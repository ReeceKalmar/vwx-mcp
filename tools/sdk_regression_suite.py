"""Reproducible registry for reviewed native fixtures; building plans is offline.

Counts distinguish cases, native API names, and later semantic readbacks. No
catalog-generated sample is used as an actual native geometry fixture.
"""
import argparse
from collections import Counter
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = {
    'design': ('sdk_design_fixtures.py', 'design_fixtures'),
    'numeric': ('sdk_numeric_fixtures.py', 'numeric_fixtures'),
    'geometry': ('sdk_geometry_fixtures.py', 'geometry_fixtures'),
    'data': ('sdk_data_fixtures.py', 'data_fixtures'),
    'annotation': ('sdk_annotation_fixtures.py', 'annotation_fixtures'),
    'resource': ('sdk_resource_fixtures.py', 'resource_fixtures'),
    'modeling': ('sdk_modeling_fixtures.py', 'modeling_fixtures'),
}
CONDITIONAL_COMPATIBILITY_APIS = frozenset({'HArea', 'GetTextLeading', 'GetTextLength', 'GetOpacityByClassN', 'GetObjMaterialName', 'SetGradientOpacity', 'SetArc'})


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def providers():
    return {name: (load('regression_' + name, ROOT / 'tools' / filename), builder)
            for name, (filename, builder) in PROVIDERS.items()}


def families():
    return [prefix + ':' + family for prefix, (module, _) in providers().items() for family in module.FAMILIES]


def characterization_families():
    """Provider declarations are independent of optional diagnostic labeling."""
    return {prefix + ':' + family for prefix, (module, _) in providers().items()
            for family in getattr(module, 'CHARACTERIZATION_FAMILIES', ())}


def coverage_kind(job):
    """Separate an observation's purpose from actual native/compat execution.

    Old semantic fixtures have no coverage_kind field. Historical observations
    already used verification_dimension='characterization'; retain that meaning
    even when reading a saved plan made before this explicit accounting field.
    """
    explicit = job.get('coverage_kind')
    if 'coverage_kind' in job and (type(explicit) is not str or explicit not in ('semantic', 'characterization')):
        raise ValueError('Invalid fixture coverage_kind')
    measured = job.get('verification_dimension') == 'characterization'
    if measured and explicit == 'semantic':
        raise ValueError('Characterization cannot be relabeled as semantic coverage')
    return 'characterization' if measured or explicit == 'characterization' else 'semantic'


def _namespace(value, prefix):
    if isinstance(value, dict):
        if set(value) == {'$capture'}:
            return {'$capture': prefix + ':' + value['$capture']}
        return {key: _namespace(item, prefix) for key, item in value.items()}
    if isinstance(value, list):
        return [_namespace(item, prefix) for item in value]
    return value


def _sample_result(entry):
    samples = {'BOOLEAN': True, 'INTEGER': 1, 'LONGINT': 1, 'REAL': 1.0,
               'STRING': 'fixture', 'DYNARRAY[] of CHAR': 'fixture', 'CHAR': 'x',
               'HANDLE': '11111111-1111-4111-8111-111111111111',
               'POINT': [1, 2], 'POINT3D': [1, 2, 3], 'VECTOR': [1, 2, 3],
               'COLOR': [0, 0, 0], 'ARRAY': [], 'ANY': [], 'TEXTSTYLE': 0}
    shape = entry['returns']
    if shape['kind'] == 'void':
        return None
    values = [copy.deepcopy(samples[item['type']]) for item in shape['items']]
    return values if shape['kind'] == 'tuple' else values[0]


def fixture_source_hashes():
    filenames = [value[0] for value in PROVIDERS.values()] + [
        'sdk_regression_suite.py', 'run_sdk_regression.py', 'sdk_design_runner.py', 'sdk_host_suite.py']
    return {name: hashlib.sha256((ROOT / 'tools' / name).read_bytes()).hexdigest() for name in filenames}


def verify_fixture_sources(plan):
    """Refuse a stale fixture/runner revision before creating a host connection."""
    if plan.get('fixture_source_sha256') != fixture_source_hashes():
        raise ValueError('Fixture sources differ from this plan; rebuild the offline plan')


