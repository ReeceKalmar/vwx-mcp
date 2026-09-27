"""Generate and run recorded SDK host fixtures through an injected job sender.

The CLI only writes plans. It never connects to Vectorworks. Contract batches
exercise the deployed adapter with a native-call canary; they are not native API
coverage. Native cases are a small explicit fixture library, never inferred from
arbitrary catalog defaults. Every job requires the exact disposable document.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import ntpath
import os
from pathlib import Path
import re
import textwrap
import uuid


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT_PREFIX = 'VWX-MCP-SDK-TEST-'
MODULE_FILES = ('sdk_catalog.json', 'sdk_runtime.py', 'sdk_generated.py', 'sdk_sequences.py')
FIXTURE_UUID = '12345678-1234-4321-8765-123456789abc'
MAX_BATCH_CASES = 2048
UNCERTAIN_TRANSPORT_CODES = frozenset({'VW_DISPATCH_UNCONFIRMED', 'VW_DISPATCH_STUCK', 'VW_UNKNOWN'})
UNCLAIMED_TRANSPORT_CODES = frozenset({'VW_JOB_UNCLAIMED', 'VW_BRIDGE_PAUSED', 'VW_BRIDGE_DOWN'})


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_runtime(root):
    spec = importlib.util.spec_from_file_location('sdk_host_suite_runtime', Path(root) / 'vwx-plugin/sdk_runtime.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _document_path(value):
    """Require a named Windows file, never a prefix-only or unsaved document."""
    if not isinstance(value, str) or not ntpath.isabs(value):
        raise ValueError('An absolute disposable Vectorworks document path is required')
    normalized = ntpath.normpath(value)
    if not ntpath.basename(normalized).startswith(DOCUMENT_PREFIX) or not normalized.lower().endswith('.vwx'):
        raise ValueError('The exact document must be a ' + DOCUMENT_PREFIX + '*.vwx file')
    if '..' in re.split(r'[\\/]', value):
        raise ValueError('Parent traversal is not permitted in the disposable document path')
    return normalized


def _type(parameter):
    return ' '.join(parameter['type'].upper().split())


def _sample(parameter, function, entry=None):
    kind = _type(parameter)
    if kind == 'HANDLE':
        return FIXTURE_UUID
    if kind == 'BOOLEAN':
        return True
    if kind in {'INTEGER', 'LONGINT', 'TEXTSTYLE'}:
        return 1
    if kind.startswith('REAL'):
        return 1.25
    if kind == 'CHAR':
        return 'A'
    if kind in {'STRING', 'DYNARRAY[] OF CHAR'}:
        return 'fixture'
    if kind == 'CRITERIA':
        return '((T=RECT))'
    if kind in {'POINT', 'POINT3D', 'VECTOR'}:
        return [1.0, 2.0] if kind == 'POINT' else [1.0, 2.0, 3.0]
    if kind in {'COLOR', 'RGBCOLOR'}:
        return [0, 32768, 65535]
    if kind == 'PROCEDURE':
        mode = (entry or {}).get('callback_contract', {}).get('mode', 'collect')
        descriptor = {'mode': mode, 'limit': 2}
        descriptor.update({'filter': {'object_types': [3]}, 'conflict': {'action': 'skip'},
                           'dialog': {'events': {}}}.get(mode, {}))
        return descriptor
    if kind == 'ARRAY':
        if function == 'SetListBoxTabStops':
            return [10, 20]
        if parameter['name'] == 'arrOptions':
            return ['category', 'setting', 'label']
        return ['first', 'second']
    if kind == 'ANY':
        return {'fixture': [1, 'text']}
    raise ValueError('No transport sample for SDK type ' + kind)


def _mutations(parameter, entry=None):
    """Independent transport/ABI examples; never native semantic defaults."""
    kind = _type(parameter)
    bad, good = [], []
    if kind == 'BOOLEAN':
        bad, good = [(0, 'SDK_TYPE'), ('true', 'SDK_TYPE'), (None, 'SDK_TYPE')], [False, True]
    elif kind in {'INTEGER', 'LONGINT', 'TEXTSTYLE'}:
        low, high = {'INTEGER': (-32768, 32767), 'LONGINT': (-2147483648, 2147483647),
                     'TEXTSTYLE': (0, 31)}[kind]
        bad = [(True, 'SDK_TYPE'), (1.5, 'SDK_TYPE'), ('1', 'SDK_TYPE'),
               (low - 1, 'SDK_RANGE'), (high + 1, 'SDK_RANGE')]
        good = [low, 0, high]
    elif kind.startswith('REAL'):
        bad, good = [(True, 'SDK_TYPE'), ('1', 'SDK_TYPE'), (None, 'SDK_TYPE')], [-1e100, 0, 1e100]
    elif kind in {'STRING', 'DYNARRAY[] OF CHAR', 'CRITERIA', 'CHAR'}:
        bad = [(None, 'SDK_TYPE'), (17, 'SDK_TYPE')]
        if kind == 'CHAR':
            bad += [('', 'SDK_RANGE'), ('AB', 'SDK_RANGE')]
            good = ['A', 'é']
        else:
            good = ['', "Unicode é and a quote '"]
            if (entry or {}).get('name') == 'UprString':
                good = ['', 'Mixed ASCII case']
    elif kind in {'POINT', 'POINT3D', 'VECTOR'}:
        size = 2 if kind == 'POINT' else 3
        bad = [(0, 'SDK_TYPE'), ([0] * (size - 1), 'SDK_TYPE'),
               ([0] * (size + 1), 'SDK_TYPE'), ([True] + [0] * (size - 1), 'SDK_TYPE')]
        good = [[0] * size, [-1.25] * size]
    elif kind in {'COLOR', 'RGBCOLOR'}:
        bad = [([0, 0], 'SDK_TYPE'), ([0, 0, 0, 0], 'SDK_TYPE'),
               ([-1, 0, 0], 'SDK_RANGE'), ([65536, 0, 0], 'SDK_RANGE'), ([True, 0, 0], 'SDK_TYPE')]
        good = [[0, 0, 0], [65535, 65535, 65535]]
    elif kind == 'HANDLE':
        bad = [('not-a-uuid', 'SDK_HANDLE'), ('00000000-0000-0000-0000-000000000000', 'SDK_HANDLE')]
        if parameter.get('nullable') is not True:
            bad.append((None, 'SDK_HANDLE'))
        good = [FIXTURE_UUID] + ([None] if parameter.get('nullable') is True else [])
    elif kind == 'ARRAY':
        # Element constraints depend on the individual API and are not guessed.
        bad = [(None, 'SDK_TYPE'), ({}, 'SDK_TYPE'), ('array', 'SDK_TYPE')]
    elif kind == 'PROCEDURE':
        descriptor = _sample(parameter, (entry or {}).get('name', ''), entry)
        bad = [({}, 'SDK_TYPE'), (dict(descriptor, limit=0), 'SDK_RANGE'),
               (dict(descriptor, limit=True), 'SDK_TYPE')]
        good = [dict(descriptor, limit=1), dict(descriptor, limit=100000)]
    # ANY accepts every finite JSON value, so no finite transport value is a
    # universally invalid type. Non-JSON objects/nonfinite numbers are tested
    # separately by the offline runtime suite, not smuggled through JSON here.
    return bad, good


def adapter_cases(name, entry, runtime, catalog):
    """Concrete tests for every API, with context-blocked type checks excluded."""
    arguments = {p['name']: _sample(p, name, entry) for p in entry['parameters']}
    cases = []

    def add(suffix, params, mode='invoke_rejection', code='SDK_ARGUMENTS', context=None, dimension='envelope'):
        case = {'id': name + ':' + suffix, 'function': name, 'mode': mode,
                'params': params, 'dimension': dimension, 'expect': {'code': code} if code else {'status': 'ok'}}
        if context:
            case['invocation_context'] = context
        cases.append(case)

    add('generated_envelope', [], mode='generated_rejection')
    for label, value in [('null', None), ('array', []), ('extra_envelope_key', {'unexpected': 1}),
                         ('arguments_array', {'arguments': []}), ('options_array', {'options': []}),
                         ('unknown_option', {'options': {'unknown': True}}),
                         ('force_not_boolean', {'options': {'force': 'yes'}})]:
        add(label, value)
    extra = '__sdk_host_suite_unknown_argument__'
    while extra in arguments:
        extra += '_'
    add('extra_argument', {'arguments': dict(arguments, **{extra: 0})}, dimension='unknown_argument')
    for parameter in entry['parameters']:
        if parameter.get('required', True):
            add('missing:' + parameter['name'], {'arguments': {k: v for k, v in arguments.items() if k != parameter['name']}},
                dimension='missing_argument')

    default = runtime.validate(name, {'arguments': arguments}, catalog=catalog)
    # This is validate-only: force/sequence context never authorizes a native call.
    controlled = {'arguments': arguments, 'options': {'force': True}}
    context = {'sequence': True}
    baseline = runtime.validate(name, controlled, catalog=catalog, invocation_context=context)
    if 'error' in baseline:
        if baseline.get('code') not in {'SDK_CONTEXT', 'SDK_UNSUPPORTED'}:
            raise ValueError('Invalid transport baseline for %s: %s' % (name, baseline))
        add('context_prerequisite', controlled, code=baseline['code'], context=context, dimension='context_rejection')
    else:
        add('accepted_transport', controlled, mode='validate_only', code=None, context=context, dimension='accepted_transport')
        if name == 'UprString':
            add('unsupported_unicode', {'arguments': {'str': 'Straße'}}, code='SDK_UNSUPPORTED',
                dimension='compatibility_input_constraint')
        for parameter in entry['parameters']:
            bad, good = _mutations(parameter, entry)
            for index, (value, code) in enumerate(bad):
                payload = copy.deepcopy(controlled)
                payload['arguments'][parameter['name']] = value
                add('invalid:%s:%d' % (parameter['name'], index), payload, code=code,
                    context=context, dimension='type_or_range_rejection')
            for index, value in enumerate(good):
                payload = copy.deepcopy(controlled)
                payload['arguments'][parameter['name']] = value
                add('boundary:%s:%d' % (parameter['name'], index), payload, mode='validate_only', code=None,
                    context=context, dimension='accepted_abi_boundary')
    return cases, default, baseline


def _capture(name):
    return {'$capture': name}


def native_fixtures(run_id):
    """Explicit native input/output contracts from the SDK's function docs.

    Arithmetic assertions follow mathematical definitions. Coordinate fixtures
    use nondegenerate points; string fixtures use ASCII unless Unicode is the
    function's documented purpose. Formatting cases use zero round trips so
    document precision/unit labels cannot change the asserted numeric value.
    """
    steps = []

    def case(name, arguments, expected, label=None, *, predicate='equals', capture=None, path=None):
        step = {'id': 'native:' + (label or name), 'kind': 'native', 'name': name,
                'arguments': arguments, 'assertions': [{'path': path or ['result'], predicate: expected}],
                'evidence_basis': 'Official SDK 3200 vs.py function description and exact signature',
                'native_status': 'pending_not_executed'}
        if capture:
            step['capture'] = {'name': capture, 'path': ['result']}
        steps.append(step)

    case('GetVersion', {}, 32, path=['result', 0])
    for name, arguments, expected in [
        ('Abs', {'v': -12.5}, 12.5), ('Sqr', {'v': -3.0}, 9.0),
        ('Sqrt', {'v': 81.0}, 9.0), ('Sin', {'v': 0.0}, 0.0),
        ('Cos', {'v': 0.0}, 1.0), ('Tan', {'v': 0.0}, 0.0),
        ('ArcSin', {'v': 0.0}, 0.0), ('ArcCos', {'v': 1.0}, 0.0),
        ('ArcTan', {'v': 0.0}, 0.0), ('Exp', {'v': 0.0}, 1.0),
        ('Ln', {'v': 1.0}, 0.0), ('Deg2Rad', {'degreeValue': 180.0}, math.pi),
        ('Rad2Deg', {'radianValue': math.pi}, 180.0),
        ('Round', {'v': 2.25}, 2), ('Trunc', {'v': -2.75}, -2),
        ('Min', {'val1': -2.0, 'val2': 3.0}, -2.0),
        ('Max', {'val1': -2.0, 'val2': 3.0}, 3.0),
        ('Norm', {'Vec': [3.0, 4.0, 0.0]}, 5.0),
        ('UnitVec', {'Vect': [3.0, 0.0, 0.0]}, [1.0, 0.0, 0.0]),
        ('Vec2Ang', {'Vect': [0.0, 1.0, 0.0]}, 90.0),
        ('Ang2Vec', {'angleR': 0.0, 'Length': 2.0}, [2.0, 0.0, 0.0]),
        ('AngBVec', {'v1': [1, 0, 0], 'v2': [0, 1, 0]}, 90.0),
        ('DotProduct', {'v1': [1, 2, 3], 'v2': [4, 5, 6]}, 32.0),
        ('CrossProduct', {'v1': [1, 0, 0], 'v2': [0, 1, 0]}, [0.0, 0.0, 1.0]),
        ('Perp', {'Vec': [1, 0, 0]}, [0.0, -1.0, 0.0]),
        ('Comp', {'v1': [3, 4, 0], 'v2': [1, 0, 0], 'v3': [0, 0, 0], 'v4': [0, 0, 0]}, [[3, 0, 0], [0, 4, 0]]),
        ('Distance', {'x1': 0, 'y1': 0, 'x2': 3, 'y2': 4}, 5.0),
        ('Distance3D', {'x1': 0, 'y1': 0, 'z1': 0, 'x2': 2, 'y2': 3, 'z2': 6}, 7.0),
        ('Eq', {'value1': 2.0, 'value2': 2.005, 'tolerance': 0.01}, True),
        ('EqPercent', {'value1': 100.0, 'value2': 100.0, 'percent': 1.0}, True),
        ('EqualPt', {'p1': [3, 4], 'p2': [3, 4]}, True),
        ('EqPt', {'pt1': [3, 4, 0], 'pt2': [3, 4, 0], 'tolerance': 0.01}, True),
        ('EqPt2D', {'pt1': [3, 4, 0], 'pt2': [3, 4, 0], 'tolerance': 0.01}, True),
        ('EqPt3D', {'pt1': [3, 4, 5], 'pt2': [3, 4, 5], 'tolerance': 0.01}, True),
        ('EqualRect', {'rectAp1': [0, 10], 'rectAp2': [10, 0], 'rectBp1': [0, 10], 'rectBp2': [10, 0]}, True),
        ('PtInRect', {'point': [5, 5], 'rect1': [0, 10], 'rect2': [10, 0]}, True),
        ('PtOnLine', {'pt': [5, 0, 0], 'begPt': [0, 0, 0], 'endPt': [10, 0, 0], 'tolerance': 0.01}, True),
        ('PtPerpLine', {'pt': [5, 3, 0], 'begPt': [0, 0, 0], 'endPt': [10, 0, 0]}, [5, 0, 0]),
        ('PtPerpLine3D', {'pt': [5, 3, 4], 'pt0': [0, 0, 0], 'pt1': [10, 0, 0]}, [5, 0, 0]),
        ('PtPerpCircle', {'pt': [5, 0, 0], 'cenPt': [0, 0, 0], 'radius': 2.0}, [2, 0, 0]),
        ('ThreePtCenter', {'pt1': [1, 0, 0], 'pt2': [0, 1, 0], 'pt3': [-1, 0, 0]}, [0, 0, 0]),
        ('UnionRect', {'p1': [0, 10], 'p2': [10, 0], 'p3': [5, 20], 'p4': [20, -5], 'p5': [0, 0], 'p6': [0, 0]}, [[0, 20], [20, -5]]),
        ('Chr', {'v': 65}, 'A'), ('Ord', {'v': 'A'}, 65),
        ('UniChr', {'v': 233}, 'é'), ('Len', {'v': 'Vectorworks'}, 11),
        ('LenEncoding', {'v': 'ABC', 'encoding': 3}, 3),
        ('Concat', {'txt': 'SDK fixture'}, 'SDK fixture'),
        ('Copy', {'source': 'abcdef', 'index': 2, 'count': 3}, 'bcd'),
        ('Delete', {'source': 'abcdef', 'index': 2, 'count': 3}, 'aef'),
        ('UprString', {'str': 'Vectorworks'}, 'VECTORWORKS'),
        ('Pos', {'subStr': 'cd', 'str': 'abcdef'}, 3),
        ('SubString', {'text': 'red,green,blue', 'delimiter': ',', 'index': 2}, 'green'),
        ('Num2Str', {'decPlace': 0, 'v': 42.0}, '42'),
        ('Str2Num', {'s': '42'}, 42.0),
    ]:
        case(name, arguments, expected)
    case('Random', {}, [0.0, 1.0], predicate='range_inclusive')
    # Additional meaningful branch/edge fixtures, not merely one happy input.
    case('Copy', {'source': 'abc', 'index': 1, 'count': 0}, '', 'Copy_empty')
    case('Pos', {'subStr': 'missing', 'str': 'abcdef'}, 0, 'Pos_missing')
    case('Len', {'v': ''}, 0, 'Len_empty')
    case('EqualPt', {'p1': [0, 0], 'p2': [1, 0]}, False, 'EqualPt_false')
    case('PtInRect', {'point': [20, 20], 'rect1': [0, 10], 'rect2': [10, 0]}, False, 'PtInRect_outside')
    for formatter, parser, argname, parser_arg in [
        ('Angle2Str', 'Str2Angle', 'value', 'str'),
        ('Area2Str', 'Str2Area', 'value', 'str'),
        ('Volume2Str', 'Str2Volume', 'value', 'str'),
        ('Num2StrF', 'Str2Num', 'vDistance', 's'),
    ]:
        key = 'formatted_' + formatter
        case(formatter, {argname: 0.0}, True, predicate='nonempty_string', capture=key)
        case(parser, {parser_arg: _capture(key)}, 0.0, parser + '_roundtrip_' + formatter)
    return steps


def document_fixtures(run_id, root=ROOT):
    """Reuse the explicit rectangle/polygon/text/worksheet recipes, with oracles.

    Creation results are captured in the creation job; all geometry/text/cell
    assertions remain in later jobs. Nothing is deleted after the run.
    """
    spec = importlib.util.spec_from_file_location('sdk_host_suite_probe', Path(root) / 'tools/sdk_live_probe.py')
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    steps = []
    for original in probe.build_plan('document', run_id)['steps'][4:]:
        step = {'id': 'document:' + original['id'], 'kind': 'native',
                'evidence_basis': 'Document fixture recorded in LIVE_SDK_2027.json; assertions apply to the new run only',
                'native_status': 'pending_not_executed',
                'prerequisites': ['Top/Plan view with an active design layer in the exact disposable document']}
        if 'calls' in original:
            step['calls'] = copy.deepcopy(original['calls'])
        else:
            step.update(copy.deepcopy(original['call']))
        if 'expect' in original:
            step['assertions'] = [copy.deepcopy(original['expect'])]
        elif original['id'] == 'inspect_rectangle_bbox':
            step['assertions'] = [{'path': ['result'], 'equals': [[0, 20], [30, 0]]}]
        elif 'capture' in original:
            step['assertions'] = [{'path': original['capture']['path'], 'valid_uuid': True}]
        else:
            # These are setters/recalculation, not semantic readback credit.
            step['assertions'] = [{'path': ['status'], 'equals': 'ok'}]
            step['verification_dimension'] = 'native execution/return contract; semantic readback is a later job'
        if 'capture' in original:
            step['capture'] = copy.deepcopy(original['capture'])
        steps.append(step)
    return steps


def _functions(job):
    return [call['name'] for call in job['calls']] if 'calls' in job else [job['name']]


def classify(entry, baseline, controlled, native_ids):
    """Conservative triage metadata; classifications never authorize execution."""
    name = entry['name']
    text = (name + ' ' + entry.get('category', '') + ' ' + entry.get('description', '')).lower()
    prerequisites = ['Vectorworks 2027, matching deployed catalog/runtime', 'Exact disposable document path active']
    flags = []
    context = entry.get('context', {})
    if 'error' in controlled:
        flags.append('unsupported_context_or_representation')
        prerequisites.append(controlled['error'])
    elif 'error' in baseline:
        flags.append('sequence_or_quarantine_prerequisite')
        prerequisites.append(baseline['error'])
    if any(word in text for word in ('dialog', 'modal', 'alert', 'user input', 'getpt', 'getmouse')):
        flags.append('interactive_or_dialog_review')
        prerequisites.append('Designed interactive fixture and user participation where required')
    if any(word in text for word in ('file', 'folder', 'import', 'export', 'save', 'path name', 'pathname')):
        flags.append('file_or_external_resource_review')
        prerequisites.append('Explicit disposable file/resource paths and controlled read/write fixtures')
    if any(_type(p) == 'HANDLE' for p in entry['parameters']):
        flags.append('typed_object_fixture')
        prerequisites.append('Known valid UUID for the documented object/resource type')
    if any(_type(p) == 'PROCEDURE' for p in entry['parameters']):
        flags.append('callback_protocol')
        prerequisites.append('Supported callback protocol and callback result assertions')
    if name.startswith(('Set', 'Create', 'Add', 'Delete', 'Del', 'Remove', 'Begin', 'End', 'Import', 'Export', 'Save', 'Reset')):
        flags.append('potential_mutation')
        prerequisites.append('Creation/setter fixture followed by independent readback and explicit retained artifacts')
    if not native_ids:
        flags.append('native_fixture_not_yet_designed')
        prerequisites.append('Review official semantics and provide concrete native inputs with an independent oracle')
    return {'flags': flags, 'classification_method': 'Conservative catalog/name triage, not a proof of side effects',
            'prerequisites': prerequisites, 'catalog_context': context,
            'default_adapter_status': 'rejected' if 'error' in baseline else 'validated_without_dispatch',
            'native_case_ids': native_ids, 'native_status': 'pending_not_executed',
            'semantic_verification': False}


def build_plan(document_path, *, root=ROOT, run_id=None, batch_size=1024,
               include_contracts=True, include_native=True, include_document=False):
    """Build reproducible tests; generated samples are never native fixtures."""
    document_path = _document_path(document_path)
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH_CASES:
        raise ValueError('batch_size must be 1..%d' % MAX_BATCH_CASES)
    run_id = run_id or uuid.uuid4().hex[:12]
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id):
        raise ValueError('Invalid run_id')
    root = Path(root)
    catalog = json.loads((root / 'vwx-plugin/sdk_catalog.json').read_text(encoding='utf-8'))
    runtime = _load_runtime(root)
    native = native_fixtures(run_id) if include_native else []
    if include_document:
        native.extend(document_fixtures(run_id, root))
    native_by_api, compatibility_by_api = {}, {}
    for step in native:
        step['function_execution_kinds'] = {
            name: ('compatibility' if catalog['functions'][name].get('compatibility', {}).get('native_execution') == 'blocked'
                   else 'native') for name in _functions(step)}
        if 'compatibility' in step['function_execution_kinds'].values():
            step['execution_kind'] = 'compatibility'
        for name in _functions(step):
            (compatibility_by_api if step['function_execution_kinds'][name] == 'compatibility' else native_by_api).setdefault(name, []).append(step['id'])
    all_cases, functions = [], {}
    for name, entry in sorted(catalog['functions'].items()):
        cases, default, controlled = adapter_cases(name, entry, runtime, catalog)
        functions[name] = classify(entry, default, controlled, native_by_api.get(name, []))
        functions[name]['compatibility_case_ids'] = compatibility_by_api.get(name, [])
        functions[name]['adapter_case_count'] = len(cases) if include_contracts else 0
        functions[name]['type_checks_blocked'] = 'error' in controlled
        if include_contracts:
            all_cases.extend(cases)
    jobs = [{'id': 'contracts:%04d' % (offset // batch_size), 'kind': 'adapter_contract',
             'cases': all_cases[offset:offset + batch_size]}
            for offset in range(0, len(all_cases), batch_size)]
    jobs.extend(native)
    return {'schema_version': 1, 'run_id': run_id, 'document_path': document_path,
            'sdk': {key: catalog[key] for key in ('vectorworks_year', 'sdk_version', 'sdk_build')},
            'source_sha256': {name: _digest(root / 'vwx-plugin' / name) for name in MODULE_FILES},
            'functions': functions, 'jobs': jobs,
            'summary': {'sdk_functions': len(functions), 'adapter_cases': len(all_cases),
                        'adapter_jobs': len(jobs) - len(native),
                        'native_cases': sum(step.get('execution_kind') != 'compatibility' for step in native),
                        'compatibility_cases': sum(step.get('execution_kind') == 'compatibility' for step in native),
                        'native_apis_with_designed_fixture': len(native_by_api),
                        'native_apis_without_fixture': len(functions) - len(native_by_api)},
            'limitations': [
                'Adapter cases use a canary or validation-only path and never count as native API execution.',
                'Accepted ABI boundaries do not establish valid native resource indices or geometry.',
                'Catalog/name classifications are conservative review hints, not a comprehensive effect system.',
                'Only explicit native fixtures execute vs functions; unmeasured functions remain pending.',
                'Each native fixture is one menu job; dependent native reads require later jobs.',
                'No automatic retries, rollback, deletion, document switching, focus changes or dialog dismissal.',
            ]}


def _substitute(value, captures):
    if isinstance(value, dict):
        if '$capture' in value:
            if set(value) != {'$capture'} or value['$capture'] not in captures:
                raise ValueError('Unknown or malformed capture')
            return captures[value['$capture']]
        return {k: _substitute(v, captures) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, captures) for v in value]
    return value


# Shared host code is serialized as source in execute_script. It runs only
# after the path/version/hash guards. Canary attempts are counted even when
# the adapter catches their exception and returns a structured error.
_CONTRACT_BODY = '''
class _SDKSuiteCanary:
    def __init__(self):
        self.attempts = []
    def GetVersion(self):
        return (32, 0, 0, 2)
    def __getattr__(self, name):
        self.attempts.append(name)
        raise RuntimeError('SDK host suite blocked native access: ' + name)
    def target(self, *args):
        self.attempts.append('target')
        raise RuntimeError('SDK host suite blocked native dispatch')

_suite_records = []
for _case in _suite_payload['cases']:
    _canary = _SDKSuiteCanary()
    _mode = _case['mode']
    if _mode == 'generated_rejection':
        _saved_vs = _generated.vs
        _generated.vs = _canary
        try:
            _actual = _generated.WRAPPERS[_case['function']](_case['params'])
        finally:
            _generated.vs = _saved_vs
    elif _mode == 'invoke_rejection':
        _actual = _runtime.invoke(_case['function'], _case['params'], _canary.target,
                                 vs_module=_canary, catalog=_catalog,
                                 invocation_context=_case.get('invocation_context'))
    elif _mode == 'validate_only':
        _actual = _runtime.validate(_case['function'], _case['params'], catalog=_catalog,
                                   invocation_context=_case.get('invocation_context'))
    else:
        raise ValueError('Unknown contract mode')
    _expect = _case['expect']
    _passed = not _canary.attempts and isinstance(_actual, dict) and _actual.get('function') == _case['function']
    if 'code' in _expect:
        _passed = _passed and bool(_actual.get('error')) and _actual.get('code') == _expect['code'] and _actual.get('dispatched') is False
    else:
        _passed = _passed and _actual.get('status') == 'ok' and not _actual.get('error')
    _suite_records.append({'id': _case['id'], 'function': _case['function'], 'mode': _mode,
                           'dimension': _case['dimension'], 'passed': bool(_passed),
                           'actual': _actual, 'canary_attempts': _canary.attempts,
                           'native_api_executed': False})
__result__ = {'status': 'ok', 'records': _suite_records, 'native_api_executed': False}
'''


_SURFACE_BODY = '''
_sentinel = object()
_present, _missing, _noncallable, _inspection_errors = [], [], [], {}
if set(_suite_payload['names']) != set(_catalog['functions']):
    raise ValueError('Surface probe must inspect the exact SDK catalog names')
for _name in _suite_payload['names']:
    try:
        _target = getattr(vs, _name, _sentinel)
        if _target is _sentinel:
            _missing.append(_name)
        elif callable(_target):
            _present.append(_name)
        else:
            _noncallable.append(_name)
    except Exception as _error:
        _inspection_errors[_name] = str(_error)
__result__ = {'status': 'ok', 'kind': 'native_surface_presence',
              'indexed_function_count': len(_suite_payload['names']),
              'present': _present, 'missing': _missing, 'noncallable': _noncallable,
              'inspection_errors': _inspection_errors,
              'host': {'GetVersionEx': list(vs.GetVersionEx())},
              'sdk': {key: _catalog[key] for key in ('vectorworks_year', 'sdk_version', 'sdk_build')},
              'source_sha256': _suite_hashes, 'tested_functions_invoked': [],
              'metadata_calls': ['GetFPathName', 'GetVersion', 'GetVersionEx'],
              'semantic_verification': False}
'''


def render_job(plan, job, captures=None):
    """Return exactly one guarded execute_script request without sending it."""
    expected_path = _document_path(plan['document_path'])
    if job.get('kind') not in {'adapter_contract', 'native', 'surface_presence'}:
        raise ValueError('Unknown job kind')
    if job['kind'] == 'surface_presence':
        payload = {'names': sorted(plan['functions'])}
        body = _SURFACE_BODY
    elif job['kind'] == 'adapter_contract':
        if not 1 <= len(job.get('cases', [])) <= MAX_BATCH_CASES:
            raise ValueError('Invalid contract batch size')
        payload = {'cases': job['cases']}
        body = _CONTRACT_BODY
    else:
        if 'calls' in job:
            payload = {'calls': _substitute(job['calls'], captures or {})}
            body = "__result__ = commands.sdk_sequence(_suite_payload)\n"
        else:
            payload = {'name': job['name'], 'arguments': _substitute(job['arguments'], captures or {})}
            body = "__result__ = commands.sdk_call(_suite_payload)\n"
    source = 'import json, os, hashlib\nimport commands\n'
    source += '_suite_payload = json.loads(%r)\n' % json.dumps(payload, ensure_ascii=True, allow_nan=False)
    source += '_suite_expected_path = %r\n' % expected_path
    source += '_suite_hashes = json.loads(%r)\n' % json.dumps(plan['source_sha256'])
    source += textwrap.dedent('''
        def _suite_run():
            global __result__, _runtime, _generated, _catalog
            actual_path = vs.GetFPathName()
            if not isinstance(actual_path, str) or os.path.normcase(os.path.normpath(actual_path)) != os.path.normcase(os.path.normpath(_suite_expected_path)):
                __result__ = {'error': 'Exact disposable document is not active', 'code': 'SDK_SUITE_DOCUMENT', 'dispatched': False, 'actual_path': actual_path}
                return
            version = vs.GetVersion()
            if not isinstance(version, (tuple, list)) or not version or version[0] != 32:
                __result__ = {'error': 'Vectorworks 2027 is required', 'code': 'SDK_SUITE_VERSION', 'dispatched': False}
                return
            directory = os.path.dirname(os.path.realpath(commands.__file__))
            for filename, expected in _suite_hashes.items():
                with open(os.path.join(directory, filename), 'rb') as stream:
                    actual = hashlib.sha256(stream.read()).hexdigest()
                if actual != expected:
                    __result__ = {'error': 'Deployed SDK files differ from this test plan', 'code': 'SDK_SUITE_SOURCE', 'dispatched': False, 'file': filename}
                    return
            _runtime, _generated, _sequences = commands._sdk_modules()
            _catalog = _runtime.load_catalog()
    ''')
    source += textwrap.indent(textwrap.dedent(body), '    ')
    source += '\n_suite_run()\n'
    return {'command': 'execute_script', 'params': {'code': source}}


def render_surface_probe(plan):
    """One standalone presence-inspection job; never a semantic test record.

    Only callable/getattr inspection is performed for the catalog names. The
    document/version guard and GetVersionEx read metadata independently. Supply
    this request directly to an authorized sender, outside run_plan's fixtures.
    """
    return render_job(plan, {'id': 'surface-presence', 'kind': 'surface_presence'})


def _at(value, path):
    if type(path) is not list or not path:
        raise ValueError('Oracle/capture path must be a nonempty list')
    for part in path:
        if type(part) is int:
            if part < 0 or type(value) not in (list, tuple):
                raise ValueError('Path indices must be nonnegative and address an array')
        elif type(part) is str:
            if type(value) is not dict:
                raise ValueError('Path keys must address a JSON object')
        else:
            raise ValueError('Path components must be string keys or integer indices')
        value = value[part]
    return value


def _finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def _equal(actual, expected, *, rel_tol=1e-9, abs_tol=1e-9):
    if type(expected) in (int, float):
        return (_finite_number(actual) and _finite_number(expected)
                and math.isclose(actual, expected, rel_tol=rel_tol, abs_tol=abs_tol))
    if type(expected) in (list, tuple):
        return (type(actual) in (list, tuple) and len(actual) == len(expected)
                and all(_equal(a, b, rel_tol=rel_tol, abs_tol=abs_tol) for a, b in zip(actual, expected)))
    if type(expected) is dict:
        return (type(actual) is dict and set(actual) == set(expected)
                and all(type(key) is str and _equal(actual[key], value, rel_tol=rel_tol, abs_tol=abs_tol)
                        for key, value in expected.items()))
    if type(expected) not in (str, bool, type(None)):
        return False
    return type(actual) is type(expected) and actual == expected


def _bbox_size(points):
    """Measure axis spans from opposite GetBBox corners, independent of origin."""
    if (type(points) not in (list, tuple) or len(points) != 2
            or any(type(point) not in (list, tuple) or len(point) != 2
                   or any(not _finite_number(value) for value in point) for point in points)):
        raise ValueError('Bounding box requires exactly two finite nonboolean 2D points')
    spans = [abs(points[1][axis] - points[0][axis]) for axis in (0, 1)]
    if not all(_finite_number(value) for value in spans):
        raise ValueError('Bounding box spans must remain finite')
    return spans


def evaluate_native(job, response):
    """Fail closed on malformed protocol, attribution, captures or predicates.

    This validates only the assertions supplied by a curated fixture. A passing
    subset does not establish every native behavior or unasserted output field.
    """
    assertions = []
    try:
        if (type(job) is not dict or type(response) is not dict
                or 'error' in response or response.get('status') != 'ok'):
            return False, assertions
        if 'calls' in job:
            calls, returned = job['calls'], response.get('results')
            if (type(calls) is not list or not calls or type(returned) is not list
                    or type(response.get('count')) is not int or response['count'] != len(calls)
                    or len(returned) != len(calls)
                    or any(type(call) is not dict or type(call.get('name')) is not str
                           or type(item) is not dict or item.get('status') != 'ok' or 'error' in item
                           or item.get('function') != call['name']
                           for call, item in zip(calls, returned))):
                return False, assertions
        elif type(job.get('name')) is not str or response.get('function') != job['name']:
            return False, assertions
        expected_assertions = job.get('assertions')
        if type(expected_assertions) is not list or not expected_assertions:
            return False, assertions
        if 'capture' in job:
            capture = job['capture']
            if (type(capture) is not dict or set(capture) != {'name', 'path'}
                    or type(capture['name']) is not str or not capture['name']):
                raise ValueError('Capture requires a nonempty name and an exact path')
            captured = _at(response, capture['path'])
            # A malformed capture must not fail only after native pass credit
            # has already been awarded or leak a non-JSON/native value onward.
            json.dumps(captured, allow_nan=False)
    except Exception as error:
        return False, [{'passed': False, 'error': 'Invalid fixture/response: ' + str(error)}]
    for expected in expected_assertions:
        try:
            predicates = {'equals', 'range_inclusive', 'nonempty_string', 'valid_uuid', 'angle_degrees', 'bbox_size'}
            if (type(expected) is not dict or set(expected) - (predicates | {'path', 'abs_tol', 'rel_tol'})
                    or len(set(expected) & predicates) != 1):
                raise ValueError('Assertion requires exactly one supported predicate and a path')
            tolerance = {name: expected.get(name, 1e-9) for name in ('abs_tol', 'rel_tol')}
            if 'angle_degrees' in expected:
                # Orientation has no relative tolerance. Keep any explicit
                # angular error budget small enough not to hide a wrong angle.
                if 'rel_tol' in expected or not _finite_number(tolerance['abs_tol']) or not 0 <= tolerance['abs_tol'] <= 1e-3:
                    raise ValueError('Angular tolerance must be absolute and between 0 and 0.001 degrees')
            elif 'bbox_size' in expected:
                # Keep explicit budgets small enough to expose rotation/no-op
                # defects; units remain the drawing's units, as for GetBBox.
                if (not _finite_number(tolerance['abs_tol']) or not 0 <= tolerance['abs_tol'] <= 1e-3
                        or not _finite_number(tolerance['rel_tol']) or not 0 <= tolerance['rel_tol'] <= 1e-6):
                    raise ValueError('Bounding-box tolerances require 0..0.001 absolute and 0..0.000001 relative')
            elif any(name in expected for name in tolerance) and 'equals' not in expected:
                raise ValueError('Numeric tolerances apply only to equals, angle_degrees or bbox_size predicates')
            if any(not _finite_number(value) or value < 0 for value in tolerance.values()):
                raise ValueError('Numeric tolerances must be finite nonnegative numbers, not booleans')
            actual = _at(response, expected['path'])
            if 'equals' in expected:
                passed = _equal(actual, expected['equals'], **tolerance)
            elif 'bbox_size' in expected:
                spans = expected['bbox_size']
                if (type(spans) not in (list, tuple) or len(spans) != 2
                        or any(not _finite_number(value) or value < 0 for value in spans)):
                    raise ValueError('Expected bounding-box size requires two finite nonnegative spans')
                passed = _equal(_bbox_size(actual), spans, **tolerance)
            elif 'angle_degrees' in expected:
                target = expected['angle_degrees']
                if not _finite_number(target):
                    raise ValueError('Angular expectation must be a finite nonboolean scalar')
                passed = False
                if _finite_number(actual):
                    # Reduce separately so finite opposite-sign inputs cannot
                    # overflow on subtraction. This tests direction, not sweep.
                    difference = abs(actual % 360 - target % 360)
                    passed = min(difference, 360 - difference) <= tolerance['abs_tol']
            elif 'range_inclusive' in expected:
                bounds = expected['range_inclusive']
                if (type(bounds) not in (list, tuple) or len(bounds) != 2
                        or not all(_finite_number(bound) for bound in bounds) or bounds[0] > bounds[1]):
                    raise ValueError('Range requires exactly two ordered finite numeric bounds')
                passed = _finite_number(actual) and bounds[0] <= actual <= bounds[1]
            elif expected.get('nonempty_string') is True:
                passed = isinstance(actual, str) and bool(actual)
            elif expected.get('valid_uuid') is True:
                passed = isinstance(actual, str) and uuid.UUID(actual).int != 0
            else:
                raise ValueError('Unknown assertion')
            assertions.append({'expected': expected, 'actual': actual, 'passed': bool(passed)})
        except Exception as error:
            assertions.append({'expected': expected, 'passed': False, 'error': str(error)})
    return bool(assertions) and all(a['passed'] for a in assertions), assertions


def execution_evidence(job, response):
    """Keep per-step provenance when a sequence mixes native and local results.

    A mixed case is conservatively labeled compatibility in the case-level
    evidence schema. The per-step entries retain separate native API credit.
    This classifies implementation, not success or proof of dispatch.
    """
    calls = job.get('calls', [{'name': job.get('name')}])
    returned = response.get('results', []) if 'calls' in job else [response]
    planned = job.get('function_execution_kinds', {})
    entries = []
    for index, call in enumerate(calls):
        item = returned[index] if index < len(returned) and isinstance(returned[index], dict) else {}
        compatible = (planned.get(call['name'], job.get('execution_kind')) == 'compatibility'
                      or bool(item.get('compatibility')) or item.get('native_dispatched') is False
                      or bool(response.get('compatibility')) or response.get('native_dispatched') is False)
        entries.append({'step': index, 'function': call['name'],
                        'execution_kind': 'compatibility' if compatible else 'native'})
    return {'execution_kind': 'compatibility' if any(e['execution_kind'] == 'compatibility' for e in entries) else 'native',
            'function_executions': entries}


def _uncertain_transport(response):
    """Transport has not established a native result, including after a claim."""
    return isinstance(response, dict) and bool(response.get('error')) and response.get('code') in UNCERTAIN_TRANSPORT_CODES


def transport_outcome(response):
    """Distinguish an undispatched request from an unknown native outcome.

    Legacy file transport emits the unclaimed/paused/down codes only after
    atomically discarding the queued file. Older responses lack dispatched=False.
    Contradictory dispatch evidence is uncertain, never permission to replay.
    Successful local compatibility responses are not transport errors.
    """
    if not isinstance(response, dict) or not response.get('error'):
        return None
    if response.get('code') in UNCERTAIN_TRANSPORT_CODES:
        return 'uncertain'
    blocked = (response.get('code') in UNCLAIMED_TRANSPORT_CODES
               or response.get('dispatched') is False or response.get('native_dispatched') is False)
    if blocked:
        if (response.get('dispatched') is True or response.get('native_dispatched') is True
                or response.get('results')):
            return 'uncertain'
        return 'blocked'
    return None


def _unwrap(response):
    if isinstance(response, str):
        response = json.loads(response)
    # An outer transport failure must retain its cid/code and raw response,
    # rather than becoming a generic execute_script exception or native failure.
    if transport_outcome(response):
        return response
    if isinstance(response, dict) and 'output' in response and 'result' in response:
        if response.get('error'):
            raise RuntimeError('execute_script error: ' + str(response['error']))
        response = response['result']
    if not isinstance(response, dict):
        raise RuntimeError('Expected a JSON result object')
    return response


def run_plan(send_job, plan, journal_path):
    """Execute through an explicitly injected sender, stopping without replay.

    Each intent is fsynced before sending. Each returned case is journaled with
    its exact input and output. A pre-existing journal is never resumed or
    overwritten: an interrupted request may already have executed. The caller
    can inspect or reconcile it, but this runner does not retry it automatically.
    """
    if not callable(send_job):
        raise TypeError('send_job must be an explicitly supplied callable')
    journal_path = Path(journal_path)
    records, captures = [], {}
    result = {'schema_version': 1, 'run_id': plan['run_id'], 'document_path': plan['document_path'],
              'source_sha256': plan['source_sha256'], 'records': records, 'captures': captures,
              'status': 'running', 'native_functions_passed': [], 'adapter_functions_passed': [],
              'compatibility_functions_passed': [],
              'limitations': plan['limitations']}
    native_passed, compatibility_passed, adapter_pass_counts = set(), set(), {}
    expected_adapter_counts = {}
    for job in plan['jobs']:
        for case in job.get('cases', []):
            expected_adapter_counts[case['function']] = expected_adapter_counts.get(case['function'], 0) + 1
    # Exclusive creation is part of the no-replay contract; do not change to w/a.
    with journal_path.open('x', encoding='utf-8') as stream:
        def journal(event):
            stream.write(json.dumps(dict(event, utc=datetime.now(timezone.utc).isoformat()), ensure_ascii=False, allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

        journal({'event': 'start', 'run_id': plan['run_id'], 'document_path': plan['document_path'],
                 'source_sha256': plan['source_sha256'], 'plan_summary': plan['summary']})
        for job in plan['jobs']:
            try:
                if job['kind'] not in {'adapter_contract', 'native'}:
                    raise ValueError('Presence probes are standalone; do not include them in fixture jobs')
                request = render_job(plan, job, captures)
                journal({'event': 'intent', 'job_id': job['id'], 'kind': job['kind'], 'job': job,
                         'request_sha256': hashlib.sha256(request['params']['code'].encode()).hexdigest()})
                response = _unwrap(send_job(request))
                if _uncertain_transport(response):
                    # No native assertion can be evaluated without a confirmed
                    # result. Preserve unknown separately from a measured fail.
                    record = {'id': job['id'], 'job_id': job['id'], 'kind': job['kind'],
                              'result': response, 'status': 'uncertain', 'passed': None,
                              'assertions': [], 'native_api_executed': None}
                    if job['kind'] == 'native':
                        record.update(functions=_functions(job),
                                      execution_kind=job.get('execution_kind', 'native'),
                                      input=_substitute(job.get('calls', job.get('arguments')), captures))
                    else:
                        record.update(functions=sorted({case['function'] for case in job['cases']}),
                                      input={'cases': job['cases']})
                    records.append(record)
                    journal({'event': 'case_result', **record})
                    result.update(status='uncertain', uncertain_job=job['id'], error=response['error'])
                    journal({'event': 'stop', 'status': 'uncertain', 'job_id': job['id'],
                             'code': response['code'], 'cid': response.get('cid')})
                    break
                if job['kind'] == 'adapter_contract':
                    returned = response.get('records')
                    if response.get('status') != 'ok' or not isinstance(returned, list) or len(returned) != len(job['cases']):
                        raise RuntimeError('Incomplete adapter batch response: ' + str(response))
                    for expected, record in zip(job['cases'], returned):
                        if record.get('id') != expected['id'] or record.get('function') != expected['function']:
                            raise RuntimeError('Adapter response identity mismatch')
                        record = dict(record, input=expected['params'], job_id=job['id'], kind='adapter_contract')
                        records.append(record)
                        journal({'event': 'case_result', **record})
                        if record.get('passed') is True:
                            name = record['function']
                            adapter_pass_counts[name] = adapter_pass_counts.get(name, 0) + 1
                    passed = all(r.get('passed') is True for r in returned)
                else:
                    passed, assertions = evaluate_native(job, response)
                    record = {'id': job['id'], 'job_id': job['id'], 'functions': _functions(job), 'kind': 'native',
                              'input': _substitute(job.get('calls', job.get('arguments')), captures), 'result': response,
                              'assertions': assertions, 'passed': passed}
                    record.update(execution_evidence(job, response))
                    records.append(record)
                    journal({'event': 'case_result', **record})
                    if passed:
                        for execution in record['function_executions']:
                            (compatibility_passed if execution['execution_kind'] == 'compatibility' else native_passed).add(execution['function'])
                        if job.get('capture'):
                            capture = job['capture']
                            captures[capture['name']] = _at(response, capture['path'])
                if not passed:
                    result.update(status='failed', failed_job=job['id'])
                    journal({'event': 'stop', 'status': 'failed', 'job_id': job['id']})
                    break
            except Exception as error:
                # Could be transport loss after dispatch. Never infer no mutation
                # merely because the sender raised or its response was truncated.
                result.update(status='uncertain', uncertain_job=job['id'], error=str(error))
                journal({'event': 'stop', 'status': 'uncertain', 'job_id': job['id'], 'error': str(error)})
                break
        else:
            result['status'] = 'passed'
        adapter_passed = {name for name, count in adapter_pass_counts.items()
                          if count == expected_adapter_counts[name]}
        result['native_functions_passed'] = sorted(native_passed)
        result['adapter_functions_passed'] = sorted(adapter_passed)
        result['compatibility_functions_passed'] = sorted(compatibility_passed)
        result['native_semantics_fully_verified'] = False
        journal({'event': 'finish', 'status': result['status'], 'native_functions_passed': sorted(native_passed),
                 'compatibility_functions_passed': sorted(compatibility_passed),
                 'adapter_functions_all_planned_cases_passed': sorted(adapter_passed),
                 'native_semantics_fully_verified': False})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--document', required=True, help='Exact absolute disposable .vwx path')
    parser.add_argument('--run-id')
    parser.add_argument('--batch-size', type=int, default=1024)
    parser.add_argument('--only', choices=('all', 'contracts', 'native'), default='all')
    parser.add_argument('--document-fixtures', action='store_true', help='Also create and retain rectangle/polygon/text/worksheet fixtures')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = build_plan(args.document, run_id=args.run_id, batch_size=args.batch_size,
                      include_contracts=args.only != 'native', include_native=args.only != 'contracts',
                      include_document=args.document_fixtures)
    args.output.write_text(json.dumps(plan, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), **plan['summary']}, indent=2))


if __name__ == '__main__':
    main()
