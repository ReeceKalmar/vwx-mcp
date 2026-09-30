"""Background policy rejects interaction before queuing any batch mutations."""
import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('background_policy_test', ROOT / 'mcp-server/background_policy.py')
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


class BackgroundPolicyTests(unittest.TestCase):
    def test_design_geometry_and_discovery_remain_available(self):
        cases = [('sdk_Rect', {'arguments': {'p1': [0,0], 'p2': [1,1]}}),
                 ('sdk_call', {'name': 'HExtrude'}), ('sdk_list', {'name': 'AlrtDialog'}),
                 ('draw_rectangle', {}), ('get_document_info', {}), ('save_document_as', {}),
                 ('sdk_SaveActiveDocument', {'arguments': {'filePath': 'test.vwx'}})]
        for command, params in cases:
            with self.subTest(command=command):
                self.assertIsNone(POLICY.check(command, params))

    def test_interactive_paths_cannot_be_enabled_by_force_or_alias(self):
        for name in ('AlrtDialog', 'GetPt', 'GetFileN', 'RunLayoutDialog',
                     'DoMenuTextByName', 'SetTool', 'PrintUsingPrintDialog'):
            for command, params in [('sdk_' + name, {'options': {'force': True}}),
                                    ('sdk_call', {'name': name, 'options': {'force': True}})]:
                with self.subTest(command=command, name=name):
                    result = POLICY.check(command, params)
                    self.assertEqual(result['code'], 'VWX_BACKGROUND_INTERACTION_REQUIRED')
                    self.assertFalse(result['dispatched'])

    def test_whole_sequence_and_nested_batch_are_checked_before_dispatch(self):
        sequence = {'calls': [{'name': 'Rect', 'arguments': {}}, {'name': 'GetFileN'}]}
        self.assertEqual(POLICY.check('sdk_sequence', sequence)['blocked_step'], 1)
        batch = {'calls': [{'command': 'draw_rectangle'},
                           {'command': 'sdk_sequence', 'params': sequence}]}
        self.assertEqual(POLICY.check('_batch', batch)['blocked_step'], 1)
        for name in ('execute_script', 'run_menu_command', 'export_pdf', 'marionette_recalc'):
            self.assertIsNotNone(POLICY.check('_batch', {'calls': [{'command': name}]}))

    def test_handwritten_menu_and_pio_aliases_cannot_bypass_background_policy(self):
        for name in ('save_document', 'create_space', 'create_pio'):
            with self.subTest(command=name):
                self.assertIsNotNone(POLICY.check(name, {'force': True, 'show_pref': True}))
                batch = {'calls': [{'command': 'draw_rectangle'},
                                   {'command': name, 'params': {'show_pref': True}}]}
                self.assertEqual(POLICY.check('_batch', batch)['blocked_step'], 1)

    def test_non_dialog_categories_still_reject_documented_dialog_entry_points(self):
        for name in ('AdditionalDefRecords', 'CreateTextureBitmapN', 'DBShowManageDBsDlg',
                     'EditGeorefWithUI', 'EditObjectSpecial', 'GetCatalogItem',
                     'IFC_ExportWithUI', 'LegacyShapefileExp', 'RunGridSettingsDlg',
                     'SM_Preferences', 'ShowWebDlg', 'TBB_OpenTBBSelDlg',
                     'CallToolWithMode', 'ImportImageFile', 'ImportImageFileN',
                     'ImportDXFDWGFile', 'ImportResourceToCurrentFile', 'QTSetMovieOptionsN'):
            for command, params in [('sdk_' + name, {'arguments': {}, 'options': {'force': True}}),
                                    ('sdk_call', {'name': name, 'arguments': {}})]:
                with self.subTest(command=command, name=name):
                    response = POLICY.check(command, params)
                    self.assertIsNotNone(response)
                    self.assertFalse(response['dispatched'])
            self.assertEqual(POLICY.check('sdk_sequence', {'calls': [
                {'name': 'Rect'}, {'name': name}]})['blocked_step'], 1)

    def test_quiet_save_and_unshown_layout_construction_remain_available(self):
        for name in ('SaveActiveDocument', 'CreateLayout', 'CreateTextureBitmap', 'GetScriptResource'):
            self.assertIsNone(POLICY.check('sdk_call', {'name': name, 'arguments': {}}))

    def test_unknown_or_malformed_sdk_operations_fail_closed(self):
        for command, params in [('sdk_NotAnApi', {}), ('sdk_call', {'name': []}),
                                ('_batch', {'calls': [{}]}), ('sdk_sequence', {'calls': 7})]:
            with self.subTest(command=command):
                self.assertIsNotNone(POLICY.check(command, params))

    def test_cmd_does_not_construct_connection_for_rejected_operation(self):
        tree = ast.parse((ROOT / 'mcp-server/vwx_mcp_server.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'cmd')
        connection = SimpleNamespace(send_command=Mock(return_value={'status': 'ok'}))
        connect = Mock(return_value=connection)
        namespace = {'json': json, 'VWX_BACKGROUND_MODE': True,
                     'check_background_operation': POLICY.check, 'get_vwx_connection': connect}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<cmd>', 'exec'), namespace)
        response = json.loads(namespace['cmd']('execute_script', {'code': 'vs.AlrtDialog("x")'}))
        self.assertFalse(response['dispatched'])
        connect.assert_not_called()
        self.assertEqual(json.loads(namespace['cmd']('draw_rectangle'))['status'], 'ok')
        self.assertEqual(connect.call_count, 1)
        namespace['VWX_BACKGROUND_MODE'] = False
        namespace['cmd']('execute_script', {'code': 'print(1)'})
        self.assertEqual(connect.call_count, 2)

    def test_pio_preference_dialog_must_be_explicitly_suppressed(self):
        self.assertIsNone(POLICY.check('create_pio', {'name': 'Door'}))
        self.assertIsNone(POLICY.check('create_pio', {'name': 'Door', 'show_pref': False}))
        for unsafe in (True, 1, 0, 'false', None):
            self.assertIsNotNone(POLICY.check('create_pio', {'name': 'Door', 'show_pref': unsafe}))
        self.assertIsNone(POLICY.check('sdk_CreateCustomObjectN', {'arguments': {'showPref': False}}))
        self.assertIsNone(POLICY.check('sdk_call', {'name': 'CreateCustomObjectN', 'arguments': {'showPref': False}}))
        for unsafe in (True, 0, 'false', None):
            self.assertIsNotNone(POLICY.check('sdk_CreateCustomObjectN', {'arguments': {'showPref': unsafe}}))

    def test_site_model_picker_requires_literal_false_even_in_owned_nested_jobs(self):
        for selector in (True, 0, 'false', None, {'$ref': 0}):
            with self.subTest(selector=selector):
                call = {'name': 'DTM6_GetDTMObject',
                        'arguments': {'hLayer': 'layer-uuid', 'bPickUpModel': selector}}
                for command, params in (
                        ('sdk_call', call),
                        ('sdk_DTM6_GetDTMObject', {'arguments': call['arguments']}),
                        ('project_execute', {'token': 'c' * 64, 'command': '_batch', 'params': {'calls': [
                            {'command': 'draw_rectangle'},
                            {'command': 'sdk_sequence', 'params': {'calls': [call]}}]}})):
                    result = POLICY.check(command, params)
                    self.assertEqual(result['code'], 'VWX_BACKGROUND_INTERACTION_REQUIRED')
                    self.assertFalse(result['dispatched'])
        allowed = {'name': 'DTM6_GetDTMObject',
                   'arguments': {'hLayer': 'layer-uuid', 'bPickUpModel': False}}
        self.assertIsNone(POLICY.check('project_execute', {
            'token': 'c' * 64, 'command': 'sdk_sequence', 'params': {'calls': [allowed]}}))

    def test_document_switch_is_blocked_for_names_handles_and_force(self):
        for params in ({}, {'name': 'Other.vwx'}, {'hwnd': 123456},
                       {'name': 'Other.vwx', 'force': True},
                       {'hwnd': 123456, 'options': {'force': True}},
                       {'name': 'Other.vwx', 'background': True}):
            with self.subTest(params=params):
                response = POLICY.check('switch_document', params)
                self.assertEqual(response['code'], 'VWX_BACKGROUND_INTERACTION_REQUIRED')
                self.assertEqual(response['command'], 'switch_document')
                self.assertFalse(response['dispatched'])
                self.assertIn('foreground', response['error'])
                self.assertIn('shared active document', response['error'])
                self.assertIn('do not isolate', response['alternative'])
        for command in ('list_documents', 'get_document_info', 'confirm_active_document'):
            self.assertIsNone(POLICY.check(command, {'expected': 'Current.vwx'}))

    def test_document_switch_blocks_entire_nested_batch_before_first_mutation(self):
        calls = [
            {'command': 'draw_rectangle', 'params': {'x': 0, 'y': 0}},
            {'command': '_batch', 'params': {'calls': [
                {'command': 'get_document_info'},
                {'command': 'switch_document', 'params': {'hwnd': 42, 'force': True}}]}},
            {'command': 'draw_circle'},
        ]
        response = POLICY.check('_batch', {'calls': calls})
        self.assertEqual(response['code'], 'VWX_BACKGROUND_INTERACTION_REQUIRED')
        self.assertEqual(response['command'], 'switch_document')
        self.assertEqual(response['blocked_step'], 1)
        self.assertFalse(response['dispatched'])

    def test_all_mcp_document_switch_routes_reject_before_connection_or_queue(self):
        tree = ast.parse((ROOT / 'mcp-server/vwx_mcp_server.py').read_text(encoding='utf-8'))
        names = {'cmd', 'switch_document', 'vwx', 'vwx_batch'}
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        for node in nodes:
            node.decorator_list = []
            node.returns = None
            for argument in node.args.args:
                argument.annotation = None
        connection = SimpleNamespace(send_command=Mock(return_value={'status': 'ok'}))
        connect = Mock(return_value=connection)
        namespace = {'json': json, 'VWX_BACKGROUND_MODE': True,
                     'check_background_operation': POLICY.check, 'get_vwx_connection': connect}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<document-switch-routes>', 'exec'), namespace)
        requests = [
            lambda: namespace['switch_document'](None, name='Other.vwx'),
            lambda: namespace['switch_document'](None, hwnd=42),
            lambda: namespace['vwx'](None, 'switch_document', {'name': 'Other.vwx', 'force': True}),
            lambda: namespace['vwx_batch'](None, [
                {'command': 'draw_rectangle'}, {'command': 'switch_document', 'params': {'hwnd': 42}}]),
        ]
        for request in requests:
            response = json.loads(request())
            self.assertEqual(response['code'], 'VWX_BACKGROUND_INTERACTION_REQUIRED')
            self.assertFalse(response['dispatched'])
        connect.assert_not_called()
        connection.send_command.assert_not_called()
        # Attended operation remains an explicit separate mode; the policy
        # does not remove this legacy workflow from that mode.
        namespace['VWX_BACKGROUND_MODE'] = False
        self.assertEqual(json.loads(namespace['switch_document'](None, name='Other.vwx'))['status'], 'ok')
        connect.assert_called_once()
        connection.send_command.assert_called_once_with('switch_document', {'name': 'Other.vwx'})


if __name__ == '__main__':
    unittest.main()
