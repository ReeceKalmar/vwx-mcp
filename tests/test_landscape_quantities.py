"""Native snapshot/record regressions with independent quantities; no live host."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from test_sdk_commands import command_namespace


ROOT = Path(__file__).resolve().parents[1]
PROPOSED = '11111111-1111-4111-8111-111111111111'
EXISTING = '22222222-2222-4222-8222-222222222222'
PART = '33333333-3333-4333-8333-333333333333'
GROUP = '55555555-5555-4555-8555-555555555555'
RECORD = 'VWX_Landscape'
FIELDS = ('Status', 'Role', 'Category', 'Material', 'Unit', 'CountField',
          'AssemblyId', 'ClassificationSource', 'Measurement', 'Description')


class NativeQuantities:
    def __init__(self):
        self.records = {}
        self.types = {PROPOSED: 3, EXISTING: 3, PART: 3, RECORD: 47, 'layer': 31}
        self.area = {PROPOSED: 2160.0, EXISTING: 14400.0, PART: 144.0}
        self.reads = []
        self.writes = []
        self.ignore_writes = False
        self.parents = {}
        self.layer_type = 1
        self.matrices = {}

    def GetObject(self, name):
        return name if name in self.types else None

    def GetTypeN(self, handle):
        return self.types.get(handle, 0)

    def IsPluginFormat(self, handle):
        return False

    def NumFields(self, handle):
        return len(FIELDS)

    def GetFldName(self, handle, index):
        return FIELDS[index - 1]

    def GetFldType(self, handle, index):
        return 4

    def NumRecords(self, handle):
        return int(handle in self.records)

    def GetRecord(self, handle, index):
        return RECORD if handle in self.records and index == 1 else None

    def GetName(self, handle):
        return handle

    def SetRecord(self, handle, name):
        self.writes.append(('attach', handle, name))
        self.records.setdefault(handle, {})

    def SetRField(self, handle, name, field, value):
        self.writes.append(('field', handle, field, value))
        if not self.ignore_writes:
            self.records[handle][field] = value

    def GetRField(self, handle, name, field):
        return self.records.get(handle, {}).get(field, '')

    def GetUnits(self):
        # Coordinate inches, deliberately different area display label.
        return (1, 0, 0, 1.0, 'Inches', 'Acres')

    def HAreaN(self, handle):
        self.reads.append(('area', handle))
        return self.area[handle]

    def HPerim(self, handle):
        self.reads.append(('perimeter', handle))
        return 192.0

    def GetParent(self, handle):
        return self.parents.get(handle, 'layer')

    def GetObjectVariableInt(self, handle, selector):
        if handle != 'layer' or selector != 154:
            raise AssertionError('Unexpected native selector')
        return self.layer_type

    def GetEntityMatrix(self, handle):
        return self.matrices.get(handle, (True, (0.0, 0.0, 0.0), 0.0, 0.0, 0.0))


class LandscapeQuantityTests(unittest.TestCase):
    def setUp(self):
        self.ns = command_namespace()
        self.ns['__file__'] = str(ROOT / 'vwx-plugin/commands.py')
        self.vs = NativeQuantities()
        self.ns['vs'] = self.vs
        self.ns['_h'] = lambda value: value if self.vs.GetTypeN(value) else None
        self.ns['_oid'] = lambda value: value
        self.path_patch = patch.object(sys, 'path', [str(ROOT / 'vwx-plugin'), *sys.path])
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

    def metadata(self, status='new_proposed', role='item', **extra):
        return dict(status=status, role=role, category='paving', material='pavers',
                    measurement='plan_area', unit='ft2',
                    classification_source='Approved design schedule', **extra)

    def classify(self, object_id, **extra):
        response = self.ns['landscape_set_metadata']({
            'object_id': object_id, 'metadata': self.metadata(**extra)})
        self.assertEqual(response['status'], 'ok', response)

    def test_new_native_measurement_excludes_existing_and_assembly_parts(self):
        self.classify(PROPOSED)
        self.classify(EXISTING, status='existing')
        self.classify(PART, role='assembly_part', assembly_id=PROPOSED)
        result = self.ns['landscape_takeoff']({'object_ids': [PROPOSED, EXISTING, PART]})
        self.assertEqual(len(result['line_items']), 1, result)
        line = result['line_items'][0]
        self.assertEqual(line['object_id'], PROPOSED)
        self.assertAlmostEqual(line['quantity'], 15.0)
        self.assertEqual(line['unit'], 'ft2')
        self.assertEqual(result['cost_totals'], [])
        self.assertEqual(len(result['excluded']), 2)
        self.assertNotIn(('area', EXISTING), self.vs.reads)
        self.assertNotIn(('area', PART), self.vs.reads)

    def test_takeoff_rereads_geometry_after_an_edit(self):
        self.classify(PROPOSED)
        first = self.ns['landscape_takeoff']({'object_ids': [PROPOSED]})
        self.vs.area[PROPOSED] = 2880.0
        second = self.ns['landscape_takeoff']({'object_ids': [PROPOSED]})
        self.assertEqual(first['line_items'][0]['quantity'], 15.0)
        self.assertEqual(second['line_items'][0]['quantity'], 20.0)

    def test_record_noop_is_reported_with_partial_mutation(self):
        self.vs.ignore_writes = True
        response = self.ns['landscape_set_metadata']({
            'object_id': PROPOSED, 'metadata': self.metadata()})
        self.assertIn('error', response)
        self.assertTrue(response['mutation_started'])
        self.assertNotEqual(response.get('status'), 'ok')

    def test_wrong_record_resource_type_rejects_before_writing(self):
        self.vs.types[RECORD] = 16
        response = self.ns['landscape_set_metadata']({
            'object_id': PROPOSED, 'metadata': self.metadata()})
        self.assertIn('error', response)
        self.assertEqual(self.vs.writes, [])

    def test_invalid_classification_and_unit_reject_before_writing(self):
        for change in ({'status': 'new'}, {'unit': 'ft3'}, {'measurement': 'volume'}):
            with self.subTest(change=change):
                metadata = self.metadata()
                metadata.update(change)
                response = self.ns['landscape_set_metadata']({
                    'object_id': PROPOSED, 'metadata': metadata})
                self.assertIn('error', response)
                self.assertEqual(self.vs.writes, [])

    def test_unclassified_missing_and_duplicate_objects_never_inflate_totals(self):
        self.classify(PROPOSED)
        result = self.ns['landscape_takeoff']({
            'object_ids': [PROPOSED, PROPOSED, EXISTING, '44444444-4444-4444-8444-444444444444']})
        self.assertEqual(result['line_items'], [], result)
        self.assertTrue(result['excluded'])
        json.dumps(result, allow_nan=False)

    def test_resolved_uuid_alias_cannot_modify_or_bill_another_object(self):
        self.classify(EXISTING)
        self.vs.writes.clear()
        self.ns['_h'] = lambda value: EXISTING if value == PROPOSED else value
        changed = self.ns['landscape_set_metadata']({'object_id': PROPOSED, 'metadata': self.metadata()})
        self.assertIn('UUID differs', changed['error'])
        self.assertFalse(changed['mutation_started'])
        self.assertEqual(self.vs.writes, [])
        result = self.ns['landscape_takeoff']({'object_ids': [PROPOSED]})
        self.assertEqual(result['line_items'], [], result)
        self.assertEqual(self.vs.reads, [])

    def test_sheet_and_native_container_geometry_cannot_be_classified_or_billed(self):
        self.classify(PROPOSED)
        self.vs.writes.clear()
        for kind in (16, 15, 86, 122, 24, 71):
            with self.subTest(parent_type=kind):
                self.vs.types[GROUP] = kind
                self.vs.parents[PROPOSED] = GROUP
                changed = self.ns['landscape_set_metadata']({'object_id': PROPOSED, 'metadata': self.metadata()})
                self.assertIn('error', changed)
                self.assertFalse(changed['mutation_started'])
                result = self.ns['landscape_takeoff']({'object_ids': [PROPOSED]})
                self.assertEqual(result['line_items'], [], result)
        self.vs.parents.clear()
        self.vs.layer_type = 2
        changed = self.ns['landscape_set_metadata']({'object_id': PROPOSED, 'metadata': self.metadata()})
        self.assertIn('sheet annotations', changed['error'])
        result = self.ns['landscape_takeoff']({'object_ids': [PROPOSED]})
        self.assertEqual(result['line_items'], [], result)
        self.assertEqual(self.vs.writes, [])
        self.assertEqual(self.vs.reads, [])

    def test_grouped_design_items_remain_valid_but_assembly_and_reference_descendants_are_excluded(self):
        self.vs.types[GROUP] = 11
        self.vs.parents[PROPOSED] = GROUP
        self.classify(PROPOSED)
        result = self.ns['landscape_takeoff']({'object_ids': [PROPOSED]})
        self.assertEqual(result['line_items'][0]['quantity'], 15)
        for role in ('assembly', 'reference', 'markup'):
            self.classify(GROUP, role=role)
            result = self.ns['landscape_takeoff']({'object_ids': [PROPOSED]})
            self.assertEqual(result['line_items'], [], result)
        # Explicit excluded part metadata must remain writable inside a drawing
        # group, without relaxing the no-internal-geometry guard.
        self.classify(PROPOSED, role='assembly_part', assembly_id=GROUP)

    def test_cyclic_group_ancestry_rejects_before_metadata_mutation(self):
        self.vs.types[GROUP] = 11
        self.vs.parents.update({PROPOSED: GROUP, GROUP: GROUP})
        changed = self.ns['landscape_set_metadata']({'object_id': PROPOSED, 'metadata': self.metadata()})
        self.assertIn('cyclic', changed['error'])
        self.assertFalse(changed['mutation_started'])
        self.assertEqual(self.vs.writes, [])

    def test_metric_native_coordinate_area_uses_squared_scale_not_area_display_units(self):
        self.classify(PROPOSED)
        self.vs.GetUnits = lambda: (1, 0, 0, 25.4, 'mm', 'Acres')
        self.vs.area[PROPOSED] = 92903.04  # one square foot, in square millimetres
        result = self.ns['landscape_takeoff']({'object_ids': [PROPOSED]})
        self.assertAlmostEqual(result['line_items'][0]['quantity'], 1)

    def test_native_plant_count_text_is_validated_without_float_rounding(self):
        self.vs.types[PROPOSED] = 86
        self.vs.GetParametricRecord = lambda handle: 'Plant'
        original_fields = self.vs.GetFldName
        self.vs.GetFldName = lambda handle, index: 'Quantity' if handle == 'Plant' else original_fields(handle, index)
        original_count = self.vs.NumFields
        self.vs.NumFields = lambda handle: 1 if handle == 'Plant' else original_count(handle)
        metadata = self.metadata()
        metadata.update(measurement='plant_count', unit='each', count_field='Quantity')
        changed = self.ns['landscape_set_metadata']({'object_id': PROPOSED, 'metadata': metadata})
        self.assertEqual(changed['status'], 'ok', changed)
        original_read = self.vs.GetRField
        for value, accepted in [('7', True), ('7.0000000000000001', False),
                                ('9007199254740993', False), ('NaN', False), (True, False)]:
            with self.subTest(native_text=value):
                self.vs.GetRField = lambda handle, record, field: value if record == 'Plant' else original_read(handle, record, field)
                result = self.ns['landscape_takeoff']({'object_ids': [PROPOSED]})
                self.assertEqual(bool(result['line_items']), accepted, result)
                if accepted:
                    self.assertEqual(result['line_items'][0]['quantity'], 7)

    def test_surface_quantities_reject_tilt_failed_and_malformed_planar_transforms(self):
        self.classify(PROPOSED)
        rejected = [(True, (0, 0, 0), 30, 0, 0), (True, (0, 0, 0), 0, 0.0001, 0),
                    (False, (0, 0, 0), 0, 0, 0), (1, (0, 0, 0), 0, 0, 0),
                    (True, (0, 0), 0, 0, 0), (True, (0, float('nan'), 0), 0, 0, 0),
                    (True, (0, 0, 0), 0, 0, float('inf')), (True, 0, 0, 0, 0, 0, 0)]
        for measurement, unit in [('plan_area', 'ft2'), ('perimeter', 'ft')]:
            metadata = self.metadata()
            metadata.update(measurement=measurement, unit=unit)
            changed = self.ns['landscape_set_metadata']({'object_id': PROPOSED, 'metadata': metadata})
            self.assertEqual(changed['status'], 'ok', changed)
            for matrix in rejected:
                with self.subTest(measurement=measurement, matrix=matrix):
                    self.vs.matrices[PROPOSED] = matrix
                    result = self.ns['landscape_takeoff']({'object_ids': [PROPOSED]})
                    self.assertEqual(result['line_items'], [], result)
                    self.assertIn('measurement_failed', result['excluded'][0]['reason'])
        self.assertEqual(self.vs.reads, [], 'Unverified transforms must fail before area/perimeter measurement')

    def test_horizontal_revolutions_and_in_plane_rotation_preserve_area(self):
        self.classify(PROPOSED)
        self.vs.matrices[PROPOSED] = (True, (12, 30, 400), 180, -360, 37.5)
        result = self.ns['landscape_takeoff']({'object_ids': [PROPOSED]})
        self.assertEqual(result['line_items'][0]['quantity'], 15)

    def test_unknown_or_tilted_group_transform_excludes_horizontal_child(self):
        self.vs.types[GROUP] = 11
        self.vs.parents[PROPOSED] = GROUP
        self.classify(PROPOSED)
        for matrix in ((False, (0, 0, 0), 0, 0, 0), (True, (0, 0, 0), 45, 0, 0)):
            self.vs.matrices[GROUP] = matrix
            result = self.ns['landscape_takeoff']({'object_ids': [PROPOSED]})
            self.assertEqual(result['line_items'], [], result)
        self.assertEqual(self.vs.reads, [])

    def test_native_surface_requires_verified_owner_and_path_planes(self):
        self.vs.types[PROPOSED] = 86
        self.vs.types[PART] = 5
        self.vs.parents[PART] = PROPOSED
        self.vs.GetParametricRecord = lambda handle: 'Hardscape'
        self.vs.GetCustomObjectPath = lambda handle: PART
        self.vs.IsPolyClosed = lambda handle: True
        self.classify(PROPOSED)
        for owner, path in [((False, (0, 0, 0), 0, 0, 0), (True, (0, 0, 0), 0, 0, 0)),
                            ((True, (0, 0, 0), 0, 0, 0), (True, (0, 0, 0), 0, 15, 0))]:
            self.vs.matrices.update({PROPOSED: owner, PART: path})
            result = self.ns['landscape_takeoff']({'object_ids': [PROPOSED]})
            self.assertEqual(result['line_items'], [], result)
        self.assertEqual(self.vs.reads, [])
        self.vs.matrices.clear()
        result = self.ns['landscape_takeoff']({'object_ids': [PROPOSED]})
        self.assertEqual(result['line_items'][0]['quantity'], 1.0)
        self.assertEqual(self.vs.reads, [('area', PART)])

    def test_unavailable_plane_api_excludes_surface_without_guessing(self):
        self.classify(PROPOSED)
        def unavailable(handle):
            raise AttributeError('unavailable')
        self.vs.GetEntityMatrix = unavailable
        result = self.ns['landscape_takeoff']({'object_ids': [PROPOSED]})
        self.assertEqual(result['line_items'], [], result)
        self.assertIn('transform is unavailable', result['excluded'][0]['reason'])
        self.assertEqual(self.vs.reads, [])


if __name__ == '__main__':
    unittest.main()
