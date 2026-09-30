"""Named dispatch and real FastMCP registration, without starting host transport."""
import ast
import asyncio
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'vwx-plugin'
SERVER = ROOT / 'mcp-server'
CATALOG = json.loads((PLUGIN / 'sdk_catalog.json').read_text(encoding='utf-8'))
SDK_NAMES = set(CATALOG['functions'])
try:
    HAS_FASTMCP = importlib.util.find_spec('fastmcp') is not None
except (ValueError, ImportError):
    HAS_FASTMCP = False


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command_namespace():
    tree = ast.parse((PLUGIN / 'commands.py').read_text(encoding='utf-8'))
    names = {'_sdk_modules', '__getattr__', 'sdk_call', 'sdk_list', 'sdk_sequence', 'list_commands'}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {'__file__': str(PLUGIN / 'commands.py'), '__name__': 'sdk_commands_test',
                 'os': os, '_SDK_MODULES': None, '_SDK_STAMP': None}
    exec(compile(ast.Module(body=functions, type_ignores=[]), '<sdk_commands>', 'exec'), namespace)
    return namespace


class SDKCommandIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.modules = patch.dict(sys.modules)
        self.modules.start()
        self.addCleanup(self.modules.stop)
        for name in ('sdk_runtime', 'sdk_generated', 'sdk_sequences'):
            sys.modules.pop(name, None)
        self.path = patch.object(sys, 'path', [str(PLUGIN), *sys.path])
        self.path.start()
        self.addCleanup(self.path.stop)
        self.host = ModuleType('vs')
        self.host.GetVersion = Mock(return_value=(32, 0, 0, 2))
        self.host.Rect = Mock(return_value=None)
        sys.modules['vs'] = self.host
        self.commands = command_namespace()

    def test_dynamic_named_dispatch_and_sdk_call_use_same_exact_adapter(self):
        wrapper = self.commands['__getattr__']('sdk_Rect')
        envelope = {'arguments': {'p1': [0, 0], 'p2': [10, 20]}}
        first = wrapper(envelope)
        second = self.commands['sdk_call']({'name': 'Rect', **envelope})
        self.assertEqual(first['status'], 'ok')
        self.assertEqual(second['status'], 'ok')
        self.host.Rect.assert_called_with((0.0, 0.0), (10.0, 20.0))
        self.assertEqual(self.host.Rect.call_count, 2)
        with self.assertRaises(AttributeError):
            self.commands['__getattr__']('sdk_MissingApi')
        self.assertEqual(self.commands['sdk_call']({'name': 'MissingApi'})['code'], 'SDK_UNKNOWN')

    def test_exact_contract_discovery_and_generated_command_enumeration(self):
        detail = self.commands['sdk_list']({'name': 'Rect'})
        self.assertEqual(detail['function']['parameters'][0]['name'], 'p1')
        listing = self.commands['sdk_list']({'limit': 200})
        self.assertEqual(listing['total'], 3098)
        self.assertEqual(len(listing['functions']), 200)
        commands = self.commands['list_commands']({'include_sdk': True})
        self.assertEqual(commands['sdk_adapters_included'], 3098)
        self.assertTrue({'sdk_' + name for name in SDK_NAMES} <= {item['name'] for item in commands['commands']})
        self.assertIn('error', self.commands['sdk_list']({'offset': -1}))

    def test_foreign_cached_sdk_module_is_rejected_before_host_access(self):
        foreign = ModuleType('sdk_runtime')
        foreign.__file__ = str(ROOT / 'other-installation/sdk_runtime.py')
        sys.modules['sdk_runtime'] = foreign
        with self.assertRaisesRegex(RuntimeError, 'another installation'):
            self.commands['_sdk_modules']()
        self.host.GetVersion.assert_not_called()

    def test_catalog_digest_mismatch_is_rejected_before_native_dispatch(self):
        actual_open = open
        def altered_catalog(path, mode='r', *args, **kwargs):
            if str(path).endswith('sdk_catalog.json') and mode == 'rb':
                return io.BytesIO(b'not the catalog matching the generated wrappers')
            return actual_open(path, mode, *args, **kwargs)
        with patch('builtins.open', side_effect=altered_catalog):
            with self.assertRaisesRegex(RuntimeError, 'do not match'):
                self.commands['_sdk_modules']()
        self.host.GetVersion.assert_not_called()


