"""Landscape host contracts with independent fake objects; no native certification."""
import ast
import unittest
from unittest.mock import Mock

from test_sdk_commands import SOURCE, command_namespace


class LandscapeHostTests(unittest.TestCase):
    def setUp(self):
        self.ns = command_namespace()
        self.vs = self.ns['vs']
        self.types = {'plant': 86, 'hardscape': 86, 'wall': 68, 'symbol': 15,
                      'site': 86, 'stake': 86, 'layer': 31, 'planter': 86}
        self.plugins = {'plant': 'Plant', 'hardscape': 'Hardscape', 'site': 'Site Model',
                        'stake': 'Stake Object', 'planter': 'Planter'}
        self.fields = {'plant': {'Botanical Name': 'Acer', 'Height': '12'},
                       'hardscape': {'Thickness': '6', 'Finish': 'Stone'},
                       'site': {}, 'stake': {}, 'planter': {}}
        self.schemas = {self.plugins[h]: list(fields) for h, fields in self.fields.items()}
        self.ns['_h'] = lambda h: h if h in self.types else None
        self.ns['_oid'] = lambda h: h if h in self.types else None
        self.ns['_summary'] = lambda h: {'object_id': h, 'type': self.types[h]}
        self.ns['_bbox'] = lambda h: {'x1': 7, 'y1': 19, 'x2': 24, 'y2': -3}
        self.vs.GetTypeN = Mock(side_effect=lambda h: self.types.get(h, 0))
        self.vs.GetParametricRecord = Mock(side_effect=lambda h: self.plugins.get(h))
        self.vs.GetName = Mock(side_effect=lambda h: h)
        self.vs.NumFields = Mock(side_effect=lambda rec: len(self.schemas[rec]))
        self.vs.GetFldName = Mock(side_effect=lambda rec, index: self.schemas[rec][index - 1])
        self.vs.GetRField = Mock(side_effect=lambda h, rec, field: self.fields[h][field])
        self.vs.SetRField = Mock(side_effect=lambda h, rec, field, value: self.fields[h].__setitem__(field, value))
        self.vs.ResetObject = Mock()
        self.vs.GetUnits = Mock(return_value=(False, 2, 0, 12, 'ft', 'sq ft'))
        self.vs.GetPluginStyle = Mock(return_value='Local style')
        self.vs.Get3DCntr = Mock(return_value=((7, 19), 83))
        self.vs.Get3DInfo = Mock(return_value=(4, 17, 22))
        self.vs.GetCustomObjectPath = Mock(return_value=None)
        self.vs.DTM6_IsDTM6Object = Mock(side_effect=lambda h: h == 'site')
        self.vs.GetObjectVariableInt = Mock(return_value=1)
        self.vs.GetLayer = Mock(return_value='layer')
        self.ns['_active_dtm'] = Mock(return_value='site')
        self.vs.DTM6_GetZatXY = Mock(return_value=(True, 83.25))
        self.vs.DTM6_SendToSurface = Mock(return_value=True)
        self.vs.DTM6_RiseToSurface = Mock(return_value=True)
        self.vs.DTM6_ClearModelCache = Mock()

    def run_command(self, name, **params):
        return self.ns[name](params)

    def test_object_summary_type_names_follow_sdk_3200(self):
        node = next(n for n in SOURCE.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'OBJ_TYPES' for t in n.targets))
        names = ast.literal_eval(node.value)
        for kind, name in ((5, 'polygon'), (10, 'text'), (11, 'group'), (15, 'symbol'),
                           (21, 'polyline'), (24, 'extrude'), (68, 'wall'),
                           (86, 'plugin_obj'), (18, 'worksheet'), (122, 'viewport')):
            self.assertEqual(names[kind], name)

    def test_plant_limit_is_applied_after_native_identity_filter(self):
        self.types['plant2'] = 86
        self.plugins['plant2'] = 'Plant'
        self.fields['plant2'] = {'Botanical Name': 'Quercus', 'Height': '15'}
        self.vs.ForEachObject = Mock(side_effect=lambda cb, criteria:
                                    [cb(h) for h in ['wall', 'symbol', 'planter', 'plant', 'plant2']])
        result = self.run_command('get_plants', limit=1, layer="Owner's Garden")
        self.assertEqual([p['object_id'] for p in result['plants']], ['plant'])
        self.assertTrue(result['truncated'])
        self.assertIn("PON='Plant'", self.vs.ForEachObject.call_args.args[1])
        self.assertIn("Owner''s Garden", self.vs.ForEachObject.call_args.args[1])

    def test_plant_invalid_limit_is_rejected_before_enumeration(self):
        self.vs.ForEachObject = Mock()
        for limit in (True, 0, -1, 1.5, 5001, '10'):
            self.assertIn('error', self.run_command('get_plants', limit=limit))
        self.vs.ForEachObject.assert_not_called()

    def test_plant_aliases_resolve_only_discovered_fields(self):
        result = self.run_command('update_plant', object_id='plant', botanical_name='Acer rubrum')
        self.assertEqual(result['updated'], 1)
        self.assertEqual(self.fields['plant']['Botanical Name'], 'Acer rubrum')
        self.assertTrue(result['regeneration_required'])
        self.assertFalse(result['geometry_verified'])
        self.vs.ResetObject.assert_not_called()
        self.fields['plant'] = {'Botanischer Name': 'Acer', 'Höhe': '12'}
        self.schemas['Plant'] = list(self.fields['plant'])
        result = self.run_command('update_plant', object_id='plant', botanical_name='Quercus', height=15)
        self.assertEqual(result['updated'], 2)
        self.assertEqual(self.fields['plant'], {'Botanischer Name': 'Quercus', 'Höhe': '15'})

    def test_plant_missing_ambiguous_wrong_type_and_unknown_fields_never_write(self):
        for params in ({'object_id': 'wall', 'height': 20},
                       {'object_id': 'hardscape', 'height': 20},
                       {'object_id': 'plant', 'spread': 20},
                       {'object_id': 'plant', 'height': 20, 'extra_fields': {'Missing': 1}}):
            with self.subTest(params=params):
                self.assertIn('error', self.run_command('update_plant', **params))
        self.fields['plant']['Botanischer Name'] = 'Conflicting field'
        self.schemas['Plant'].append('Botanischer Name')
        self.assertIn('error', self.run_command('update_plant', object_id='plant', botanical_name='New'))
        self.vs.SetRField.assert_not_called()

    def test_plant_no_effect_write_is_partial_and_stops_before_next_field(self):
        self.vs.SetRField.side_effect = None
        result = self.run_command('update_plant', object_id='plant', botanical_name='New', height=20)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['updated'], 0)
        self.assertEqual(result['results'][0]['actual'], 'Acer')
        self.vs.SetRField.assert_called_once()

    def test_batch_preflights_all_plants_and_reports_partial_native_failure(self):
        bad = [{'object_id': 'plant', 'field_name': 'Height', 'value': 15},
               {'object_id': 'hardscape', 'field_name': 'Thickness', 'value': 8}]
        self.assertFalse(self.run_command('batch_update_plants', updates=bad)['dispatched'])
        self.vs.SetRField.assert_not_called()
        writes = [{'object_id': 'plant', 'field_name': 'Height', 'value': 15},
                  {'object_id': 'plant', 'field_name': 'Botanical Name', 'value': 'New'}]
        def fail_second(h, rec, field, value):
            if field == 'Botanical Name':
                raise RuntimeError('native failure')
            self.fields[h][field] = value
        self.vs.SetRField.side_effect = fail_second
        result = self.run_command('batch_update_plants', updates=writes)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['updated'], 1)
        self.assertEqual(self.fields['plant']['Height'], '15')

    def test_legacy_database_discloses_symbol_name_candidates(self):
        self.ns['_collect'] = Mock(return_value=['Plant Symbol', 'Ordinary'])
        result = self.run_command('get_plant_database')
        self.assertFalse(result['native_plant_database'])
        self.assertEqual(result['source'], 'document_symbol_name_search')

    def test_site_info_never_falls_back_to_stakes(self):
        self.ns['_collect'] = Mock(return_value=[])
        self.assertIn('error', self.run_command('get_site_model_info'))
        self.ns['_collect'].assert_called_once_with('T=DTM')
        self.ns['_collect'].return_value = ['stake']
        self.assertIn('error', self.run_command('get_site_model_info'))
        self.ns['_collect'].return_value = ['site']
        self.assertEqual(self.run_command('get_site_model_info')['object_id'], 'site')

    def test_wrong_site_model_rejected_for_all_terrain_targets(self):
        for command, params in (
                ('get_z_at_xy', {}), ('get_terrain_elevation', {}),
                ('send_to_surface', {'object_id': 'plant'}),
                ('rise_to_surface', {'object_id': 'plant', 'send_type': 1}),
                ('clear_site_model_cache', {}), ('update_site_model', {}),
                ('terrain_sample_points', {'points': [{'x': 7, 'y': 19}]})):
            with self.subTest(command=command):
                self.assertIn('error', self.run_command(command, site_model_id='stake', **params))
        for api in ('DTM6_GetZatXY', 'DTM6_SendToSurface', 'DTM6_RiseToSurface',
                    'DTM6_ClearModelCache', 'ResetObject'):
            getattr(self.vs, api).assert_not_called()

    def test_terrain_preflights_all_points_selectors_and_finite_inputs(self):
        invalid = [[], [{'x': 7, 'y': True}], [{'x': float('inf'), 'y': 19}],
                   [{'x': 7}], [{'x': 7, 'y': 19}] * 201,
                   [{'x': 7, 'y': 19}, {'x': 'bad', 'y': 19}]]
        for points in invalid:
            self.assertIn('error', self.run_command('terrain_sample_points', points=points))
        for types in ([1, 1], [True], [3], [], '2', [1.0]):
            self.assertIn('error', self.run_command('terrain_sample_points',
                                                  points=[{'x': 7, 'y': 19}], tin_types=types))
        for value in (True, '7', float('nan'), float('inf')):
            self.assertIn('error', self.run_command('get_z_at_xy', x=value))
        self.vs.DTM6_GetZatXY.assert_not_called()

    def test_terrain_samples_surfaces_outside_and_stop_on_native_failure(self):
        values = {('site', 0, 7.0, 19.0): (True, 83),
                  ('site', 1, 7.0, 19.0): (True, 84.5)}
        self.vs.DTM6_GetZatXY.side_effect = lambda *args: values.get(args, (False, -999))
        result = self.run_command('terrain_sample_points',
                                  points=[{'x': 7, 'y': 19}, {'x': 400, 'y': -90}], tin_types=[0, 1])
        self.assertEqual(result['queries_completed'], 4)
        self.assertEqual(result['outside_count'], 2)
        self.assertEqual([v['z'] for v in result['samples'][0]['elevations']], [83, 84.5])
        self.assertIsNone(result['samples'][1]['elevations'][0]['z'])
        self.vs.DTM6_GetZatXY.reset_mock()
        self.vs.DTM6_GetZatXY.side_effect = [(True, 83), RuntimeError('native failure'), (True, 99)]
        result = self.run_command('terrain_sample_points', points=[{'x': 7, 'y': 19}], tin_types=[0, 1, 2])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['queries_completed'], 1)
        self.assertEqual(result['samples'][0]['failed_tin_type'], 1)
        self.assertEqual(self.vs.DTM6_GetZatXY.call_count, 2)

    def test_nonfinite_native_elevation_never_becomes_success(self):
        for raw in ((True, float('nan')), (1, 83), None):
            self.vs.DTM6_GetZatXY.return_value = raw
            self.assertIn('error', self.run_command('get_z_at_xy', x=7, y=19))

    def test_site_lookup_never_requests_interactive_selection(self):
        self.vs.ActLayer = Mock(return_value='layer')
        self.vs.DTM6_GetDTMObject = Mock(return_value='site')
        active = next(n for n in SOURCE.body if isinstance(n, ast.FunctionDef) and n.name == '_active_dtm')
        exec(compile(ast.Module(body=[active], type_ignores=[]), '<active dtm>', 'exec'), self.ns)
        self.assertEqual(self.ns['_active_dtm'](), 'site')
        self.vs.DTM6_GetDTMObject.assert_called_once_with('layer', False)
        self.vs.DTM6_GetDTMObject.reset_mock()
        self.assertEqual(self.run_command('site_model_on_layer')['object_id'], 'site')
        self.vs.DTM6_GetDTMObject.assert_called_once_with('layer', False)

    def test_site_lookup_rejects_a_sole_model_from_another_layer(self):
        self.vs.ActLayer = Mock(return_value='layer')
        self.vs.DTM6_GetDTMObject = Mock(return_value='site')
        self.vs.GetLayer.return_value = 'other-layer'
        self.assertIsNone(self.run_command('site_model_on_layer')['object_id'])
        self.vs.GetObjectVariableInt.return_value = 2
        self.vs.DTM6_GetDTMObject.reset_mock()
        self.assertIn('error', self.run_command('site_model_on_layer'))
        self.vs.DTM6_GetDTMObject.assert_not_called()

    def test_send_to_surface_preserves_actual_uuid_and_never_guesses_from_last_object(self):
        self.vs.LNewObj = Mock(return_value='wall')
        result = self.run_command('send_to_surface', object_id='plant', site_model_id='site')
        self.assertEqual(result['object_id'], 'plant')
        self.assertFalse(result['geometry_verified'])
        self.vs.LNewObj.assert_not_called()
        self.ns['_h'] = Mock(side_effect=['plant', 'site', None])
        result = self.run_command('send_to_surface', object_id='plant', site_model_id='site')
        self.assertEqual(result['status'], 'partial')
        self.assertIsNone(result['object_id'])
        self.assertEqual(result['source_id'], 'plant')

    def test_surface_native_exception_or_malformed_result_retains_uncertain_state(self):
        for outcome in (RuntimeError('failed after mutation'), None, 1):
            with self.subTest(outcome=outcome):
                if isinstance(outcome, Exception):
                    self.vs.DTM6_SendToSurface.side_effect = outcome
                else:
                    self.vs.DTM6_SendToSurface.side_effect = None
                    self.vs.DTM6_SendToSurface.return_value = outcome
                result = self.run_command('send_to_surface', object_id='plant', site_model_id='site')
                self.assertEqual(result['status'], 'partial')
                self.assertTrue(result['dispatched'])
                self.assertEqual(result['source_id'], 'plant')
                self.assertIsNone(result['object_id'])

    def test_surface_post_mutation_type_lookup_failure_cannot_report_success(self):
        nodes = [node for node in SOURCE.body if isinstance(node, ast.FunctionDef)
                 and node.name in ('_h', '_oid')]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<uuid helpers>', 'exec'), self.ns)
        self.vs.GetObjectByUuid = Mock(side_effect=lambda value: value)
        self.vs.GetObjectUuid = Mock(side_effect=lambda value: value)
        def mutated(*args):
            self.vs.GetTypeN.side_effect = RuntimeError('native type lookup failed')
            return True
        self.vs.DTM6_SendToSurface.side_effect = mutated
        result = self.run_command('send_to_surface', object_id='plant', site_model_id='site')
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(result['dispatched'])
        self.assertIsNone(result['object_id'])
        self.assertEqual(result['source_id'], 'plant')
        self.vs.GetObjectUuid.assert_not_called()

    def test_landscape_inspection_distinguishes_observation_from_geometry_verification(self):
        result = self.run_command('landscape_object_info', object_id='hardscape')
        self.assertEqual(result['type'], 86)
        self.assertEqual(result['record_name'], 'Hardscape')
        self.assertEqual(result['parameters']['Thickness'], '6')
        self.assertEqual(result['center_3d'], ((7, 19), 83))
        self.assertEqual(result['bounds_frame'], 'screen_plane_projection')
        self.assertFalse(result['geometry_verified'])
        self.assertIn('error', self.run_command('landscape_object_info', object_id='wall'))
        self.vs.Get3DCntr.side_effect = RuntimeError('unavailable')
        result = self.run_command('landscape_object_info', object_id='hardscape')
        self.assertEqual(result['status'], 'partial')
        self.assertIn('center_3d', result['inspection_errors'])

    def prepare_duplicate(self):
        self.vs.GetLayerByName = Mock(return_value='layer')
        self.vs.GetObjectVariableInt = Mock(return_value=1)
        self.vs.GetParent = Mock(return_value='layer')
        self.vs.HMove = Mock()
        def duplicate(source, layer):
            self.types['copy'] = 86
            self.plugins['copy'] = self.plugins[source]
            self.fields['copy'] = dict(self.fields[source])
            return 'copy'
        self.vs.CreateDuplicateObject = Mock(side_effect=duplicate)

    def test_template_duplication_preserves_source_and_reports_pending_geometry(self):
        self.prepare_duplicate()
        result = self.run_command('landscape_duplicate_template', source_id='hardscape',
                                  target_layer='Design', dx=7, dy=-19, fields={'Thickness': '8'})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['object_id'], 'copy')
        self.assertEqual(self.fields['hardscape']['Thickness'], '6')
        self.assertEqual(self.fields['copy']['Thickness'], '8')
        self.vs.CreateDuplicateObject.assert_called_once_with('hardscape', 'layer')
        self.vs.HMove.assert_called_once_with('copy', 7.0, -19.0)
        self.vs.ResetObject.assert_called_once_with('copy')
        self.assertTrue(result['regeneration_pending'])
        self.assertFalse(result['geometry_verified'])

    def test_template_invalid_fields_and_layer_prevent_creation(self):
        self.prepare_duplicate()
        for params in ({'fields': {'Absent': 1}}, {'dx': float('nan')}, {'source_id': 'wall'}):
            arguments = {'source_id': 'hardscape', 'target_layer': 'Design', **params}
            self.assertFalse(self.run_command('landscape_duplicate_template', **arguments)['dispatched'])
        self.vs.GetObjectVariableInt.return_value = 2
        self.assertFalse(self.run_command('landscape_duplicate_template', source_id='hardscape',
                                         target_layer='Sheet')['dispatched'])
        self.vs.CreateDuplicateObject.assert_not_called()

    def test_template_alias_never_mutates_source_and_partial_copy_keeps_uuid(self):
        self.prepare_duplicate()
        self.vs.CreateDuplicateObject.side_effect = lambda source, layer: source
        result = self.run_command('landscape_duplicate_template', source_id='hardscape', target_layer='Design')
        self.assertIn('error', result)
        self.vs.HMove.assert_not_called()
        self.vs.SetRField.assert_not_called()
        self.vs.ResetObject.assert_not_called()
        self.prepare_duplicate()
        self.vs.SetRField.side_effect = None
        result = self.run_command('landscape_duplicate_template', source_id='hardscape',
                                  target_layer='Design', fields={'Thickness': '9'})
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(result['created'])
        self.assertEqual(result['object_id'], 'copy')
        self.assertEqual(self.fields['hardscape']['Thickness'], '6')


