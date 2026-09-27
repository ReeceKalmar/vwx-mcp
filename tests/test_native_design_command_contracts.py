"""Offline SDK 3200 regressions; these do not certify native landscape workflows."""
import unittest
from unittest.mock import Mock

from test_sdk_commands import command_namespace, sdk_mock


class DesignCommandContracts(unittest.TestCase):
    def setUp(self):
        self.ns = command_namespace()
        self.vs = self.ns['vs']

    def bind(self, name, value=None):
        fn = sdk_mock(name, value)
        setattr(self.vs, name, fn)
        return fn

    def terrain(self):
        self.bind('DTM6_IsDTM6Object', True)
        self.bind('DTM6_IsObjectReady', True)
        query = self.bind('DTM6_GetZatXY')

        def plane(hDTMObject, TINType, x, y):
            self.assertEqual(hDTMObject, 'terrain')
            self.assertIn(TINType, (0, 1, 2))
            # Independent asymmetric plane and proposed-surface offset.
            return True, 100 + .01 * x + .02 * y + 5 * TINType
        query.side_effect = plane
        return {'site_model_id': 'terrain', 'x': 3, 'y': 7, 'tin_type': 0}

    def test_both_terrain_wrappers_use_tin_before_coordinates(self):
        params = self.terrain()
        for command, key in (('get_z_at_xy', 'z'), ('get_terrain_elevation', 'elevation')):
            for tin, expected in ((0, 100.17), (1, 105.17), (2, 110.17)):
                with self.subTest(command=command, tin=tin):
                    result = self.ns[command]({**params, 'tin_type': tin})
                    self.assertAlmostEqual(result[key], expected)
                    self.vs.DTM6_GetZatXY.assert_called_with('terrain', tin, 3.0, 7.0)

    def test_terrain_input_validation_precedes_native_calls(self):
        params = self.terrain()
        invalid = [(key, value) for key in ('x', 'y')
                   for value in (True, None, '3', float('nan'), float('inf'), [], 10 ** 400)]
        invalid += [('tin_type', value) for value in (True, -1, 3, 1.0, '1', None)]
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                self.assertIn('error', self.ns['get_z_at_xy']({**params, key: value}))
        self.vs.DTM6_GetZatXY.assert_not_called()
        self.vs.DTM6_IsDTM6Object.assert_not_called()

    def test_wrong_model_and_unready_model_do_not_query(self):
        params = self.terrain()
        for name in ('DTM6_IsDTM6Object', 'DTM6_IsObjectReady'):
            for value in (False, None, 1, 'True'):
                with self.subTest(name=name, value=value):
                    self.bind('DTM6_IsDTM6Object', True)
                    self.bind('DTM6_IsObjectReady', True)
                    self.bind(name, value)
                    self.assertIn('error', self.ns['get_z_at_xy'](params))
        self.vs.DTM6_GetZatXY.assert_not_called()

    def test_missing_explicit_uuid_never_falls_back_to_another_model(self):
        params = self.terrain()
        self.ns['_h'] = lambda value: None
        self.bind('ActLayer')
        self.assertIn('error', self.ns['get_z_at_xy'](params))
        self.vs.ActLayer.assert_not_called()
        self.vs.DTM6_GetZatXY.assert_not_called()

    def test_outside_point_does_not_use_the_undefined_z_output(self):
        params = self.terrain()
        self.bind('DTM6_GetZatXY', (False, float('nan')))
        self.assertEqual(self.ns['get_z_at_xy'](params), {'ok': False, 'z': None})
        self.assertIn('error', self.ns['get_terrain_elevation'](params))

    def test_malformed_native_terrain_results_fail_closed(self):
        params = self.terrain()
        for raw in (None, 123, (True,), (1, 100), (True, False),
                    (True, float('nan')), (True, float('inf')), (True, '100')):
            with self.subTest(raw=raw):
                self.bind('DTM6_GetZatXY', raw)
                self.assertIn('error', self.ns['get_z_at_xy'](params))

    def discovery(self, objects):
        self.bind('ActLayer', 'layer')
        self.bind('GetLayerByName', 'layer')
        self.bind('GetTypeN', 31)
        self.bind('GetLayer').side_effect = lambda obj: objects[obj][0]
        self.bind('DTM6_IsDTM6Object').side_effect = lambda obj: objects[obj][1]
        self.bind('ForEachObject').side_effect = lambda callback, criteria: [
            callback(obj) for obj in objects]
        self.bind('DTM6_GetDTMObject').side_effect = AssertionError('Picker must never run')

    def test_discovery_uses_only_unique_model_on_requested_layer(self):
        self.discovery({'landscape': ('layer', False), 'foreign': ('other', True),
                        'terrain': ('layer', True)})
        self.assertEqual(self.ns['site_model_on_layer']({'layer': 'Design'}),
                         {'object_id': 'terrain'})
        self.vs.GetLayerByName.assert_called_once_with('Design')
        self.assertEqual(self.ns['_active_dtm'](), 'terrain')
        self.vs.DTM6_GetDTMObject.assert_not_called()

    def test_ambiguous_discovery_stops_without_picker_or_terrain_query(self):
        self.discovery({'a': ('layer', True), 'b': ('layer', True), 'c': ('layer', True)})
        self.bind('DTM6_GetZatXY')
        self.assertIn('Multiple site models', self.ns['site_model_on_layer']({})['error'])
        self.assertIn('Multiple site models', self.ns['get_z_at_xy']({})['error'])
        self.assertIsNone(self.ns['_active_dtm']())
        self.vs.DTM6_GetDTMObject.assert_not_called()
        self.vs.DTM6_GetZatXY.assert_not_called()

    def test_empty_layer_does_not_select_model_from_different_layer(self):
        self.discovery({'foreign': ('other', True), 'lookalike': ('layer', False)})
        self.assertEqual(self.ns['site_model_on_layer']({}), {'object_id': None})
        self.assertIn('error', self.ns['get_z_at_xy']({}))
        self.vs.DTM6_GetDTMObject.assert_not_called()

    def test_missing_or_invalid_layer_never_scans_or_prompts(self):
        for layer, kind in ((None, 0), ('dummy', 0), ('wall', 68)):
            self.discovery({})
            self.bind('GetLayerByName', layer)
            self.bind('GetTypeN', kind)
            self.assertIn('error', self.ns['site_model_on_layer']({'layer': 'Missing'}))
            self.vs.ForEachObject.assert_not_called()
            self.vs.DTM6_GetDTMObject.assert_not_called()

    def component(self, kind):
        resource_type = 19 if kind == 'material' else 97
        self.bind('GetTypeN').side_effect = lambda h: 68 if h == 'wall' else resource_type
        self.bind('GetNumberOfComponents', (True, 3))
        self.ns['_name_obj'] = Mock(return_value='resource-handle')
        self.bind('Name2Index', 42)
        self.bind('Index2Name', 'Finish')
        setter = 'SetComponent' + kind.title()
        getter = 'GetComponent' + kind.title()
        self.bind(setter, True)
        self.bind(getter, (True, 42))
        self.bind('ResetObject')
        return {'object_id': 'wall', 'index': 2, kind + '_name': 'Finish'}, setter, getter

    def test_component_setters_pass_integer_refs_and_verify_parameter_before_reset(self):
        for kind in ('material', 'texture'):
            params, setter, getter = self.component(kind)
            order = []
            getattr(self.vs, setter).side_effect = lambda h, i, r: order.append('write') or True
            getattr(self.vs, getter).side_effect = lambda h, i: order.append('read') or (True, 42)
            self.vs.ResetObject.side_effect = lambda h: order.append('reset')
            result = self.ns['set_component_' + kind](params)
            self.assertEqual(result, {'status': 'ok', 'resource_index': 42,
                                     'parameter_verified': True, 'geometry_verified': False})
            getattr(self.vs, setter).assert_called_once_with('wall', 2, 42)
            getattr(self.vs, getter).assert_called_once_with('wall', 2)
            self.assertEqual(order, ['write', 'read', 'reset'])

    def test_unsupported_pio_or_wrong_resource_type_is_rejected_before_write(self):
        for kind in ('material', 'texture'):
            for owner_type, resource_type in ((86, 19), (84, 97), (68, 0), (68, 16)):
                params, setter, getter = self.component(kind)
                self.vs.GetTypeN.side_effect = lambda h: owner_type if h == 'wall' else resource_type
                response = self.ns['set_component_' + kind](params)
                self.assertFalse(response['mutation_dispatched'])
                getattr(self.vs, setter).assert_not_called()

    def test_all_documented_current_owner_types_are_accepted_when_components_exist(self):
        for owner_type in (16, 68, 71, 83):
            params, setter, getter = self.component('texture')
            self.vs.GetTypeN.side_effect = lambda h: owner_type if h == 'wall' else 97
            self.assertEqual(self.ns['set_component_texture'](params)['status'], 'ok')

    def test_component_index_and_count_validation_precedes_mutation(self):
        for kind in ('material', 'texture'):
            for index in (True, 0, -1, 4, 32768, '2', 2.0, None):
                params, setter, getter = self.component(kind)
                response = self.ns['set_component_' + kind]({**params, 'index': index})
                self.assertFalse(response['mutation_dispatched'])
                getattr(self.vs, setter).assert_not_called()
            for raw in ((False, 3), (True, 1), (True, True), (1, 3), (True, 32768), None, 3):
                params, setter, getter = self.component(kind)
                self.bind('GetNumberOfComponents', raw)
                self.assertFalse(self.ns['set_component_' + kind](params)['mutation_dispatched'])
                getattr(self.vs, setter).assert_not_called()

    def test_missing_or_invalid_resource_never_reaches_component_setter(self):
        for kind in ('material', 'texture'):
            for resource in (None, ''):
                params, setter, getter = self.component(kind)
                self.ns['_name_obj'].return_value = resource
                self.assertFalse(self.ns['set_component_' + kind](params)['mutation_dispatched'])
                getattr(self.vs, setter).assert_not_called()
            for ref in (None, True, 0, -1, 42.0, '42', 2147483648):
                params, setter, getter = self.component(kind)
                self.bind('Name2Index', ref)
                self.assertFalse(self.ns['set_component_' + kind](params)['mutation_dispatched'])
                getattr(self.vs, setter).assert_not_called()
            params, setter, getter = self.component(kind)
            self.bind('Index2Name', 'Different resource')
            self.assertFalse(self.ns['set_component_' + kind](params)['mutation_dispatched'])
            getattr(self.vs, setter).assert_not_called()

    def test_failed_native_component_setters_never_report_success_or_retry(self):
        for kind in ('material', 'texture'):
            for result in (False, None, 1, 'True'):
                params, setter, getter = self.component(kind)
                self.bind(setter, result)
                response = self.ns['set_component_' + kind](params)
                self.assertIn('error', response)
                self.assertTrue(response['mutation_dispatched'])
                getattr(self.vs, setter).assert_called_once()
                getattr(self.vs, getter).assert_not_called()
                self.vs.ResetObject.assert_not_called()

    def test_noop_or_malformed_component_readbacks_remain_dispatched_failures(self):
        for kind in ('material', 'texture'):
            for actual in ((True, 21), (False, 42), (1, 42), (True, True),
                           (True, 42.0), None, (True,), 42):
                params, setter, getter = self.component(kind)
                self.bind(getter, actual)
                response = self.ns['set_component_' + kind](params)
                self.assertIn('error', response)
                self.assertTrue(response['mutation_dispatched'])
                getattr(self.vs, setter).assert_called_once()
                self.vs.ResetObject.assert_not_called()

    def test_native_exception_after_dispatch_remains_explicit(self):
        for failed_step in ('SetComponentTexture', 'GetComponentTexture', 'ResetObject'):
            params, setter, getter = self.component('texture')
            getattr(self.vs, failed_step).side_effect = RuntimeError('native error')
            result = self.ns['set_component_texture'](params)
            self.assertEqual(result, {'error': 'native error', 'mutation_dispatched': True})
            self.vs.SetComponentTexture.assert_called_once()

    def walls(self, levels=(103, 100, 107, 102), thickness=(True, .5)):
        self.ns['_collect'] = lambda criteria: ['wall']
        self.ns['_summary'] = lambda h: {'object_id': h}
        self.bind('GetWallHeight', levels)
        self.bind('GetWallThickness', thickness)
        self.bind('GetObjectVariableReal').side_effect = AssertionError('Wrong selector')
        return self.ns['get_walls']({})['walls'][0]

    def test_wall_readback_preserves_endpoint_levels_and_unpacks_thickness(self):
        wall = self.walls()
        self.assertEqual(wall['height_levels'], {'start_top': 103, 'start_bottom': 100,
                                                'end_top': 107, 'end_bottom': 102})
        self.assertEqual((wall['start_height'], wall['end_height']), (3, 5))
        self.assertIsNone(wall['height'])
        self.assertEqual(wall['thickness'], .5)
        self.vs.GetWallHeight.assert_called_once_with('wall')
        self.vs.GetWallThickness.assert_called_once_with('wall')
        self.vs.GetObjectVariableReal.assert_not_called()

    def test_constant_wall_height_accounts_for_nonzero_bottom_elevation(self):
        wall = self.walls(levels=(103, 100, 105, 102))
        self.assertEqual(wall['height'], 3)

    def test_bad_wall_levels_are_explicit_and_do_not_hide_valid_thickness(self):
        for raw in (None, (1, 2), (True, 0, 3, 0), (float('nan'), 0, 3, 0)):
            wall = self.walls(levels=raw)
            self.assertIsNone(wall['height'])
            self.assertIn('height_error', wall)
            self.assertEqual(wall['thickness'], .5)

    def test_failed_or_malformed_wall_thickness_is_not_a_numeric_measurement(self):
        for raw in (None, .5, (False, .5), (1, .5), (True, True), (True, -1),
                    (True, float('inf')), (True, '.5')):
            wall = self.walls(thickness=raw)
            self.assertIsNone(wall['thickness'])
            self.assertIn('thickness_error', wall)
            self.assertEqual(wall['end_height'], 5)


if __name__ == '__main__':
    unittest.main()