def _path_value(sample, path):
    if (not isinstance(path, list) or not 1 <= len(path) <= 16
            or any(type(part) not in (str, int) or type(part) is int and part < 0 for part in path)):
        raise ValueError('Result path must contain nonnegative indices or string keys')
    value = sample
    for part in path:
        if type(part) is int and not isinstance(value, list):
            raise ValueError('An integer result-path component requires a list')
        if type(part) is str and not isinstance(value, dict):
            raise ValueError('A string result-path component requires an object')
        try:
            value = value[part]
        except (KeyError, IndexError) as error:
            raise ValueError('Result path does not match the SDK return contract') from error
    return value


def _finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _nullable_handle_paths(calls, sdk_functions, *, sequence):
    """Only SDK HANDLE outputs may use either a UUID or a JSON null oracle."""
    paths = set()
    for index, call in enumerate(calls):
        prefix = ('results', index) if sequence else ()
        shape = sdk_functions[call['name']]['returns']
        for item_index, item in enumerate(shape['items']):
            if item['type'] != 'HANDLE':
                continue
            if shape['kind'] == 'scalar':
                paths.add(prefix + ('result',))
            elif shape['kind'] == 'tuple':
                paths.add(prefix + ('result', item_index))
                paths.add(prefix + ('outputs', item['name']))
    return paths


def _expected_shape(actual, expected, *, nullable_handle_paths=(), path=()):
    if expected is None and path in nullable_handle_paths:
        return actual is None or isinstance(actual, str)
    if type(actual) is bool:
        return type(expected) is bool
    if type(actual) in (int, float):
        return _finite_number(expected)
    if actual is None:
        return expected is None
    if isinstance(actual, str):
        return isinstance(expected, str)
    if isinstance(actual, list):
        # Empty sample arrays represent SDK ARRAY/ANY outputs of unknown length.
        return isinstance(expected, list) and (not actual or len(actual) == len(expected)
            and all(_expected_shape(a, b, nullable_handle_paths=nullable_handle_paths,
                                    path=path + (index,))
                    for index, (a, b) in enumerate(zip(actual, expected))))
    return False


def _validate_assertions(job, sample, *, nullable_handle_paths=()):
    assertions = job.get('assertions')
    if not isinstance(assertions, list) or not assertions:
        raise ValueError('At least one assertion is required: ' + job['id'])
    for assertion in assertions:
        predicate_names = {'equals', 'range_inclusive', 'nonempty_string', 'valid_uuid', 'angle_degrees', 'bbox_size'}
        if (not isinstance(assertion, dict) or 'path' not in assertion
                or set(assertion) - (predicate_names | {'path', 'abs_tol', 'rel_tol'})
                or len(set(assertion) & predicate_names) != 1):
            raise ValueError('Each assertion requires one path and one predicate')
        actual = _path_value(sample, assertion['path'])
        if 'angle_degrees' in assertion:
            tolerance = assertion.get('abs_tol', 1e-9)
            if 'rel_tol' in assertion or not _finite_number(tolerance) or not 0 <= tolerance <= 1e-3:
                raise ValueError('Angular tolerance must be absolute and between 0 and 0.001 degrees')
        elif 'bbox_size' in assertion:
            for option, maximum in (('abs_tol', 1e-3), ('rel_tol', 1e-6)):
                tolerance = assertion.get(option, 1e-9)
                if not _finite_number(tolerance) or not 0 <= tolerance <= maximum:
                    raise ValueError('Bounding-box tolerances require 0..0.001 absolute and 0..0.000001 relative')
        else:
            for option in ('abs_tol', 'rel_tol'):
                if option in assertion and ('equals' not in assertion or not _finite_number(assertion[option]) or assertion[option] < 0):
                    raise ValueError('Only equality, angular or bounding-box predicates allow numeric tolerances')
        if 'equals' in assertion:
            # This checks JSON/finite transport, not whether the sample equals
            # the real oracle. Samples never become a native result.
            json.dumps(assertion['equals'], allow_nan=False)
            if not _expected_shape(actual, assertion['equals'], nullable_handle_paths=nullable_handle_paths,
                                   path=tuple(assertion['path'])):
                raise ValueError('Expected value shape/types disagree with the SDK result contract')
        elif 'bbox_size' in assertion:
            spans = assertion['bbox_size']
            if (type(spans) not in (list, tuple) or len(spans) != 2
                    or any(not _finite_number(value) or value < 0 for value in spans)
                    or type(actual) not in (list, tuple) or len(actual) != 2
                    or any(type(point) not in (list, tuple) or len(point) != 2
                           or any(not _finite_number(value) for value in point) for point in actual)
                    or any(not _finite_number(abs(actual[1][axis] - actual[0][axis])) for axis in (0, 1))):
                raise ValueError('Bounding-box predicate requires two finite 2D points and two finite nonnegative spans')
        elif 'angle_degrees' in assertion:
            if not _finite_number(actual) or not _finite_number(assertion['angle_degrees']):
                raise ValueError('Angular predicate requires finite nonboolean scalar result and expectation')
        elif 'range_inclusive' in assertion:
            bounds = assertion['range_inclusive']
            if (not isinstance(bounds, list) or len(bounds) != 2
                    or any(not _finite_number(v) for v in bounds)
                    or bounds[0] > bounds[1] or type(actual) not in (int, float)):
                raise ValueError('Numeric range requires two ordered finite bounds and a numeric result')
        elif assertion.get('nonempty_string') is not True and assertion.get('valid_uuid') is not True:
            raise ValueError('String/UUID predicates must be true')
        elif not isinstance(actual, str):
            raise ValueError('String/UUID predicate requires a string return')


