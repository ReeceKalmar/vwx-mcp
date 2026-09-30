"""Offline terrain query contracts; these do not certify native site models."""
import unittest
from unittest.mock import Mock

from test_sdk_commands import command_namespace


class TerrainElevationTests(unittest.TestCase):
    def setUp(self):
        self.ns = command_namespace()
        self.active_dtm = Mock(return_value='active-site-model')
        self.ns['_active_dtm'] = self.active_dtm
        self.ns['_h'] = Mock(return_value='selected-site-model')

        # Fixed samples distinguish coordinates, model, and all three surfaces.
        # Values are independent of the wrapper's forwarding implementation.
        samples = {
            ('active-site-model', 0, 17.25, -8.5): 120.0,
            ('active-site-model', 1, 17.25, -8.5): 123.75,
            ('active-site-model', 2, 17.25, -8.5): 121.5,
            ('selected-site-model', 1, -3.5, 42.25): 98.25,
        }

        def elevation(hDTMObject, TINType, x, y):
            # Match the pinned 2027 SDK contract, including its false result.
            self.assertIn(TINType, (0, 1, 2))
            value = samples.get((hDTMObject, TINType, x, y))
            return (False, -999.0) if value is None else (True, value)

        self.query = Mock(side_effect=elevation)
        self.ns['vs'].DTM6_GetZatXY = self.query
        self.ns['vs'].DTM6_IsDTM6Object = Mock(return_value=True)

    def test_active_model_queries_distinguish_surfaces_and_preserve_xy(self):
        for command in ('get_terrain_elevation', 'get_z_at_xy'):
            for tin_type, expected_z in ((0, 120.0), (1, 123.75), (2, 121.5), (None, 121.5)):
                with self.subTest(command=command, tin_type=tin_type):
                    params = {'x': 17.25, 'y': -8.5}
                    if tin_type is not None:
                        params['tin_type'] = tin_type
                    expected = ({'elevation': expected_z} if command == 'get_terrain_elevation'
                                else {'ok': True, 'z': expected_z})
                    self.assertEqual(self.ns[command](params), expected)

    def test_explicit_model_query_uses_selected_model_and_proposed_surface(self):
        response = self.ns['get_z_at_xy']({
            'site_model_id': 'selected-uuid', 'tin_type': 1, 'x': -3.5, 'y': 42.25,
        })
        self.assertEqual(response, {'ok': True, 'z': 98.25})
        self.ns['_h'].assert_called_once_with('selected-uuid')
        self.active_dtm.assert_not_called()

    def test_outside_model_result_never_exposes_an_elevation(self):
        point = {'x': 500.25, 'y': -700.5, 'tin_type': 1}
        self.assertEqual(self.ns['get_z_at_xy'](point), {'ok': False, 'z': None})
        response = self.ns['get_terrain_elevation'](point)
        self.assertIn('outside the site model', response['error'])
        self.assertNotIn('elevation', response)

    def test_missing_active_model_does_not_dispatch_query(self):
        self.active_dtm.return_value = None
        for command in ('get_terrain_elevation', 'get_z_at_xy'):
            with self.subTest(command=command):
                self.assertIn('error', self.ns[command]({'x': 17.25, 'y': -8.5}))
        self.query.assert_not_called()


if __name__ == '__main__':
    unittest.main()
