#!/usr/bin/env python3
"""Generate exact named adapters and a typed catalog from the official SDK stub.

Usage: python tools/build_sdk_wrappers.py <SDKLib/Include/vs.py> [--check]
Generation never imports the SDK, starts Vectorworks, or claims live validation.
"""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import warnings

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = 'vwx-plugin/sdk_catalog.json'
GENERATED_PATH = 'vwx-plugin/sdk_generated.py'
SCALAR_TYPES = {'BOOLEAN', 'INTEGER', 'LONGINT', 'STRING', 'REAL', 'CHAR', 'HANDLE',
                'DYNARRAY[] of CHAR', 'POINT', 'POINT3D', 'VECTOR', 'COLOR',
                'PROCEDURE', 'ANY', 'ARRAY', 'TEXTSTYLE', 'CRITERIA'}

SCOPE_BEGIN = {
    'BeginColumn': 'group', 'BeginFloor': 'group', 'BeginRoof': 'group',
    'BeginContext': 'context', 'BeginFolder': 'folder', 'BeginFolderN': 'folder',
    'BeginGroup': 'group', 'BeginGroupN': 'group', 'BeginMesh': 'mesh',
    'BeginModeButtonsText': 'mode_buttons_text', 'BeginMultDashConvert': 'mult_dash_convert',
    'BeginMultipleDuplicate': 'multiple_duplicate', 'BeginMXtrd': 'mxtrd',
    'BeginPoly': 'poly', 'BeginPoly3D': 'poly3d', 'BeginSweep': 'sweep',
    'BeginSym': 'sym', 'BeginText': 'text', 'BeginVectorFillN': 'vector_fill',
    'BeginXtrd': 'xtrd',
}
SCOPE_END = {
    'EndContext': 'context', 'EndFolder': 'folder', 'EndGroup': 'group',
    'EndMesh': 'mesh', 'EndModeButtonsText': 'mode_buttons_text',
    'EndMultDashConvert': 'mult_dash_convert', 'EndMultipleDuplicate': 'multiple_duplicate',
    'EndMXtrd': 'mxtrd', 'EndPoly': 'poly', 'EndPoly3D': 'poly3d',
    'EndSweep': 'sweep', 'EndSym': 'sym', 'EndText': 'text',
    'EndVectorFill': 'vector_fill', 'EndXtrd': 'xtrd',
}
SCOPE_MEMBERS = {
    'AddPoint': ('poly', 'SDK description explicitly requires BeginPoly/EndPoly.'),
    'Add3DPt': ('poly3d', 'SDK description explicitly requires BeginPoly3D/EndPoly3D.'),
    'AddVectorFillLayer': ('vector_fill', 'SDK description explicitly requires BeginVectorFillN first.'),
    'CurveTo': ('poly', 'Conservative inference: SDK describes creation of a bezier vertex.'),
    'CurveThrough': ('poly', 'Conservative inference: SDK describes insertion of a cubic spline vertex.'),
    'ArcTo': ('poly', 'Conservative inference: SDK describes creation of an arc vertex.'),
}
TRANSIENT_HANDLES = {'CreateHLHandle', 'CreateOpenGLHandle', 'CreateRWHandle',
                     'GetHLLineStyle', 'SetHLLineStyle'}
VARIADIC_READS = {'Read', 'ReadBin', 'ReadLn', 'StdRead', 'StdReadLn'}
GENERAL_EVENT_CATEGORY_QUERIES = {'vsoParamName2Index'}
CALLBACK_CONTRACTS = {
    'ForEachMaterial': {'parameter': 'callback', 'mode': 'collect',
                        'signature': '(HANDLE) -> None', 'lifetime': 'synchronous',
                        'source': 'SDK ISDK.h ForEachMaterial: std::function<void(MCObjectHandle)>.'},
    'ForEachObjectInList': {'parameter': 'actionFunc', 'mode': 'collect',
                            'signature': '(HANDLE) -> BOOLEAN', 'lifetime': 'synchronous',
                            'source': 'SDK reference ForEachObjectInList BOOLEAN callback; false continues, true stops.'},
    'ImportResToCurFileN': {'parameter': 'callback', 'mode': 'conflict',
                           'actions': ['skip', 'replace'], 'signature': '(STRING) -> INTEGER',
                           'lifetime': 'synchronous',
                           'source': 'Vectorworks developer-scripting ImportResToCurFileN: 0 skips, 1 replaces; rename VAR-string ABI remains unsupported.'},
}
for _name in ('TrackObject', 'TrackObjectN'):
    CALLBACK_CONTRACTS[_name] = {'parameter': 'callback', 'mode': 'filter',
                                'signature': '(HANDLE) -> BOOLEAN', 'lifetime': 'synchronous',
                                'source': 'SDK stub documents one-handle predicate returning true to accept.'}