def _load_sequences(runtime):
    # The standalone sequence module imports sdk_runtime. Restore the process
    # import table after the offline validator obtains the exact helper module.
    sentinel = object()
    previous = sys.modules.get('sdk_runtime', sentinel)
    try:
        sys.modules['sdk_runtime'] = runtime
        return load('regression_sequence_validation', ROOT / 'vwx-plugin/sdk_sequences.py')
    finally:
        if previous is sentinel:
            sys.modules.pop('sdk_runtime', None)
        else:
            sys.modules['sdk_runtime'] = previous


def _capture_references(value):
    if isinstance(value, dict):
        if '$capture' in value:
            if set(value) != {'$capture'} or not isinstance(value['$capture'], str) or not value['$capture']:
                raise ValueError('Malformed capture reference')
            yield value['$capture']
        else:
            for child in value.values():
                yield from _capture_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _capture_references(child)


def validate_plan(plan):
    """Check the entire planned surface before connecting; samples stay offline."""
    host = load('regression_host_validation', ROOT / 'tools/sdk_host_suite.py')
    runtime = host._load_runtime(ROOT)
    sequences = _load_sequences(runtime)
    policy = load('regression_background_policy', ROOT / 'mcp-server/background_policy.py')
    catalog = json.loads((ROOT / 'vwx-plugin/sdk_catalog.json').read_text(encoding='utf-8'))
    index = json.loads((ROOT / 'vwx-plugin/vs_index.json').read_text(encoding='utf-8'))
    if not isinstance(plan, dict) or not isinstance(plan.get('jobs'), list) or not plan['jobs']:
        raise ValueError('A nonempty curated fixture plan is required')
    host._document_path(plan.get('document_path'))
    if not isinstance(plan.get('run_id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', plan['run_id']):
        raise ValueError('Invalid run_id')
    source_hashes = plan.get('source_sha256')
    if (not isinstance(source_hashes, dict) or set(source_hashes) != set(host.MODULE_FILES)
            or any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)
                   for value in source_hashes.values())):
        raise ValueError('Complete valid deployed-source SHA256 provenance is required')
    declared_characterizations = characterization_families()
    bare_characterizations = {name.split(':', 1)[1] for name in declared_characterizations}
    captures, capture_families, seen = {}, {}, {}
    for job in plan['jobs']:
        if (not isinstance(job, dict) or not isinstance(job.get('id'), str) or not job['id']
                or job['id'] in seen or job.get('kind') != 'native' or 'code' in job or 'cases' in job):
            raise ValueError('Duplicate or invalid fixture')
        if job.get('native_status') != 'pending_not_executed':
            raise ValueError('Fixture plans must retain pending native status')
        family = job.get('fixture_family')
        if not isinstance(family, str) or not family:
            raise ValueError('Every fixture requires a family')
        classification = coverage_kind(job)
        if ((family in declared_characterizations or family in bare_characterizations)
                and classification != 'characterization'):
            raise ValueError('Declared characterization family cannot receive semantic coverage')
        if not isinstance(job.get('verifies_jobs', []), list):
            raise ValueError('verifies_jobs must be a list')
        if any(prior not in seen for prior in job.get('verifies_jobs', [])):
            raise ValueError('Readback refers to a missing/later job: ' + job['id'])
        if any(seen[prior] != family for prior in job.get('verifies_jobs', [])):
            raise ValueError('A readback must stay within its independent fixture family')
        if 'calls' in job and ('name' in job or 'arguments' in job):
            raise ValueError('Ambiguous sequence/single-call fixture')
        original_calls = job.get('calls', [{'name': job.get('name'), 'arguments': job.get('arguments')}])
        if not isinstance(original_calls, list) or not 1 <= len(original_calls) <= sequences.MAX_STEPS:
            raise ValueError('A fixture requires 1..200 calls')
        for key in _capture_references(original_calls):
            if key not in captures or capture_families[key] != family:
                raise ValueError('Capture must originate in an earlier job of this fixture family')
        calls = host._substitute(original_calls, captures)
        if any(not isinstance(call, dict) or set(call) != {'name', 'arguments'}
               or not isinstance(call['name'], str) or not isinstance(call['arguments'], dict) for call in calls):
            raise ValueError('Each call requires exactly a string name and argument object')
        request = {'calls': calls} if 'calls' in job else calls[0]
        error = policy.check('sdk_sequence' if 'calls' in job else 'sdk_call', request, sdk_catalog=catalog['functions'])
        if error:
            raise ValueError('Background fixture blocked: ' + job['id'] + ': ' + str(error))
        matching = []
        for step, call in enumerate(calls):
            if not isinstance(call, dict) or set(call) != {'name', 'arguments'} or not isinstance(call['arguments'], dict):
                raise ValueError('Each call requires exactly name and arguments')
            name = call['name']
            if name not in index or set(call['arguments']) != set(index[name]['args']):
                raise ValueError('Fixture arguments disagree with independent SDK index: ' + job['id'])
            result = runtime.validate(name, {'arguments': call['arguments']}, catalog=catalog,
                                      invocation_context={'sequence': 'calls' in job},
                                      reference_validator=lambda value, parameter, index=step: sequences._reference_contract(
                                          value, parameter, index, calls, catalog['functions']))
            if result.get('error'):
                raise ValueError('Invalid fixture contract: ' + job['id'] + ': ' + str(result))
            context = catalog['functions'][name].get('context', {})
            role, scope_family = context.get('scope_role'), context.get('scope_family')
            if role == 'begin':
                matching.append(scope_family)
            elif role == 'member' and (not matching or matching[-1] != scope_family):
                raise ValueError('Scope member outside its construction scope')
            elif role == 'end':
                if not matching or matching.pop() != scope_family:
                    raise ValueError('Mismatched construction scope end')
        if matching:
            raise ValueError('Unclosed construction scope')
        responses = []
        for call in calls:
            entry = catalog['functions'][call['name']]
            response = {'status': 'ok', 'function': call['name'], 'result': _sample_result(entry)}
            if entry['returns']['kind'] == 'tuple':
                response['outputs'] = {item['name']: response['result'][i] for i, item in enumerate(entry['returns']['items'])}
            responses.append(response)
        sample = {'status': 'ok', 'results': responses, 'count': len(responses)} if 'calls' in job else responses[0]
        _validate_assertions(job, sample, nullable_handle_paths=_nullable_handle_paths(
            calls, catalog['functions'], sequence='calls' in job))
        if 'capture' in job:
            capture = job['capture']
            if not isinstance(capture, dict) or set(capture) != {'name', 'path'} or not isinstance(capture['name'], str) or not capture['name']:
                raise ValueError('Capture requires a nonempty name and a typed result path')
            key = capture['name']
            if key in captures:
                raise ValueError('Duplicate capture: ' + key)
            captures[key] = _path_value(sample, capture['path'])
            if captures[key] is None or capture['path'][0] not in {'result', 'results', 'outputs'}:
                raise ValueError('A capture must select a non-void SDK result')
            capture_families[key] = family
        seen[job['id']] = family
    return True