class LandscapeRecordFormatTests(unittest.TestCase):
    def setUp(self):
        self.ns = command_namespace()
        self.vs = self.ns['vs']
        self.records = {}
        self.kinds = {}
        self.ns['_oid'] = lambda h: h
        self.vs.GetObject = Mock(side_effect=lambda name: name if name in self.kinds else 'missing-dummy')
        self.vs.GetTypeN = Mock(side_effect=lambda h: self.kinds.get(h, 0))
        self.vs.IsPluginFormat = Mock(return_value=False)
        self.vs.NumFields = Mock(side_effect=lambda h: len(self.records[h]))
        self.vs.GetFldName = Mock(side_effect=lambda h, index: list(self.records[h])[index - 1])
        self.vs.GetFldType = Mock(side_effect=lambda h, index: list(self.records[h].values())[index - 1]['type'])
        self.vs.GetRField = Mock(side_effect=lambda h, record, field: self.records[h][field]['default'])
        def new_field(name, field, default, kind, flags):
            self.kinds[name] = 47
            self.records.setdefault(name, {})[field] = {'type': kind, 'default': default}
        self.vs.NewField = Mock(side_effect=new_field)

    def create(self, fields, name='Landscape Metadata'):
        return self.ns['create_record_format']({'name': name, 'fields': fields})

    def test_new_record_uses_newfield_and_reads_back_types_and_defaults(self):
        result = self.create([{'name': 'Status', 'default': 'proposed'},
                              {'name': 'Quantity', 'type': 'number', 'default': 2.5},
                              {'name': 'Count', 'type': 'integer', 'default': 3},
                              {'name': 'Included', 'type': 'boolean', 'default': True}])
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['fields_added'], 4)
        self.assertFalse(result['existed'])
        self.assertEqual(result['object_id'], 'Landscape Metadata')
        self.assertEqual(result['fields']['Quantity'], {'type': 3, 'default': '2.5'})
        self.assertEqual(self.vs.NewField.call_count, 4)

    def test_existing_defaults_are_preserved_and_conflicting_types_reject_all_writes(self):
        self.kinds['Landscape Metadata'] = 47
        self.records['Landscape Metadata'] = {'Status': {'type': 4, 'default': 'existing'}}
        result = self.create([{'name': 'Status', 'default': 'proposed'}, {'name': 'Category', 'default': 'paving'}])
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['fields_added'], 1)
        self.assertEqual(result['preserved_existing'], ['Status'])
        self.assertEqual(self.records['Landscape Metadata']['Status']['default'], 'existing')
        self.vs.NewField.reset_mock()
        result = self.create([{'name': 'Material'}, {'name': 'Status', 'type': 'integer', 'default': 3}])
        self.assertFalse(result['dispatched'])
        self.vs.NewField.assert_not_called()

    def test_definition_errors_preflight_entire_request_before_creating(self):
        for fields in ([], [{'name': 'A'}, {'name': 'A'}],
                       [{'name': 'A'}, {'name': 'B', 'type': 'nonsense'}],
                       [{'name': 'A'}, {'name': 'B', 'type': 'integer', 'default': 2.5}],
                       [{'name': 'A'}, {'name': 'B', 'type': 'real', 'default': float('nan')}],
                       [{'name': 'A'}, {'name': 'B', 'type': 'boolean', 'default': 'sometimes'}]):
            with self.subTest(fields=fields):
                self.assertFalse(self.create(fields)['dispatched'])
        self.vs.NewField.assert_not_called()

    def test_wrong_resource_and_plugin_format_reject_before_native_write(self):
        self.kinds['Landscape Metadata'] = 16
        self.assertFalse(self.create([{'name': 'Status'}])['dispatched'])
        self.kinds['Landscape Metadata'] = 47
        self.vs.IsPluginFormat.return_value = True
        self.assertFalse(self.create([{'name': 'Status'}])['dispatched'])
        self.vs.NewField.assert_not_called()

    def test_native_noop_or_exception_reports_retained_partial_record(self):
        original = self.vs.NewField.side_effect
        def fail_second(*args):
            if args[1] == 'Material':
                raise RuntimeError('native field failure')
            return original(*args)
        self.vs.NewField.side_effect = fail_second
        result = self.create([{'name': 'Status', 'default': 'proposed'}, {'name': 'Material'}])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['object_id'], 'Landscape Metadata')
        self.assertEqual(result['added_fields'], ['Status'])
        self.assertEqual(self.records['Landscape Metadata']['Status']['default'], 'proposed')
        self.vs.NewField.side_effect = None
        result = self.create([{'name': 'Missing'}])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['fields_added'], 0)

    def test_lookup_failure_never_becomes_permission_to_create(self):
        self.vs.GetObject.side_effect = RuntimeError('lookup failed')
        self.assertFalse(self.create([{'name': 'Status'}])['dispatched'])
        self.vs.NewField.assert_not_called()


if __name__ == '__main__':
    unittest.main()