for _name in ('RunLayoutDialog', 'RunLayoutDialogN', 'RunNamedDialog', 'RunNamedDialogN'):
    CALLBACK_CONTRACTS[_name] = {'parameter': 'callback', 'mode': 'dialog',
                                'signature': '(LONGINT item, LONGINT data) -> LONGINT item',
                                'lifetime': 'synchronous',
                                'source': 'SDK reference dialog event loop; official Python RunLayoutDialog remarks require returning item.'}


def normalize_type(raw):
    value = re.sub(r'^in/out\s+', '', raw.strip(), flags=re.I)
    value = re.sub(r'\s*\(Coordinate\)', '', value, flags=re.I)
    value = re.sub(r'\s+', ' ', value).strip().upper()
    if value in ('DYNARRAY OF CHAR', 'DYNARRAY[] OF CHAR'):
        return 'DYNARRAY[] of CHAR'
    return value


def parse_pascal_signature(signature):
    """Preserve all Pascal argument types for Python output-name resolution."""
    prefix = re.match(r'^(FUNCTION|PROCEDURE)\s+(\w+)\s*', signature)
    if not prefix:
        return {}, None
    remainder = signature[prefix.end():].strip()
    params = ''
    if remainder.startswith('('):
        end = remainder.rfind(')')
        params, remainder = remainder[1:end], remainder[end + 1:]
    return_type = None
    if remainder.lstrip().startswith(':'):
        return_type = normalize_type(remainder.lstrip()[1:].rstrip(';').strip())
    descriptors = {}
    for group in params.split(';'):
        if ':' not in group:
            continue
        names, raw_type = group.rsplit(':', 1)
        is_var = bool(re.match(r'^\s*VAR\b', names, re.I))
        names = re.sub(r'^\s*VAR\s+', '', names, flags=re.I)
        for name in names.split(','):
            name = name.strip()
            descriptors[name.casefold()] = {'name': name, 'type': normalize_type(raw_type),
                                             'raw_type': raw_type.strip(), 'var': is_var}
    return descriptors, return_type


def output_descriptor(token, pascal):
    if token.casefold() in pascal:
        param = pascal[token.casefold()]
        return {'name': token, 'type': param['type'], 'source': 'vectorscript_parameter'}
    declared_type = normalize_type(token)
    if declared_type in SCALAR_TYPES:
        return {'name': 'result', 'type': declared_type, 'source': 'python_signature'}
    variadic_type = pascal.get((token + '1').casefold())
    if variadic_type and any(name == '...' for name in pascal):
        return {'name': token, 'type': variadic_type['type'],
                'source': 'vectorscript_variadic_parameter', 'variable_shape': True}
    components = [pascal.get((token + axis).casefold()) for axis in 'XYZ']
    if all(components[:2]) and all(item['type'] == 'REAL' for item in components if item):
        count = 3 if components[2] else 2
        return {'name': token, 'type': 'POINT3D' if count == 3 else 'POINT',
                'source': 'vectorscript_coordinate_group',
                'components': [item['name'] for item in components[:count]]}
    return {'name': token, 'type': 'UNKNOWN', 'source': 'unresolved_python_output'}


def parse_returns(node, python_signature, vector_signature):
    pascal, return_type = parse_pascal_signature(vector_signature)
    placeholder = next((n.value for n in node.body if isinstance(n, ast.Return)), None)
    raw_shape = None
    if placeholder is not None:
        try:
            raw_shape = ast.literal_eval(placeholder)
        except (ValueError, TypeError):
            raw_shape = {'expression': ast.unparse(placeholder)}
    if '=' not in python_signature:
        return {'kind': 'void', 'items': [], 'stub_placeholder': raw_shape}
    lhs = python_signature.split('=', 1)[0].strip()
    tokens = [part.strip() for part in lhs.strip('()').split(',')]
    items = [output_descriptor(token, pascal) for token in tokens]
    out = {'kind': 'tuple' if lhs.startswith('(') else 'scalar',
           'items': items, 'stub_placeholder': raw_shape,
           'vectorscript_return_type': return_type}
    if out['kind'] == 'scalar':
        out['type'] = items[0]['type']
    return out


