"""SDK-driven call and failure regressions; these do not execute Vectorworks."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_sdk_commands import command_namespace, sdk_mock


class CommandContractTests(unittest.TestCase):
    def setUp(self):
        self.ns = command_namespace()
        self.vs = self.ns['vs']

    def bind(self, name, value=None):
        fn = sdk_mock(name, value)
        setattr(self.vs, name, fn)
        return fn

    def test_invalid_uuid_type_zero_is_rejected_before_native_mutation(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'vwx-plugin/commands.py').read_text(encoding='utf-8'))
        fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('_h', '_oid')]
        exec(compile(ast.Module(body=fns, type_ignores=[]), '<handle helpers>', 'exec'), self.ns)
        self.bind('GetObjectByUuid', 'dummy')
        self.bind('GetTypeN', 0)
        self.bind('GetObjectUuid', 'wrong')
        self.assertIsNone(self.ns['_h']('missing'))
        self.assertIsNone(self.ns['_oid']('dummy'))
        self.vs.GetObjectUuid.assert_not_called()
        self.bind('IFC_SetIFCEntity', True)
        self.assertIn('error', self.ns['set_ifc_entity']({'object_id': 'missing'}))
        self.vs.IFC_SetIFCEntity.assert_not_called()

    def test_ifc_signature_and_false_result(self):
        fn = self.bind('IFC_SetIFCEntity', False)
        self.assertIn('error', self.ns['set_ifc_entity']({'object_id': 'obj', 'entity': 'IfcWall'}))
        fn.assert_called_once_with('obj', 'IfcWall')

    def test_object_metrics_uses_harean_coordinate_area_and_exact_signature(self):
        area = self.bind('HAreaN', 600.0)
        perimeter = self.bind('HPerim', 100.0)
        self.vs.HArea = Mock(side_effect=AssertionError('HArea returned None on VW2027'))
        self.vs.ObjArea = Mock(return_value=600.0 / 144.0)
        result = self.ns['get_object_metrics']({'object_id': 'rectangle'})
        self.assertEqual(result, {'status': 'ok', 'area': 600.0, 'perimeter': 100.0})
        area.assert_called_once_with('rectangle')
        perimeter.assert_called_once_with('rectangle')
        self.vs.HArea.assert_not_called()
        self.vs.ObjArea.assert_not_called()

    def test_save_signature_and_failure_code(self):
        fn = self.bind('SaveActiveDocument', -1)
        self.assertIn('error', self.ns['save_document_as']({'path': 'test.vwx'}))
        fn.assert_called_once_with('test.vwx')
        fn = self.bind('SaveActiveDocument', 0)
        self.assertEqual(self.ns['save_document_as']({'path': 'test.vwx'})['status'], 'ok')

    def test_guarded_existing_document_save_checks_before_mutation(self):
        path = r'C:\Tests\garden.vwx'
        self.bind('GetFPathName', path)
        saved = self.bind('SaveActiveDocument', 0)
        result = self.ns['save_document_as']({'path': path, 'expected_current_path': path.upper()})
        self.assertEqual(result['status'], 'ok')
        saved.assert_called_once_with(path)
        for actual, expected, destination in ((r'C:\Tests\other.vwx', path, path),
                                             (path, path, r'C:\Tests\other.vwx'),
                                             (path, '', path), (None, path, path), (path, True, path)):
            with self.subTest(actual=actual, expected=expected, destination=destination):
                self.bind('GetFPathName', actual)
                saved = self.bind('SaveActiveDocument', 0)
                response = self.ns['save_document_as']({'path': destination, 'expected_current_path': expected})
                self.assertEqual(response['code'], 'VWX_SAVE_DOCUMENT_GUARD')
                saved.assert_not_called()

    def test_save_false_or_zero_float_is_not_native_success(self):
        for raw in (False, True, 0.0, None, '0'):
            self.bind('SaveActiveDocument', raw)
            self.assertIn('error', self.ns['save_document_as']({'path': 'test.vwx'}))

    def test_solid_booleans_unpack_native_status_before_resolving_the_handle(self):
        names = {'add': 'AddSolid', 'subtract': 'SubtractSolid', 'intersect': 'IntersectSolid'}
        for operation, name in names.items():
            for api in names.values():
                self.bind(api, (0, 'new-solid'))
            self.ns['_oid'] = Mock(side_effect=lambda h: 'uuid-result' if h == 'new-solid' else None)
            response = self.ns['boolean_operation']({'operation': operation, 'object_id_a': 'a', 'object_id_b': 'b'})
            self.assertEqual(response, {'status': 'ok', 'object_id': 'uuid-result'})
            getattr(self.vs, name).assert_called_once_with('a', 'b')
            self.ns['_oid'].assert_called_once_with('new-solid')

    def test_solid_boolean_failed_or_malformed_native_results_never_become_success(self):
        for api in ('AddSolid', 'SubtractSolid', 'IntersectSolid'):
            self.bind(api)
        for raw in ((1, 'unused'), (-1, None), (False, 'unused'), (0,), (0, None), None, 'native-handle', (0, 'bad-handle')):
            with self.subTest(raw=raw):
                self.vs.AddSolid.return_value = raw
                self.ns['_oid'] = Mock(return_value=None)
                response = self.ns['boolean_operation']({'operation': 'add', 'object_id_a': 'a', 'object_id_b': 'b'})
                self.assertIn('error', response)
                self.assertNotIn('status', response)
                if raw != (0, 'bad-handle'):
                    self.ns['_oid'].assert_not_called()

    def test_texture_uses_numeric_resource_reference(self):
        self.ns['_name_obj'] = lambda name: 'texture-handle'
        self.bind('GetTypeN', 97)
        self.bind('Name2Index', 42)
        fn = self.bind('SetTextureRefN')
        self.assertEqual(self.ns['apply_texture']({'object_id': 'object', 'texture_name': 'Grass'})['status'], 'ok')
        fn.assert_called_once_with('object', 42, 0, 0)

    def test_viewport_parent_and_options_are_separate_sdk_calls(self):
        self.bind('GetLayerByName').side_effect = lambda name: {'Sheet': 'sheet', 'Design': 'design'}.get(name)
        self.bind('GetTypeN', 31)
        self.bind('GetObjectVariableInt').side_effect = lambda h, selector: 2 if h == 'sheet' else 1
        self.bind('CreateVP', 'viewport')
        self.bind('SetObjectVariableReal')
        self.bind('HMove')
        self.bind('SetVPLayerVisibility', True)
        result = self.ns['create_viewport']({'sheet_layer': 'Sheet', 'x': 20, 'y': 30,
                                           'scale': 50, 'design_layers': ['Design']})
        self.assertEqual(result['object_id'], 'viewport')
        self.vs.CreateVP.assert_called_once_with('sheet')
        self.vs.SetObjectVariableReal.assert_called_once_with('viewport', 1003, 50.0)
        self.vs.HMove.assert_called_once_with('viewport', 20.0, 30.0)
        self.vs.SetVPLayerVisibility.assert_called_once_with('viewport', 'design', 0)
        self.vs.CreateVP.reset_mock()
        self.assertIn('error', self.ns['create_viewport']({'sheet_layer': 'Sheet', 'design_layers': ['Missing']}))
        self.vs.CreateVP.assert_not_called()

    def test_symbol_origin_offsets_copies_without_moving_originals(self):
        self.bind('BeginSym')
        self.bind('EndSym')
        self.bind('HDuplicate', 'copy')
        result = self.ns['create_symbol_from_objects']({'object_ids': ['original'], 'name': 'Symbol',
                                                       'origin_x': 10, 'origin_y': 25})
        self.assertEqual(result['status'], 'ok')
        self.vs.HDuplicate.assert_called_once_with('original', -10.0, -25.0)
        self.vs.EndSym.assert_called_once_with()

    def test_marker_preserves_dimensions_and_uses_all_sdk_parameters(self):
        self.bind('GetObjBeginningMarker', (True, 5, 30, .1, .05, 0, .01, True))
        self.bind('GetObjEndMarker', (True, 5, 45, .2, .1, 1, .02, True))
        self.bind('SetObjBeginningMarker', True)
        self.bind('SetObjEndMarker', True)
        result = self.ns['set_marker']({'object_id': 'line', 'start_marker': 'arrow', 'end_marker': 'none'})
        self.assertEqual(result['status'], 'ok')
        self.vs.SetObjBeginningMarker.assert_called_once_with('line', 1, 30, .1, .05, 0, .01, True)
        self.vs.SetObjEndMarker.assert_called_once_with('line', 0, 45, .2, .1, 1, .02, False)

    def test_unsupported_parameters_fail_before_any_vs_call(self):
        for command, params in [('create_plant', {'height': 5}),
                                ('set_georeferencing', {'crs': 'EPSG:25832', 'origin_x': 0}),
                                ('export_image', {'path': 'x.png', 'width': 200})]:
            with self.subTest(command=command):
                self.assertIn('error', self.ns[command](params))

    def test_plant_insertion_does_not_report_a_stale_last_object(self):
        self.ns['_name_obj'] = lambda name: 'definition'
        self.bind('GetTypeN', 16)
        self.bind('LNewObj', 'prior-object')
        self.bind('Symbol')
        result = self.ns['create_plant']({'botanical_name': 'Tree'})
        self.assertIn('error', result)
        self.assertNotIn('object_id', result)

    def test_all_direct_sdk_calls_match_indexed_names_and_arities(self):
        import importlib.util
        import json
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('arity_audit', root / 'tools/pruefe_vs_aufrufe.py')
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        index = json.loads((root / 'vwx-plugin/vs_index.json').read_text(encoding='utf-8'))
        for relative in ('vwx-plugin/commands.py', 'vwx-plugin/BridgeStart_MenuCommand.py'):
            with self.subTest(file=relative):
                findings, count = audit.pruefe((root / relative).read_text(encoding='utf-8'), relative, index)
                self.assertGreater(count, 0)
                self.assertEqual(findings, [])

    def test_georeferencing_delegates_to_existing_sdk_gis_commands(self):
        self.ns['get_georeference_info'] = Mock(return_value={'origin_lat': 40.0, 'origin_lon': -111.0})
        self.ns['get_projection'] = Mock(return_value={'wkt': 'test-wkt'})
        self.bind('ActLayer', 'layer')
        self.bind('GetObjectVariableBoolean', True)
        result = self.ns['get_georeferencing']({})
        self.assertEqual(result['projection_details']['wkt'], 'test-wkt')
        self.assertTrue(result['active_layer_georef'])

    def test_dwg_import_uses_file_function_and_returns_host_code(self):
        self.bind('ImportDXFDWGFile', 7)
        self.bind('ActLayer', 'layer')
        self.bind('GetLName', 'Layer')
        result = self.ns['import_dwg']({'path': 'test.dwg'})
        self.vs.ImportDXFDWGFile.assert_called_once_with('test.dwg', False)
        self.assertEqual(result['code'], 7)
        self.assertNotEqual(result['status'], 'ok')


if __name__ == '__main__':
    unittest.main()