def build_plan(document_path, *, run_id=None, selected=None):
    available = providers()
    wanted = families() if selected is None else list(selected)
    if not wanted or len(set(wanted)) != len(wanted) or any(name not in families() for name in wanted):
        raise ValueError('Choose unique registered fixture families')
    host = available['design'][0].HOST
    plan = host.build_plan(document_path, run_id=run_id or uuid.uuid4().hex[:12],
                           include_contracts=False, include_native=False, include_document=False)
    jobs = []
    for qualified in wanted:
        prefix, family = qualified.split(':', 1)
        module, builder = available[prefix]
        for original in getattr(module, builder)(plan['run_id'], [family]):
            job = _namespace(copy.deepcopy(original), qualified)
            job['id'] = prefix + '/' + original['id']
            job['fixture_family'] = qualified
            job['verifies_jobs'] = [prefix + '/' + name for name in original.get('verifies_jobs', [])]
            if 'capture' in job:
                job['capture']['name'] = qualified + ':' + original['capture']['name']
            if family in getattr(module, 'CHARACTERIZATION_FAMILIES', ()):
                if job.get('coverage_kind') == 'semantic':
                    raise ValueError('Declared characterization family has contradictory semantic metadata')
                job['verification_dimension'] = 'characterization'
                job['coverage_kind'] = 'characterization'
            else:
                job['coverage_kind'] = coverage_kind(job)
            jobs.append(job)
    by_api, by_compatibility, by_conditional, by_characterization = {}, {}, {}, {}
    classifications = Counter()
    for job in jobs:
        execution_kinds = set()
        characterization = coverage_kind(job) == 'characterization'
        for name in host._functions(job):
            # These APIs attempt native execution and may disclose a guarded
            # compatibility repair in the returned response.
            # This is planning metadata only: do not override actual provenance.
            if name == 'UprString':
                if not characterization:
                    by_compatibility.setdefault(name, []).append(job['id'])
                execution_kinds.add('compatibility')
            elif name in CONDITIONAL_COMPATIBILITY_APIS:
                if not characterization:
                    by_conditional.setdefault(name, []).append(job['id'])
                execution_kinds.add('conditional_compatibility')
            else:
                if not characterization:
                    by_api.setdefault(name, []).append(job['id'])
                execution_kinds.add('native')
            if characterization:
                by_characterization.setdefault(name, []).append(job['id'])
        classification = next(iter(execution_kinds)) if len(execution_kinds) == 1 else 'mixed'
        job['planned_execution_kind'] = classification
        classifications['characterization' if characterization else classification] += 1
    for name, entry in plan['functions'].items():
        entry['native_case_ids'] = by_api.get(name, [])
        entry['compatibility_case_ids'] = by_compatibility.get(name, [])
        entry['conditional_compatibility_case_ids'] = by_conditional.get(name, [])
        entry['characterization_case_ids'] = by_characterization.get(name, [])
        if name in by_api:
            entry['flags'] = [flag for flag in entry['flags'] if flag != 'native_fixture_not_yet_designed']
    plan['jobs'] = jobs
    plan['fixture_source_sha256'] = fixture_source_hashes()
    plan['summary'].update(fixture_jobs_total=len(jobs), native_cases=classifications['native'],
                           compatibility_cases=classifications['compatibility'],
                           conditional_compatibility_cases=classifications['conditional_compatibility'],
                           mixed_execution_cases=classifications['mixed'],
                           characterization_cases=classifications['characterization'],
                           characterization_apis_with_planned_observations=len(by_characterization),
                           native_apis_with_designed_fixture=len(by_api),
                           compatibility_apis_with_designed_fixture=len(by_compatibility),
                           conditional_compatibility_apis_with_designed_fixture=len(by_conditional),
                           native_apis_without_fixture=len(plan['functions']) - len(by_api),
                           fixture_families=wanted, phases=dict(Counter(job.get('phase', 'unspecified') for job in jobs)),
                           assertion_count=sum(len(job['assertions']) for job in jobs))
    plan['limitations'].extend([
        'A designed fixture remains unverified until its recorded native assertions pass.',
        'Characterization jobs inspect response contracts or unresolved behavior; they provide no semantic native or compatibility API pass credit.',
        'UprString is local compatibility; HArea and guarded getter repairs may disclose conditional compatibility. Planned categories never replace actual response provenance.',
        'Readback coverage does not establish all meaningful input combinations or object lifecycles.',
        'Document guards and mutations are separate invocations; concurrent agents must not switch the active document.',
        'No dialogs, arbitrary scripts, forced quarantines, preferences or preexisting user resources are used.',
    ])
    validate_plan(plan)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='List independent families without a host connection')
    parser.add_argument('--document')
    parser.add_argument('--family', action='append')
    parser.add_argument('--run-id')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.list:
        print('\n'.join(families()))
        return 0
    if not args.document or not args.output:
        parser.error('--document and --output are required for an offline plan')
    plan = build_plan(args.document, run_id=args.run_id, selected=args.family)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(plan, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
    print(json.dumps(plan['summary'], indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