def correct_known_return_contract(function):
    """Resolve one measured SDK declaration conflict; never infer tuple repairs."""
    if function['name'] != 'GetGradientDataN':
        return
    declared_python = ('(Boolean, spotPosition, midpointPosition, red, green, blue, opacity) '
                       '= vs.GetGradientDataN(gradient, segmentIndex)')
    declared_vector = ('PROCEDURE GetGradientDataN(gradient:HANDLE; segmentIndex:INTEGER; '
                       'VAR spotPosition:REAL; VAR midpointPosition:REAL; VAR red:LONGINT; '
                       'VAR green:LONGINT; VAR blue:LONGINT; VAR opacity:INTEGER);')
    output_names = ['spotPosition', 'midpointPosition', 'red', 'green', 'blue', 'opacity']
    output_types = ['REAL', 'REAL', 'LONGINT', 'LONGINT', 'LONGINT', 'INTEGER']
    expected_items = [{'name': 'result', 'type': 'BOOLEAN', 'source': 'python_signature'}] + [
        {'name': name, 'type': kind, 'source': 'vectorscript_parameter'}
        for name, kind in zip(output_names, output_types)]
    inputs = [(p['name'], p['type'], p['direction']) for p in function['parameters']]
    returns = function['returns']
    placeholder = returns.get('stub_placeholder')
    if (function['python_signature'] != declared_python
            or function['vector_script_signature'] != declared_vector
            or inputs != [('gradient', 'HANDLE', 'in'), ('segmentIndex', 'INTEGER', 'in')]
            or returns.get('kind') != 'tuple' or returns.get('items') != expected_items
            or returns.get('vectorscript_return_type') is not None
            or type(placeholder) is not tuple or len(placeholder) != 6
            or [type(value) for value in placeholder] != [float, float, int, int, int, int]
            or placeholder != (0.0, 0.0, 0, 0, 0, 0)):
        raise ValueError('GetGradientDataN SDK declaration changed; review the measured six-output correction')
    # Keep the unmodified SDK declaration in the audit note, but expose the
    # six native values verbatim. Adding a Boolean would invent success data.
    returns['items'] = expected_items[1:]
    function['python_signature'] = ('(spotPosition, midpointPosition, red, green, blue, opacity) '
                                    '= vs.GetGradientDataN(gradient, segmentIndex)')
    function['return_contract_correction'] = {
        'kind': 'measured_sdk_declaration_conflict',
        'sdk_python_signature': declared_python,
        'sdk_version': 3200, 'sdk_build': 882699,
        'observed_host': [32, 0, 0, 2, 882075],
        'reason': ('The Python docstring declares seven outputs including Boolean; the stub placeholder '
                   'and VectorScript PROCEDURE declare six data outputs. The C++ ISDK method returns bool, '
                   'but the observed Python binding returns only the six data values. No Boolean is fabricated.'),
        'native_evidence': 'docs/GRADIENT_RETURN_2027.json',
        'native_evidence_sha256': 'db267c5294d3bf552b498d73f0d502fa2628c21807943b0bcf8fbf2f0fbce319',
        'observed_result': [0.25, 0.4, 0, 0, 255, 71],
        'corroboration': 'GetGradientData returned the same first five values; GetGradientOpacity returned 71.',
        'verification_scope': 'One native return-shape observation; not comprehensive semantic verification.',
    }


