"""Repository contract discovery without importing vs or publishing native jobs."""
import ast
from functools import lru_cache
import json
from pathlib import Path
import re

PLUGIN = Path(__file__).resolve().parents[1] / 'vwx-plugin'


@lru_cache(maxsize=1)
def _sources():
    return (json.loads((PLUGIN / 'sdk_catalog.json').read_text(encoding='utf-8')),
            json.loads((PLUGIN / 'vs_index.json').read_text(encoding='utf-8')),
            ast.parse((PLUGIN / 'commands.py').read_text(encoding='utf-8')))


def discover(command, params):
    """Local source contracts, never a claim about the installed native host."""
    catalog, index, tree = _sources()
    if command == 'sdk_list':
        if params.get('include_presence', False) is not False:
            return {'error': 'Host presence requires an owned native job', 'code': 'SDK_ARGUMENTS'}
        name = params.get('name')
        functions = catalog['functions']
        if name:
            result = ({'sdk_version': catalog['sdk_version'], 'function': functions[name]}
                      if name in functions else {'error': 'Unknown SDK function: ' + str(name), 'code': 'SDK_UNKNOWN'})
        else:
            offset, limit = params.get('offset', 0), params.get('limit', 50)
            if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
                return {'error': 'offset must be >= 0 and limit must be 1..200', 'code': 'SDK_ARGUMENTS'}
            search, category = (params.get('search') or '').lower(), (params.get('category') or '').lower()
            names = [name for name, spec in sorted(functions.items())
                     if (not search or search in (name + ' ' + spec.get('description', '')).lower())
                     and (not category or category == spec.get('category', '').lower())]
            result = {'sdk_version': catalog['sdk_version'], 'total': len(names), 'offset': offset,
                      'functions': [functions[name] for name in names[offset:offset + limit]]}
    elif command == 'list_commands':
        filt = (params.get('filter') or '').lower()
        rows = [{'name': node.name, 'doc': (ast.get_docstring(node) or '').strip().split('\n')[0][:140]}
                for node in tree.body if isinstance(node, ast.FunctionDef)
                and not node.name.startswith('_') and (not filt or filt in node.name.lower())]
        sdk = []
        if params.get('include_sdk') or filt.startswith('sdk_'):
            sdk = [{'name': 'sdk_' + name, 'doc': spec.get('description', '')[:140]}
                   for name, spec in catalog['functions'].items() if not filt or filt in ('sdk_' + name).lower()]
        rows = sorted(rows + sdk, key=lambda row: row['name'])
        result = {'count': len(rows), 'commands': rows, 'sdk_adapters_included': len(sdk),
                  'sdk_discovery': 'sdk_list returns exact SDK contracts; include_sdk:true adds their command names here'}
    elif command == 'vs_signature':
        # Reuse the host's pure ranked signature lookup so search semantics do
        # not drift. Only this one function is compiled; commands.py is never
        # imported or initialized, and no vs object exists in this namespace.
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == command)
        namespace = {'_VS_INDEX': index, 're': re}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<local-signature-contract>', 'exec'), namespace)
        result = namespace[command](params)
    else:
        raise ValueError('Unknown local discovery route')
    return dict(result, discovery_source='local_repository', host_presence_checked=False)
