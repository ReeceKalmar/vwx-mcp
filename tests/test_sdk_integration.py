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