def context_descriptor(function):
    """Expose execution constraints; never turn a generated signature into a live claim."""
    name = function['name']
    category = function['category']
    description = function['description']
    context = {
        'requires_sequence': name in SCOPE_BEGIN or name in SCOPE_END,
        'scope_role': 'begin' if name in SCOPE_BEGIN else 'end' if name in SCOPE_END else None,
        'scope_family': SCOPE_BEGIN.get(name, SCOPE_END.get(name)),
        'unsupported_reason': None,
        'quarantined': name in {'Layer', 'CombineIntoSurface'},
        'deprecated': bool(re.search(r'\b(?:obsolete|deprecated)\b', description, re.I)),
        'interactive': category in {'User Interactive', 'Dialogs - Predefined'}
                       or name.startswith(('RunLayoutDialog', 'EditCriteriaWithUI')),
        'required_host_context': None,
    }
    if name in SCOPE_MEMBERS:
        family, evidence = SCOPE_MEMBERS[name]
        context.update(requires_sequence=True, scope_role='member', scope_family=family,
                       scope_evidence=evidence)
    if (category in ('Object Events', 'Tool Events') and name not in GENERAL_EVENT_CATEGORY_QUERIES
            or name in {'BeginModeButtonsText', 'EndModeButtonsText'}):
        context['required_host_context'] = 'object_event' if category == 'Object Events' else 'tool_event'
        context['unsupported_reason'] = ('Requires a Vectorworks ' + context['required_host_context']
                                          + ' callback context, which a menu-command job cannot provide.')
    if name in TRANSIENT_HANDLES:
        context['unsupported_reason'] = ('This API uses a transient rendering-options HANDLE, '
                                          'not a document object addressable by UUID.')
    if name in VARIADIC_READS:
        context['unsupported_reason'] = ('The stub declares no Python inputs but a variadic typed '
                                          'ANY output; its runtime calling convention is not verified.')
    if name == 'GS_EdSh_ConstructLayout':
        context['unsupported_reason'] = ('The ANY arguments carry native shader pointers; '
                                          'JSON values cannot represent these pointers.')
    if name == 'SetControlData':
        context['required_host_context'] = 'dialog_event'
        context['context_evidence'] = 'SDK explicitly requires a dialog event handler; supported inside a declarative dialog callback.'
    if name == 'BeginRoof':
        context['scope_evidence'] = 'SDK VectorScript Reference.xml BeginRoof example closes with EndGroup.'
    if name in GENERAL_EVENT_CATEGORY_QUERIES:
        context['context_evidence'] = 'SDK documents an explicit format-name parameter lookup, independent of current object events.'
    if name == 'RunTempTool':
        context['unsupported_reason'] = ('SDK stub and official Python reference disagree on argument order '
                                          'and completion-callback ABI; temporary tool context is not verified.')
    if any(item['type'] == 'UNKNOWN' for item in function['returns']['items']):
        context['unsupported_reason'] = 'The SDK output type could not be resolved from its declarations.'
    return context


def parse_stub(source):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', SyntaxWarning)
        tree = ast.parse(source)
    lines = source.splitlines()
    functions = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.args.defaults or node.args.vararg or node.args.kwarg or node.args.kwonlyargs:
            raise ValueError('Unsupported new SDK signature form: ' + node.name)
        doc = ast.get_docstring(node) or ''
        doc_lines = [line.strip() for line in doc.splitlines()]
        python_signature = next((line[8:] for line in doc_lines if line.startswith('Python: ')), '')
        vector_signature = next((line[14:] for line in doc_lines if line.startswith('VectorScript: ')), '')
        category = next((line[9:] for line in doc_lines if line.startswith('Category:')), '').strip()
        description = '\n'.join(line for line in doc_lines
                                if line and not line.startswith(('Python:', 'VectorScript:', 'Category:')))
        parameters = []
        for arg in node.args.args:
            source_line = lines[arg.lineno - 1]
            comment = re.search(r'#\s*(.+?)\s+-\s*(.*)', source_line)
            if comment is None:
                raise ValueError('Missing SDK parameter type: ' + node.name + '.' + arg.arg)
            raw_type, summary = comment.groups()
            parameters.append({'name': arg.arg, 'type': normalize_type(raw_type),
                               'raw_type': raw_type.strip(),
                               'direction': 'inout' if raw_type.lower().startswith('in/out ') else 'in',
                               'required': True, 'has_default': False,
                               'nullable': None,
                               'description': summary.strip()})
            if node.name == 'BeginGroupN' and arg.arg == 'groupHandle':
                parameters[-1]['nullable'] = True
                parameters[-1]['nullability_source'] = 'SDK parameter description explicitly permits nil.'
        functions[node.name] = {
            'name': node.name, 'command': 'sdk_' + node.name,
            'parameters': parameters,
            'returns': parse_returns(node, python_signature, vector_signature),
            'python_signature': python_signature,
            'vector_script_signature': vector_signature,
            'category': category, 'description': description,
            'source_line': node.lineno,
            'required_count': len(parameters),
            'vectorscript_variadic': '...' in vector_signature,
        }
        correct_known_return_contract(functions[node.name])
        functions[node.name]['context'] = context_descriptor(functions[node.name])
        if node.name in CALLBACK_CONTRACTS:
            functions[node.name]['callback_contract'] = CALLBACK_CONTRACTS[node.name]
        if node.name == 'UprString':
            functions[node.name]['compatibility'] = {
                'implementation': 'python.str.upper', 'input_constraint': 'ASCII only',
                'native_execution': 'blocked', 'reason': 'native_uncertain_outcome',
                'evidence': 'SDK XML example converts vectorworks to VECTORWORKS; Unicode/locale equivalence is unverified.',
                'source': 'https://github.com/Vectorworks/developer-scripting/blob/main/Function%20Reference/Functions/UprString.md',
                'native_warning': 'Host exited after an UprString job was claimed on 2026-09-26. Causation is unproven; do not replay the native call.',
            }
    return functions


