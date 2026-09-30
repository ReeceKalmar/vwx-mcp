"""Offline command-contract regressions; no live geometry certification."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ast.parse((ROOT / 'vwx-plugin/commands.py').read_text(encoding='utf-8'))
INDEX = json.loads((ROOT / 'vwx-plugin/vs_index.json').read_text(encoding='utf-8'))


def command_namespace():
    """Load function bodies without importing a live vs module or running startup."""
    functions = [node for node in SOURCE.body if isinstance(node, ast.FunctionDef)]
    namespace = {}
    exec(compile(ast.Module(body=functions, type_ignores=[]), '<commands>', 'exec'), namespace)
    namespace.update(vs=SimpleNamespace(), _h=lambda value: value,
                     _oid=lambda value: value, _SAFE_DEBUG=False,
                     _with_layer_class=lambda params: None, _restore=lambda prev: None,
                     _newobj_result=lambda params, fallback=None: {'object_id': fallback})
    return namespace


def sdk_mock(name, result=None):
    """Reject calls violating the actual checked-in SDK signature."""
    args = INDEX[name]['args']
    function = 'def call(' + ', '.join(args) + '):\n    return result\n'
    scope = {'result': result}
    exec(function, scope)
    return Mock(side_effect=scope['call'])


class SDKCommandTests(unittest.TestCase):
    def setUp(self):
        self.ns = command_namespace()
        self.vs = self.ns['vs']

    def bind(self, name, result=None):
        call = sdk_mock(name, result)
        setattr(self.vs, name, call)
        return call

    def run_command(self, command_name, **params):
        return self.ns[command_name](params)

    def test_discovery_presence_never_executes_native_targets_or_mutates_catalog(self):
        functions = {'Abs': {'name': 'Abs'}, 'Missing': {'name': 'Missing'}, 'Opaque': {'name': 'Opaque'}}
        catalog = {'sdk_version': 3200, 'functions': functions}
        self.ns['_sdk_modules'] = lambda: (SimpleNamespace(load_catalog=lambda: catalog),)
        self.vs.Abs = Mock(side_effect=AssertionError('Inspection must never invoke native code'))
        self.vs.Opaque = 42
        plain = self.run_command('sdk_list', name='Abs')
        self.assertNotIn('host_callable', plain['function'])
        measured = self.run_command('sdk_list', include_presence=True, limit=2)
        self.assertEqual(measured['total'], 3)
        self.assertEqual([row['host_callable'] for row in measured['functions']], [True, False])
        self.assertIs(self.run_command('sdk_list', name='Opaque', include_presence=True)['function']['host_callable'], False)
        self.assertNotIn('host_callable', functions['Abs'])
        self.vs.Abs.assert_not_called()
        for value in (1, 'true', None, [], {}):
            self.assertEqual(self.run_command('sdk_list', include_presence=value)['code'], 'SDK_ARGUMENTS')

    def test_discovery_inspection_errors_remain_unknown_not_absent(self):
        class BrokenHost:
            def __getattr__(self, name):
                raise RuntimeError('attribute lookup failed')
        self.ns['vs'] = BrokenHost()
        self.ns['_sdk_modules'] = lambda: (SimpleNamespace(load_catalog=lambda: {
            'sdk_version': 3200, 'functions': {'Abs': {'name': 'Abs'}}}),)
        result = self.run_command('sdk_list', name='Abs', include_presence=True)['function']
        self.assertIsNone(result['host_callable'])
        self.assertEqual(result['host_inspection_error'], 'attribute lookup failed')

    def test_class_override_procedures_return_none_and_use_viewport_class_keys(self):
        self.bind('CreateVPClOvrd')
        self.bind('UpdateVP')
        for name in ('SetVPClOvrdFillFore', 'SetVPClOvrdFillBack',
                     'SetVPClOvrdPenFore', 'SetVPClOvrdPenBack',
                     'SetVPClOvrdFillOpty', 'SetVPClOvrdPenOpty',
                     'SetVPClOvrdFillStyle'):
            self.bind(name)
        result = self.run_command('add_vp_class_override', viewport_id='vp',
                                  class_name='Trees', fill_fore_rgb=[255, 0, 128],
                                  fill_back_rgb=[1, 2, 3], pen_fore_rgb=[3, 2, 1],
                                  pen_back_rgb=[4, 5, 6], fill_opacity=50,
                                  pen_opacity=70, fill_style=1)
        self.assertEqual(result['status'], 'ok')
        self.vs.SetVPClOvrdFillFore.assert_called_once_with('vp', 'Trees', 65535, 0, 32896)
        self.vs.SetVPClOvrdFillOpty.assert_called_once_with('vp', 'Trees', 50)

    def test_layer_override_resolves_name_and_procedure_does_not_return_handle(self):
        self.bind('GetLayerByName', 'layer-handle')
        self.bind('CreateVPLrOvrd')
        self.bind('SetVPLrOvrdFillFore')
        self.bind('SetVPLrOvrdPenFore')
        self.bind('SetVPLrOvrdOpty')
        self.bind('UpdateVP')
        result = self.run_command('add_vp_layer_override', viewport_id='vp',
                                  layer_name='Design', fill_fore_rgb=[255, 0, 0],
                                  pen_fore_rgb=[0, 255, 0], opacity=42)
        self.assertEqual(result['status'], 'ok')
        self.vs.CreateVPLrOvrd.assert_called_once_with('vp', 'layer-handle')
        self.vs.SetVPLrOvrdOpty.assert_called_once_with('vp', 'layer-handle', 42)

    def test_chain_joins_new_dimension_handles(self):
        self.bind('LinearDim')
        self.vs.LNewObj = Mock(side_effect=['old', 'dim-a', 'dim-a', 'dim-b'])
        self.bind('CreateChainDimension', 'chain')
        result = self.run_command('create_chain_dimension', points=[[0, 0], [5, 0], [10, 0]])
        self.assertEqual(result, {'status': 'ok', 'created': 2, 'object_id': 'chain'})
        self.vs.CreateChainDimension.assert_called_once_with('dim-a', 'dim-b')

    def test_circular_dimension_requires_box_and_passes_complete_signature(self):
        self.bind('CircularDim')
        self.assertIn('error', self.run_command('create_circular_dimension', mode='radius'))
        self.vs.CircularDim.assert_not_called()
        result = self.run_command('create_circular_dimension', cx=0, cy=0, x=10, y=0,
                                  box1=[-10, 10], box2=[10, -10], dim_type=7,
                                  offset=2, shoulder=3)
        self.assertNotIn('error', result)
        self.vs.CircularDim.assert_called_once_with((0.0, 0.0), (10.0, 0.0),
                                                   (-10.0, 10.0), (10.0, -10.0),
                                                   2.0, 7, 770, 0, 3.0)

    def test_chain_does_not_reuse_stale_last_object_when_creation_fails(self):
        self.bind('LinearDim')
        self.vs.LNewObj = Mock(return_value='old')
        self.bind('CreateChainDimension')
        result = self.run_command('create_chain_dimension', points=[[0, 0], [5, 0]])
        self.assertIn('error', result)
        self.vs.CreateChainDimension.assert_not_called()

    def test_nurbs_conversion_explicitly_preserves_or_consumes_input(self):
        call = self.bind('ConvertToNURBS', 'nurbs')
        self.assertEqual(self.run_command('convert_to_nurbs', object_id='source',
                                         keep_original=True)['object_id'], 'nurbs')
        call.assert_called_once_with('source', True)
        call.reset_mock()
        self.run_command('convert_to_nurbs', object_id='source')
        call.assert_called_once_with('source', False)

    def test_offset_and_polygon_boolean_pass_complete_sdk_options(self):
        self.bind('OffsetPoly', 'offset')
        self.bind('ClipPolygon', 'clip')
        self.bind('SubtractPolygon', 'subtract')
        self.bind('CombinePolygons', 'combine')
        self.assertEqual(self.run_command('offset_polygon', object_id='a', distance=5,
                                         conversion_res=2)['status'], 'ok')
        self.vs.OffsetPoly.assert_called_once_with('a', 5.0, 1, False, True, 2, 0.0)
        self.assertEqual(self.run_command('clip_polygon', clip_id='a', subject_id='b',
                                         fuzz=0.01)['object_id'], 'clip')
        self.vs.ClipPolygon.assert_called_once_with('a', 'b', 0.01)
        self.assertEqual(self.run_command('subtract_polygon', object_id_a='a',
                                         object_id_b='b')['object_id'], 'subtract')
        self.assertEqual(self.run_command('combine_polygons', object_ids=['a', 'b'],
                                         fuzz=0.1)['object_id'], 'combine')

    def test_hatch_has_origin_point_and_perimeter_uses_whole_object(self):
        self.bind('CreateStaticHatchFromObject', 'hatch')
        result = self.run_command('create_static_hatch_from_object', source_id='boundary',
                                  hatch_name='Stone', origin_x=5, origin_y=7, angle=15)
        self.assertEqual(result['object_id'], 'hatch')
        self.vs.CreateStaticHatchFromObject.assert_called_once_with('boundary', 'Stone',
                                                                  (5.0, 7.0), 15.0)
        self.bind('HPerim', 24.0)
        self.assertEqual(self.run_command('polygon_perimeter', object_id='poly'),
                         {'perimeter': 24.0})

    def test_material_metrics_use_material_name_as_second_argument(self):
        self.bind('GetObjMaterialHandle', 'material')
        self.bind('GetObjMaterialName', 'Stone')
        self.bind('GetMaterialArea', 12.0)
        self.bind('GetMaterialVolume', 30.0)
        self.bind('IsMaterialSimple', True)
        result = self.run_command('get_material_info', object_id='object')
        self.assertEqual(result['area'], 12.0)
        self.assertEqual(result['volume'], 30.0)
        self.vs.GetMaterialArea.assert_called_once_with('object', 'Stone')

    def test_dtm_rise_requires_send_type_and_reports_modified_input(self):
        self.bind('DTM6_IsDTM6Object', True)
        self.bind('DTM6_RiseToSurface', True)
        missing = self.run_command('rise_to_surface', object_id='object', site_model_id='dtm')
        self.assertIn('error', missing)
        self.vs.DTM6_RiseToSurface.assert_not_called()
        result = self.run_command('rise_to_surface', object_id='object', site_model_id='dtm',
                                  tin_type=1, send_type=2)
        self.assertEqual(result, {'status': 'ok', 'object_id': 'object'})
        self.vs.DTM6_RiseToSurface.assert_called_once_with('dtm', 'object', 1, 2)
        self.bind('MakeModifierClass')
        self.assertEqual(self.run_command('make_site_modifier_class', class_name='Site')['status'], 'ok')
        self.vs.MakeModifierClass.assert_called_once_with('Site')


if __name__ == '__main__':
    unittest.main()
