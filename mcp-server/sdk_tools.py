"""Register the generated SDK surface without importing Vectorworks' vs module.

Each SDK function has its own named tool and argument schema. The host adapter
performs strict validation again before dispatch; schemas alone are not a guard.
"""
import json
from pathlib import Path


def read_catalog():
    path = Path(__file__).resolve().parents[1] / 'vwx-plugin' / 'sdk_catalog.json'
    with path.open(encoding='utf-8') as file:
        catalog = json.load(file)
    return catalog


def argument_schema(spec):
    """JSON Schema for the transport representation, without type coercion."""
    properties = {}
    for parameter in spec['parameters']:
        kind = ' '.join(parameter['type'].upper().split())
        if kind in ('STRING', 'DYNARRAY[] OF CHAR', 'CRITERIA', 'CHAR'):
            value = {'type': 'string'}
            if kind == 'CHAR':
                value.update(minLength=1, maxLength=1)
        elif kind == 'BOOLEAN':
            value = {'type': 'boolean'}
        elif kind in ('INTEGER', 'LONGINT', 'TEXTSTYLE'):
            low, high = {'INTEGER': (-32768, 32767), 'LONGINT': (-2147483648, 2147483647),
                         'TEXTSTYLE': (0, 31)}[kind]
            value = {'type': 'integer', 'minimum': low, 'maximum': high}
        elif kind == 'REAL':
            value = {'type': 'number'}
        elif kind == 'HANDLE':
            value = {'type': 'string', 'format': 'uuid'}
            if spec['name'] == 'BeginGroupN' and parameter['name'] == 'groupHandle':
                value = {'anyOf': [value, {'type': 'null'}]}
        elif kind in ('POINT', 'POINT3D', 'VECTOR', 'COLOR'):
            size = 2 if kind == 'POINT' else 3
            item = {'type': 'number'} if kind != 'COLOR' else {'type': 'integer', 'minimum': 0, 'maximum': 65535}
            value = {'type': 'array', 'minItems': size, 'maxItems': size, 'items': item}
        elif kind == 'ARRAY':
            value = {'type': 'array'}
        elif kind == 'PROCEDURE':
            value = {'type': 'object', 'description': 'Declarative synchronous callback; see sdk_list and SDK_ADAPTERS_2027.md.'}
        else:
            value = {}
        value['description'] = parameter.get('description', '')
        properties[parameter['name']] = value
    return {'type': 'object', 'properties': properties, 'additionalProperties': False,
            'required': [p['name'] for p in spec['parameters'] if p.get('required', True)]}


def register_sdk_tools(mcp, send_command, timeout, tool_tags):
    from fastmcp.tools import Tool
    from mcp.types import ToolAnnotations
    catalog = read_catalog()
    functions = catalog['functions']
    for name, spec in sorted(functions.items()):
        tool_name = 'sdk_' + name

        def make_call(command):
            def call(arguments: dict, options: dict | None = None) -> str:
                return send_command(command, {'arguments': arguments, 'options': options or {}})
            return call

        call = make_call(tool_name)
        call.__name__ = tool_name
        description = ('Vectorworks 2027 SDK function ' + name + '. '
                       + spec.get('description', '')[:1200]
                       + '\nArguments use exact SDK names. Handles use object UUIDs. '
                       'Native context and semantic behavior require live verification. '
                       'Use sdk_list for the full contract and sdk_sequence for balanced scopes.')
        tool = Tool.from_function(
            call, name=tool_name, description=description, tags={'sdk'},
            output_schema=None, timeout=timeout,
            annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                        idempotentHint=False, openWorldHint=True),
            meta={'vectorworks_sdk': 3200, 'sdk_function': name,
                  'verification': 'generated adapter; host behavior requires live verification',
                  'sdk_context': spec.get('context', {})},
        )
        # The callable accepts a dict so values are never silently coerced by
        # Pydantic before the host runtime's strict SDK type checks.
        tool.parameters['properties']['arguments'] = argument_schema(spec)
        mcp.add_tool(tool)
        tool_tags[tool_name] = 'sdk'
    return len(functions)