def build_catalog(stub_path, repo=ROOT):
    repo = Path(repo)
    stub_path = Path(stub_path)
    source_bytes = stub_path.read_bytes()
    functions = parse_stub(source_bytes.decode('utf-8-sig'))
    index_path = repo / 'vwx-plugin/vs_index.json'
    index_bytes = index_path.read_bytes()
    index = json.loads(index_bytes)
    metadata = json.loads((repo / 'vwx-plugin/vs_index_meta.json').read_text(encoding='utf-8'))
    if (any('return_contract_correction' in f for f in functions.values())
            and (metadata['vectorworks_year'], metadata['sdk_version'], metadata['sdk_build']) != (2027, 3200, 882699)):
        raise ValueError('SDK version changed; review measured return-contract corrections before regeneration')
    if set(index) != set(functions):
        raise ValueError('SDK function names disagree with vs_index.json')
    for name, function in functions.items():
        if [param['name'] for param in function['parameters']] != index[name]['args']:
            raise ValueError('SDK arguments disagree with vs_index.json: ' + name)
    stub_sha = hashlib.sha256(source_bytes).hexdigest()
    index_sha = hashlib.sha256(index_bytes).hexdigest()
    if stub_sha != metadata['stub_sha256'] or index_sha != metadata['index_sha256']:
        raise ValueError('SDK/index bytes disagree with vs_index_meta.json provenance')
    return {
        'schema_version': 1,
        'vectorworks_year': metadata['vectorworks_year'],
        'sdk_version': metadata['sdk_version'], 'sdk_build': metadata['sdk_build'],
        'function_count': len(functions),
        'verification': 'Generated SDK contracts only; no live Vectorworks verification.',
        'source': {'stub_sha256': stub_sha, 'index_sha256': index_sha,
                   'sdk_archive_sha256': metadata['sdk_archive_sha256'],
                   'url': metadata['source_url'],
                   'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        'functions': dict(sorted(functions.items())),
    }


def render_wrappers(catalog):
    catalog_sha = hashlib.sha256((json.dumps(catalog, ensure_ascii=False, indent=2) + '\n').encode('utf-8')).hexdigest()
    lines = [
        '# Generated by tools/build_sdk_wrappers.py; do not edit by hand.',
        '# Exact named Python SDK adapters. Generation is not live verification.',
        'import vs',
        'import sdk_runtime',
        '',
        'SDK_VERSION = ' + repr(catalog['sdk_version']),
        'SDK_BUILD = ' + repr(catalog['sdk_build']),
        'SDK_STUB_SHA256 = ' + repr(catalog['source']['stub_sha256']),
        'SDK_CATALOG_SHA256 = ' + repr(catalog_sha),
        '',
    ]
    for name, function in catalog['functions'].items():
        args = ', '.join(param['name'] for param in function['parameters'])
        lines.extend([
            '',
            'def sdk_' + name + '(p):',
            '    ' + repr(function['python_signature']),
            '    return sdk_runtime.invoke(' + repr(name) + ', p,',
            '                              lambda ' + args + ': vs.' + name + '(' + args + '))',
        ])
    lines.extend(['', '', 'WRAPPERS = {'])
    lines.extend('    ' + repr(name) + ': sdk_' + name + ',' for name in catalog['functions'])
    lines.append('}')
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sdk_stub', type=Path)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    catalog = build_catalog(args.sdk_stub, args.repo)
    outputs = {CATALOG_PATH: json.dumps(catalog, ensure_ascii=False, indent=2) + '\n',
               GENERATED_PATH: render_wrappers(catalog)}
    for relative, text in outputs.items():
        path = args.repo / relative
        if args.check:
            if not path.is_file() or path.read_text(encoding='utf-8') != text:
                raise SystemExit('Generated file is stale: ' + relative)
        else:
            path.write_text(text, encoding='utf-8', newline='\n')
    unresolved = [(name, item['name']) for name, function in catalog['functions'].items()
                  for item in function['returns']['items'] if item['type'] == 'UNKNOWN']
    print(json.dumps({'functions': len(catalog['functions']),
                      'argument_types': dict(Counter(p['type'] for f in catalog['functions'].values()
                                                      for p in f['parameters'])),
                      'unresolved_return_types': unresolved}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