@unittest.skipUnless(HAS_FASTMCP, 'Install mcp-server requirements for real FastMCP registration checks')
class SDKServerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patches = [patch.dict(sys.modules), patch.object(sys, 'path', [str(SERVER), *sys.path]),
                       patch.dict(os.environ, {'VWX_SDK_TOOLS': '1', 'VWX_VW_VERSION': '2027',
                                               'VWX_TRANSPORT': 'file', 'VWX_TOOLSET': 'full'})]
        for manager in cls.patches:
            manager.start()
        cls.addClassCleanup(lambda: [manager.stop() for manager in reversed(cls.patches)])
        for name in ('tool_tags', 'sdk_tools'):
            sys.modules.pop(name, None)
        cls.server = load_module('sdk_server_integration', SERVER / 'vwx_mcp_server.py')
        cls.tools = {tool.name: tool for tool in asyncio.run(cls.server.mcp.list_tools())}

    def test_all_3098_tools_are_registered_with_exact_wire_schemas_and_no_output_schema(self):
        self.assertEqual(self.server.SDK_TOOL_COUNT, 3098)
        for name, entry in CATALOG['functions'].items():
            with self.subTest(function=name):
                tool = self.tools['sdk_' + name]
                schema = tool.parameters['properties']['arguments']
                required = [p['name'] for p in entry['parameters']]
                self.assertEqual(schema['required'], required)
                self.assertEqual(set(schema['properties']), set(required))
                self.assertFalse(schema['additionalProperties'])
                self.assertIn('sdk', tool.tags)
                wire = tool.to_mcp_tool().model_dump(by_alias=True, exclude_none=True)
                self.assertNotIn('outputSchema', wire)
                self.assertFalse(wire['annotations']['readOnlyHint'])
        self.assertIn('confirm_active_document', self.tools)
        self.assertIn('sdk_sequence', self.tools)

    def test_registered_tool_preserves_named_arguments_in_file_transport_envelope(self):
        connection = SimpleNamespace(send_command=Mock(return_value={'status': 'ok'}))
        with patch.object(self.server, 'get_vwx_connection', return_value=connection):
            asyncio.run(self.tools['sdk_Rect'].run({'arguments': {'p1': [0, 0], 'p2': [3, 4]},
                                                    'options': {'force': False}}))
        connection.send_command.assert_called_once_with('sdk_Rect',
            {'arguments': {'p1': [0, 0], 'p2': [3, 4]}, 'options': {'force': False}})

    def test_sdk_preset_keeps_generated_surface_and_discovery(self):
        from tool_tags import preset_tags
        self.server.mcp.enable(tags=preset_tags('sdk'), only=True)
        try:
            visible = {tool.name for tool in asyncio.run(self.server.mcp.list_tools())}
            self.assertTrue({'sdk_' + name for name in SDK_NAMES} <= visible)
            self.assertTrue({'sdk_list', 'sdk_call', 'sdk_sequence', 'set_toolset'} <= visible)
            self.assertNotIn('create_roof', visible)
        finally:
            self.server.mcp.enable(tags=set(self.server.TOOL_TAGS.values()), only=True)

    def test_landscape_switch_keeps_design_workflows_and_full_restores_registered_tools(self):
        try:
            result = json.loads(self.server.set_toolset(None, 'landscape'))
            visible = {tool.name for tool in asyncio.run(self.server.mcp.list_tools())}
            self.assertEqual(result['tools'], len(visible))
            self.assertTrue({
                'confirm_active_document', 'get_document_units', 'create_layer',
                'create_class', 'draw_polyline', 'draw_extrude', 'create_wall',
                'create_roof', 'create_slab', 'create_pio', 'get_pio_parameters',
                'create_material', 'get_plants', 'get_z_at_xy', 'send_to_surface',
                'get_georeferencing', 'create_record_format', 'set_record_field',
                'create_report_worksheet', 'draw_dimension', 'draw_text',
                'create_viewport', 'screenshot', 'vwx', 'vwx_batch',
                'list_commands', 'sdk_list', 'sdk_call', 'sdk_sequence', 'set_toolset',
            } <= visible)
            self.assertFalse({'sdk_' + name for name in SDK_NAMES} & visible)
            self.assertNotIn('ifc_dm_dump', visible)
            self.assertNotIn('export_ifc', visible)
            for tool in asyncio.run(self.server.mcp.list_tools()):
                self.assertNotIn('outputSchema', tool.to_mcp_tool().model_dump(
                    by_alias=True, exclude_none=True))
            result = json.loads(self.server.set_toolset(None, 'full'))
            restored = {tool.name for tool in asyncio.run(self.server.mcp.list_tools())}
            self.assertEqual(restored, set(self.tools))
            self.assertEqual(result['tools'], len(restored))
        finally:
            self.server.mcp.enable(tags=set(self.server.TOOL_TAGS.values()), only=True)

    def test_modeling_preset_preserves_ifc_after_taxonomy_split(self):
        try:
            self.server.set_toolset(None, 'modeling')
            visible = {tool.name for tool in asyncio.run(self.server.mcp.list_tools())}
            self.assertTrue({'create_wall', 'create_material', 'get_ifc_entity',
                             'ifc_dm_dump', 'export_ifc'} <= visible)
        finally:
            self.server.mcp.enable(tags=set(self.server.TOOL_TAGS.values()), only=True)

    def test_default_startup_is_compact_and_switching_explains_omitted_sdk_tools(self):
        with patch.dict(sys.modules), patch.dict(os.environ):
            for name in ('VWX_TOOLSET', 'VWX_SDK_TOOLS'):
                os.environ.pop(name, None)
            sys.modules.pop('tool_tags', None)
            alternate = load_module('landscape_default_test', SERVER / 'vwx_mcp_server.py')
            # main applies startup visibility; replace all host/network startup.
            with patch.object(alternate, 'vw_versions'), patch.object(alternate, '_init_otel'), \
                    patch.object(alternate, '_install_middleware'), patch.object(alternate.mcp, 'run'):
                alternate.main()
            visible = {tool.name for tool in asyncio.run(alternate.mcp.list_tools())}
            self.assertEqual(alternate.SDK_TOOL_COUNT, 0)
            self.assertLess(len(visible), 300)
            self.assertTrue({'project_session', 'project_execute'} <= visible)
            self.assertTrue({'create_plant', 'draw_polyline', 'get_z_at_xy',
                             'create_viewport', 'sdk_list', 'sdk_call', 'sdk_sequence'} <= visible)
            self.assertNotIn('export_ifc', visible)
            for preset in ('sdk', 'full', 'landscape'):
                result = json.loads(alternate.set_toolset(None, preset))
                visible = {tool.name for tool in asyncio.run(alternate.mcp.list_tools())}
                self.assertEqual(result['tools'], len(visible))
                self.assertEqual(result['named_sdk_tools'], 0)
                self.assertTrue({'sdk_list', 'sdk_call', 'sdk_sequence', 'set_toolset'} <= visible)
                if preset in ('sdk', 'full'):
                    self.assertIn('VWX_SDK_TOOLS=1', result['note'])

    def test_explicit_full_or_sdk_startup_opts_in_to_named_tools(self):
        for preset in ('full', 'sdk'):
            with self.subTest(preset=preset), patch.dict(sys.modules), patch.dict(os.environ):
                os.environ.pop('VWX_SDK_TOOLS', None)
                os.environ['VWX_TOOLSET'] = preset
                sys.modules.pop('tool_tags', None)
                alternate = load_module('explicit_surface_test', SERVER / 'vwx_mcp_server.py')
                with patch.object(alternate, 'vw_versions'), patch.object(alternate, '_init_otel'), \
                        patch.object(alternate, '_install_middleware'), patch.object(alternate.mcp, 'run'):
                    alternate.main()
                visible = {tool.name for tool in asyncio.run(alternate.mcp.list_tools())}
                self.assertEqual(alternate.SDK_TOOL_COUNT, 3098)
                self.assertTrue({'sdk_' + name for name in SDK_NAMES} <= visible)
                self.assertTrue({'sdk_list', 'sdk_call', 'sdk_sequence', 'set_toolset'} <= visible)
                self.assertEqual('export_ifc' in visible, preset == 'full')

    def test_contract_discovery_never_connects_to_native_host(self):
        with patch.object(self.server, 'get_vwx_connection', side_effect=AssertionError('No host access')):
            contracts = json.loads(self.server.sdk_list(None, name='DTM6_GetZatXY'))
            declaration = json.loads(self.server.vs_signature(None, name='Rect'))
            commands = json.loads(self.server.list_commands(None, filter='plant'))
        self.assertEqual([row['name'] for row in contracts['function']['parameters']],
                         ['hDTMObject', 'TINType', 'x', 'y'])
        self.assertEqual(declaration['name'], 'Rect')
        self.assertIn('create_plant', {row['name'] for row in commands['commands']})
        for result in (contracts, declaration, commands):
            self.assertEqual(result['discovery_source'], 'local_repository')
            self.assertFalse(result['host_presence_checked'])

    def test_project_wrapper_preflights_nested_background_operations_before_connection(self):
        denied = [
            ('execute_script', {'code': 'mutation'}),
            ('_batch', {'calls': [{'command': 'draw_rectangle', 'params': {}},
                                 {'command': 'switch_document', 'params': {'name': 'other'}}]}),
            ('sdk_sequence', {'calls': [{'name': 'Rect', 'arguments': {'p1': [0, 0], 'p2': [1, 1]}},
                                       {'name': 'DoMenuTextByName', 'arguments': {}}]}),
            ('sdk_call', {'name': 'PythonExecute', 'arguments': {}, 'options': {'force': True}}),
        ]
        with patch.object(self.server, 'VWX_BACKGROUND_MODE', True), \
                patch.object(self.server, 'get_vwx_connection', side_effect=AssertionError('No queue access')):
            for command, params in denied:
                with self.subTest(command=command):
                    result = json.loads(self.server.project_execute(None, 'a' * 64, command, params))
                    self.assertEqual(result['code'], 'VWX_BACKGROUND_INTERACTION_REQUIRED')
                    self.assertIs(result['dispatched'], False)

    def test_optout_keeps_generic_sdk_routes_but_omits_3098_explicit_tools(self):
        with patch.dict(sys.modules), patch.dict(os.environ, {'VWX_SDK_TOOLS': '0'}):
            sys.modules.pop('tool_tags', None)
            alternate = load_module('sdk_optout_test', SERVER / 'vwx_mcp_server.py')
            visible = {tool.name for tool in asyncio.run(alternate.mcp.list_tools())}
            self.assertEqual(alternate.SDK_TOOL_COUNT, 0)
            self.assertFalse({'sdk_' + name for name in SDK_NAMES} & visible)
            self.assertTrue({'sdk_list', 'sdk_call', 'sdk_sequence'} <= visible)

    def test_server_main_guard_is_after_every_registration(self):
        tree = ast.parse((SERVER / 'vwx_mcp_server.py').read_text(encoding='utf-8'))
        guard = tree.body[-1]
        self.assertIsInstance(guard, ast.If)
        self.assertEqual(ast.unparse(guard.test), "__name__ == '__main__'")
        self.assertEqual(ast.unparse(guard.body[0]), 'main()')


if __name__ == '__main__':
    unittest.main()
