"""Independent landscape scope, dimensions and quote calculations; no host calls."""
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import unittest
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('landscape_takeoff', ROOT / 'vwx-plugin/landscape_takeoff.py')
TAKEOFF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TAKEOFF)


def item(number=1, **changes):
    row = {'object_id': str(UUID(int=number)), 'status': 'new_proposed', 'role': 'item',
           'category': 'Paving', 'material': 'Concrete paver', 'quantity_kind': 'area',
           'quantity': 96, 'unit': 'ft2', 'measurement_source': 'HAreaN; coordinate area converted from inches'}
    row.update(changes)
    return row


def quote(**changes):
    row = {'category': 'Paving', 'material': 'Concrete paver', 'quantity_kind': 'area',
           'unit': 'ft2', 'unit_price': 4.25, 'currency': 'USD', 'source': 'Owner supplied quote Q-104'}
    row.update(changes)
    return row


class LandscapeTakeoffTests(unittest.TestCase):
    def test_existing_house_drawn_today_and_new_proposal_are_separate_scope(self):
        rows = [item(1, status='existing', name='New house geometry', created_today=True),
                item(2, description='Proposed courtyard')]
        report = TAKEOFF.build_takeoff(rows)
        self.assertEqual([row['object_id'] for row in report['line_items']], [item(2)['object_id']])
        self.assertEqual(report['quantity_totals'], [{'quantity_kind': 'area', 'unit': 'ft2', 'quantity': 96}])
        self.assertEqual(report['excluded'][0]['reason'], 'not_new_proposed')

    def test_reference_markup_parts_and_removal_never_enter_new_work(self):
        rows = [item(1, role='assembly')]
        rows.extend(item(index, role=role) for index, role in enumerate(
            ('reference', 'markup', 'assembly_part'), 2))
        rows.extend(item(index, status=status) for index, status in enumerate(
            ('existing', 'remove', 'unknown', ''), 5))
        rows.append(item(9, assembly_id=item(1)['object_id']))
        result = TAKEOFF.build_takeoff(rows)
        self.assertEqual(result['summary']['included_objects'], 1)
        self.assertEqual(result['summary']['excluded_objects'], 8)
        self.assertEqual(result['excluded'][-1]['reason'], 'assembly_member')

    def test_conflicting_duplicate_uuid_excludes_all_occurrences(self):
        first = item(0xABCDEF)
        second = item(0xABCDEF, status='existing', quantity=120)
        second['object_id'] = '{' + first['object_id'].upper() + '}'
        result = TAKEOFF.build_takeoff([first, second, item(2)])
        self.assertEqual(result['summary']['included_objects'], 1)
        self.assertEqual([row['reason'] for row in result['excluded']], ['duplicate_object_uuid'] * 2)
        self.assertEqual(result['quantity_totals'][0]['quantity'], 96)

    def test_nil_missing_and_non_uuid_identities_are_excluded(self):
        values = [None, '', 'rectangle', str(UUID(int=0)), 1, True]
        result = TAKEOFF.build_takeoff([item(index + 1, object_id=value) for index, value in enumerate(values)])
        self.assertEqual(result['line_items'], [])
        self.assertEqual([row['reason'] for row in result['excluded']], ['invalid_object_uuid'] * len(values))

    def test_unclassified_native_geometry_is_not_inferred_from_layer_or_name(self):
        row = item()
        del row['status']
        row.update(layer='New Proposed', name='Install pavers')
        result = TAKEOFF.build_takeoff([row])
        self.assertEqual(result['summary']['included_objects'], 0)
        self.assertFalse(result['summary']['pricing_complete'])

    def test_missing_material_category_role_or_native_source_is_reported(self):
        for field in ('material', 'category', 'role', 'measurement_source'):
            with self.subTest(field=field):
                row = item()
                del row[field]
                report = TAKEOFF.build_takeoff([row])
                self.assertEqual(report['summary']['included_objects'], 0)
                self.assertEqual(report['summary']['excluded_objects'], 1)

    def test_invalid_quantities_cannot_become_zero_or_successful_measurements(self):
        for value in (None, True, False, '96', -1, 0, math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                report = TAKEOFF.build_takeoff([item(quantity=value)])
                self.assertEqual(report['quantity_totals'], [])
                self.assertEqual(report['summary']['excluded_objects'], 1)

    def test_native_measurement_failure_is_preserved_despite_a_stale_quantity(self):
        report = TAKEOFF.build_takeoff([item(measurement_error='native API returned no measurement')])
        self.assertEqual(report['line_items'], [])
        self.assertIn('native API returned no measurement', report['excluded'][0]['reason'])

    def test_units_must_match_dimension_and_have_an_explicit_supported_name(self):
        for kind, unit in (('area', 'ft'), ('length', 'ft2'), ('volume', 'ft2'),
                           ('count', 'ft'), ('area', 'square feet'), ('area', 'document')):
            with self.subTest(kind=kind, unit=unit):
                report = TAKEOFF.build_takeoff([item(quantity_kind=kind, unit=unit)])
                self.assertEqual(report['line_items'], [])
                self.assertEqual(report['excluded'][0]['reason'], 'unit does not match quantity_kind')

    def test_object_counts_require_native_uuids_and_whole_quantities(self):
        rows = [item(i, quantity_kind='count', unit='each', quantity=1,
                     measurement_source='independently resolved native UUID') for i in range(1, 4)]
        rows.append(item(4, quantity_kind='count', unit='each', quantity=30.5))
        report = TAKEOFF.build_takeoff(rows)
        self.assertEqual(report['quantity_totals'], [{'quantity_kind': 'count', 'unit': 'each', 'quantity': 3}])
        self.assertIn('positive integer', report['excluded'][0]['reason'])

    def test_native_multi_plant_pio_counts_are_distinct_from_object_counts(self):
        rows = [item(1, category='Planting', material='Serviceberry', quantity_kind='count', unit='each',
                     quantity=7, measurement='plant_count', count_field='Quantity',
                     measurement_source='GetRField: Plant.Quantity; native field discovery'),
                item(2, category='Planting', material='Serviceberry', quantity_kind='count', unit='each',
                     quantity=1, measurement_source='one independently resolved symbol UUID')]
        report = TAKEOFF.build_takeoff(rows)
        self.assertEqual(report['summary']['included_objects'], 2)
        self.assertEqual(report['quantity_totals'], [{'quantity_kind': 'count', 'unit': 'each', 'quantity': 8}])
        self.assertEqual(report['line_items'][0]['measurement_source'], rows[0]['measurement_source'])
        self.assertEqual(report['line_items'][0]['measurement'], 'plant_count')
        self.assertEqual(report['line_items'][0]['count_field'], 'Quantity')

    def test_explicit_object_count_cannot_impersonate_a_multi_plant_quantity(self):
        row = item(quantity_kind='count', unit='each', quantity=7, measurement='count')
        result = TAKEOFF.build_takeoff([row])
        self.assertEqual(result['line_items'], [])
        self.assertIn('object count must be one', result['excluded'][0]['reason'])

    def test_classification_provenance_is_preserved_and_wrong_measurement_is_excluded(self):
        rows = [item(1, classification_source='Owner approved drawing L1.0'),
                item(2, measurement='linear_length')]
        result = TAKEOFF.build_takeoff(rows)
        self.assertEqual(result['line_items'][0]['classification_source'], 'Owner approved drawing L1.0')
        self.assertEqual(result['excluded'][0]['reason'], 'measurement does not match quantity_kind')

    def test_independent_rectangle_measurements_use_squared_conversion(self):
        # A 12 ft by 8 ft rectangle: 144 by 96 native inches, 96 ft2 and 40 ft.
        self.assertEqual(TAKEOFF.convert_coordinate_quantity(13824, 'area', 1, 'ft2'), 96)
        self.assertEqual(TAKEOFF.convert_coordinate_quantity(480, 'length', 1, 'ft'), 40)
        self.assertEqual(TAKEOFF.convert_coordinate_quantity(6272640, 'area', 1, 'acre'), 1)

    def test_metric_native_units_and_cubic_dimensions_have_independent_oracles(self):
        # 3 m by 2 m measured in mm: 6 m2. A cubic yard is 36 cubed inches.
        self.assertAlmostEqual(TAKEOFF.convert_coordinate_quantity(6000000, 'area', 25.4, 'm2'), 6)
        self.assertEqual(TAKEOFF.convert_coordinate_quantity(12000, 'length', 25.4, 'm'), 12)
        self.assertEqual(TAKEOFF.convert_coordinate_quantity(46656, 'volume', 1, 'yd3'), 1)
        self.assertEqual(TAKEOFF.convert_coordinate_quantity(0, 'area', 1, 'ft2'), 0)

    def test_conversion_rejects_unknown_scale_and_dimension_mismatch(self):
        for scale in (None, True, '1', 0, -1, math.nan, math.inf):
            with self.subTest(scale=scale):
                with self.assertRaises(ValueError):
                    TAKEOFF.convert_coordinate_quantity(100, 'area', scale, 'ft2')
        for kind, unit in (('area', 'ft'), ('volume', 'ft2'), ('count', 'each')):
            with self.subTest(kind=kind, unit=unit):
                with self.assertRaises(ValueError):
                    TAKEOFF.convert_coordinate_quantity(100, kind, 1, unit)

    def test_units_dimensions_and_materials_never_mix_in_schedules(self):
        rows = [item(1), item(2, quantity=4, unit='m2'),
                item(3, quantity_kind='length', quantity=40, unit='ft'),
                item(4, material='Brick', quantity=20)]
        report = TAKEOFF.build_takeoff(rows)
        self.assertEqual(len(report['schedule']), 4)
        self.assertEqual(report['quantity_totals'], [
            {'quantity_kind': 'area', 'unit': 'ft2', 'quantity': 116},
            {'quantity_kind': 'area', 'unit': 'm2', 'quantity': 4},
            {'quantity_kind': 'length', 'unit': 'ft', 'quantity': 40}])

    def test_prices_require_explicit_sources_and_matching_units(self):
        report = TAKEOFF.build_takeoff([item(1), item(2, unit='m2', quantity=10)], [quote()])
        self.assertEqual(report['cost_totals'], [{'currency': 'USD', 'cost': 408}])
        self.assertEqual(report['summary']['priced_objects'], 1)
        self.assertEqual(report['summary']['unpriced_objects'], 1)
        self.assertFalse(report['summary']['pricing_complete'])
        self.assertEqual(report['line_items'][0]['price_source'], 'Owner supplied quote Q-104')
        self.assertNotIn('cost', report['line_items'][1])

    def test_unpriced_work_and_unused_quotes_remain_visible(self):
        report = TAKEOFF.build_takeoff([item()], [quote(material='Unknown paver')])
        self.assertEqual(report['cost_totals'], [])
        self.assertEqual(report['line_items'][0]['pricing_status'], 'unpriced')
        self.assertEqual(report['unused_prices'][0]['material'], 'Unknown paver')
        self.assertEqual(report['summary']['unpriced_objects'], 1)

    def test_zero_is_only_a_price_when_the_caller_explicitly_supplies_it(self):
        result = TAKEOFF.build_takeoff([item()], [quote(unit_price=0)])
        self.assertEqual(result['line_items'][0]['pricing_status'], 'priced')
        self.assertEqual(result['cost_totals'], [{'currency': 'USD', 'cost': 0}])
        self.assertTrue(result['summary']['pricing_complete'])

    def test_invalid_and_ambiguous_quotes_fail_instead_of_selecting_one(self):
        bad = [quote(source=''), quote(currency=''), quote(currency='usd'), quote(unit='ft'),
               quote(unit_price=-1), quote(unit_price=True), quote(unit_price=math.nan),
               quote(unit_price=None), quote(unit_price='4.25'), quote(tax=0)]
        for price in bad:
            with self.subTest(price=price):
                with self.assertRaises(ValueError):
                    TAKEOFF.build_takeoff([item()], [price])
        with self.assertRaisesRegex(ValueError, 'duplicate or conflicting'):
            TAKEOFF.build_takeoff([item()], [quote(), quote(currency='CAD')])

    def test_costs_keep_currencies_separate_and_preserve_decimal_extensions(self):
        rows = [item(1, quantity=0.1), item(2, quantity=0.2), item(3, material='Brick', quantity=10)]
        result = TAKEOFF.build_takeoff(rows, [quote(unit_price=3), quote(material='Brick', currency='CAD', unit_price=2.5)])
        self.assertEqual(result['cost_totals'], [{'currency': 'CAD', 'cost': 25}, {'currency': 'USD', 'cost': 0.9}])
        self.assertEqual(next(row for row in result['schedule'] if row['material'] == 'Concrete paver')['quantity'], 0.3)

    def test_native_quantities_cannot_be_overridden_by_descriptive_geometry(self):
        row = item(description='1000 square feet', width=100, height=100, area=10000, quantity=96)
        result = TAKEOFF.build_takeoff([row], [quote()])
        self.assertEqual(result['line_items'][0]['quantity'], 96)
        self.assertEqual(result['cost_totals'][0]['cost'], 408)

    def test_output_is_deterministic_and_input_snapshots_are_unchanged(self):
        rows = [item(2), item(1)]
        prices = [quote()]
        before = deepcopy((rows, prices))
        result = TAKEOFF.build_takeoff(rows, prices)
        self.assertEqual(result, TAKEOFF.build_takeoff(list(reversed(rows)), prices))
        self.assertEqual((rows, prices), before)
        result['line_items'][0]['description'] = 'consumer edit'
        self.assertEqual((rows, prices), before)

    def test_aggregate_overflow_fails_without_emitting_infinite_json(self):
        with self.assertRaises(ValueError):
            TAKEOFF.build_takeoff([item(quantity=1e300)], [quote(unit_price=1e300)])
        with self.assertRaises(ValueError):
            TAKEOFF.build_takeoff([item(1, quantity=1e308), item(2, quantity=1e308)])

    def test_snapshot_and_quote_inputs_are_bounded(self):
        for value in ({}, 'rows', [item()] * (TAKEOFF.MAX_ITEMS + 1)):
            with self.assertRaises(ValueError):
                TAKEOFF.build_takeoff(value)
        with self.assertRaises(ValueError):
            TAKEOFF.validate_prices([quote()] * (TAKEOFF.MAX_ITEMS + 1))

    def test_record_metadata_requires_explicit_scope_and_measurement(self):
        metadata = {'status': 'new_proposed', 'role': 'item', 'category': 'Paving',
                    'material': 'Brick', 'measurement': 'plan_area', 'unit': 'ft2'}
        output = TAKEOFF.validate_metadata(metadata)
        self.assertEqual(output['status'], 'new_proposed')
        self.assertEqual(output['description'], '')
        self.assertEqual(TAKEOFF.RECORD_NAME, 'VWX_Landscape')
        for missing in ('status', 'role', 'measurement', 'material', 'unit'):
            changed = dict(metadata)
            del changed[missing]
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                TAKEOFF.validate_metadata(changed)
        for changes in ({'measurement': 'volume'}, {'measurement': 'perimeter'},
                        {'quantity': 1000}, {'status': 'New'}, {'role': 'unknown'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                TAKEOFF.validate_metadata(dict(metadata, **changes))

    def test_plant_count_metadata_requires_an_explicit_discovered_native_field(self):
        metadata = {'status': 'new_proposed', 'role': 'item', 'category': 'Planting',
                    'material': 'Serviceberry', 'measurement': 'plant_count', 'unit': 'each'}
        with self.assertRaisesRegex(ValueError, 'count_field is required'):
            TAKEOFF.validate_metadata(metadata)
        self.assertEqual(TAKEOFF.validate_metadata(dict(metadata, count_field='Quantity'))['count_field'], 'Quantity')
        with self.assertRaisesRegex(ValueError, 'count_field is required'):
            TAKEOFF.validate_metadata(dict(metadata, measurement='count', count_field='Quantity'))


if __name__ == '__main__':
    unittest.main()
