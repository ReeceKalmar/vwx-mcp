"""Analytic fixture geometry and adversarial shells, with no Vectorworks calls."""
import copy
import importlib.util
import math
from pathlib import Path
import random
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('architecture_oracle_tests', ROOT / 'tools/sdk_architecture_oracles.py')
ORACLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ORACLE)
PARAMETERS = dict(x_bounds=(10, 20), y_bounds=(20, 28), base_z=12,
                  slope_xy=(0, .25), normal_thickness=.5)
HEIGHT = math.sqrt(17) / 8


def shell():
    # Eight explicitly enumerated vertices; this fixture does not call the
    # oracle's plane, corner, normal, area, volume or topology implementations.
    points = [(10, 20, 12), (20, 20, 12), (20, 28, 14), (10, 28, 14),
              (10, 20, 12 + HEIGHT), (20, 20, 12 + HEIGHT),
              (20, 28, 14 + HEIGHT), (10, 28, 14 + HEIGHT)]
    faces = ((0, 1, 2, 3), (4, 5, 6, 7), (0, 3, 7, 4),
             (1, 2, 6, 5), (0, 1, 5, 4), (3, 2, 6, 7))
    return [{'face_id': 'face-' + str(index), 'points': [list(points[i]) for i in face]}
            for index, face in enumerate(faces)]


def triangular_shell():
    result = []
    for face in shell():
        a, b, c, d = face['points']
        result.extend([{'face_id': face['face_id'] + '-a', 'points': copy.deepcopy([a, b, c])},
                       {'face_id': face['face_id'] + '-b', 'points': copy.deepcopy([a, c, d])}])
    return result


class RoofOracleTests(unittest.TestCase):
    def verify(self, polygons=None, **parameters):
        return ORACLE.validate_roof_body(shell() if polygons is None else polygons,
                                        **dict(PARAMETERS, **parameters))

    def reject(self, polygons, **parameters):
        with self.assertRaises(ORACLE.RoofGeometryError):
            self.verify(polygons, **parameters)

    def test_exact_prism_volume_centroid_areas_and_topology(self):
        result = self.verify()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['native_calls'], 0)
        self.assertEqual((result['vertex_count'], result['edge_count'], result['polygon_count']), (8, 12, 6))
        self.assertAlmostEqual(result['volume'], 10 * math.sqrt(17), places=11)
        for actual, expected in zip(result['solid_centroid_xyz'], (15, 24, 13 + math.sqrt(17) / 16)):
            self.assertAlmostEqual(actual, expected, places=12)
        for plane in ('top', 'bottom'):
            self.assertAlmostEqual(result['area_by_plane'][plane], 20 * math.sqrt(17), places=11)
        for plane in ('xmin', 'xmax'):
            self.assertAlmostEqual(result['area_by_plane'][plane], math.sqrt(17), places=11)
        for plane in ('ymin', 'ymax'):
            self.assertAlmostEqual(result['area_by_plane'][plane], 1.25 * math.sqrt(17), places=11)
        self.assertEqual(result['bounds_xyz'][0], [10, 20, 12])
        self.assertAlmostEqual(result['bounds_xyz'][1][2], 14 + HEIGHT)

    def test_conforming_triangulation_preserves_volume_and_centroid(self):
        result = self.verify(triangular_shell())
        self.assertEqual((result['vertex_count'], result['edge_count'], result['polygon_count']), (8, 18, 12))
        self.assertAlmostEqual(result['volume'], 10 * math.sqrt(17), places=11)
        self.assertEqual(result['solid_centroid_xyz'], self.verify()['solid_centroid_xyz'])

    def test_face_order_winding_and_start_vertex_do_not_change_geometry(self):
        randomizer = random.Random(3200882699)
        for _ in range(15):
            polygons = shell()
            randomizer.shuffle(polygons)
            for face in polygons:
                points = face['points']
                index = randomizer.randrange(4)
                points[:] = points[index:] + points[:index]
                if randomizer.randrange(2):
                    points.reverse()
            self.assertAlmostEqual(self.verify(polygons)['volume'], 10 * math.sqrt(17), places=11)

    def test_optional_closing_point_and_input_immutability(self):
        polygons = shell()
        for face in polygons:
            face['points'].append(face['points'][0][:])
        original = copy.deepcopy(polygons)
        self.verify(polygons)
        self.assertEqual(polygons, original)

    def test_translation_uses_local_frame_without_world_origin_cancellation(self):
        shift = (1000000, -2000000, 3000000)
        polygons = shell()
        for face in polygons:
            face['points'] = [[value + delta for value, delta in zip(point, shift)] for point in face['points']]
        result = self.verify(polygons, x_bounds=(1000010, 1000020), y_bounds=(-1999980, -1999972), base_z=3000012)
        self.assertAlmostEqual(result['volume'], 10 * math.sqrt(17), delta=1e-7)
        for actual, expected, delta in zip(result['solid_centroid_xyz'], (15, 24, 13 + HEIGHT / 2), shift):
            self.assertAlmostEqual(actual, expected + delta, delta=1e-7)
        self.reject(polygons)  # A translation must also be declared in the fixture.

    def test_negative_slope_has_correct_low_corner_and_center(self):
        polygons = shell()
        for face in polygons:
            for point in face['points']:
                point[1] = 48 - point[1]
        result = self.verify(polygons, base_z=14, slope_xy=(0, -.25))
        self.assertAlmostEqual(result['volume'], 10 * math.sqrt(17), places=11)
        self.assertEqual(result['bounds_xyz'][0], [10, 20, 12])
        self.assertAlmostEqual(result['solid_centroid_xyz'][2], 13 + HEIGHT / 2)

    def test_axis_exchange_rotates_slope_without_changing_volume(self):
        polygons = shell()
        for face in polygons:
            for point in face['points']:
                point[0], point[1] = point[1], point[0]
        result = self.verify(polygons, x_bounds=(20, 28), y_bounds=(10, 20), slope_xy=(.25, 0))
        self.assertAlmostEqual(result['volume'], 10 * math.sqrt(17), places=11)
        self.assertEqual(result['solid_centroid_xyz'][:2], [24, 15])

    def test_flat_roof_and_uniform_unit_scaling(self):
        flat = shell()
        for face in flat:
            for point in face['points']:
                point[2] -= (point[1] - 20) / 4
        result = self.verify(flat, slope_xy=(0, 0), normal_thickness=HEIGHT)
        self.assertAlmostEqual(result['area_by_plane']['top'], 80)
        self.assertAlmostEqual(result['volume'], 10 * math.sqrt(17), places=11)
        scaled = shell()
        for face in scaled:
            face['points'] = [[5 * value for value in point] for point in face['points']]
        result = self.verify(scaled, x_bounds=(50, 100), y_bounds=(100, 140), base_z=60, normal_thickness=2.5)
        self.assertAlmostEqual(result['volume'], 1250 * math.sqrt(17), places=9)

    def test_two_axis_slope_uses_perpendicular_thickness(self):
        polygons = shell()
        new_height = math.sqrt(21) / 8
        for face in polygons:
            for point in face['points']:
                is_top = point[2] in (12 + HEIGHT, 14 + HEIGHT)
                point[2] += (point[0] - 10) / 2 + (new_height - HEIGHT if is_top else 0)
        result = self.verify(polygons, slope_xy=(.5, .25))
        self.assertAlmostEqual(result['volume'], 10 * math.sqrt(21), places=11)
        self.assertAlmostEqual(result['area_by_plane']['top'], 20 * math.sqrt(21), places=11)
        self.assertAlmostEqual(result['solid_centroid_xyz'][2], 15.5 + math.sqrt(21) / 16, places=11)
        self.assertAlmostEqual(result['spans_xyz'][2], 7 + new_height, places=11)

    def test_omitted_face_and_duplicate_ids_are_rejected(self):
        self.reject(shell()[:-1])
        polygons = shell()
        polygons[-1]['face_id'] = polygons[0]['face_id']
        self.reject(polygons)

    def test_duplicate_geometry_with_distinct_labels_is_not_coverage(self):
        polygons = shell()
        duplicate = copy.deepcopy(polygons[0])
        duplicate['face_id'] = 'unique-label-same-face'
        self.reject(polygons + [duplicate])
        polygons[-1] = duplicate
        self.reject(polygons)

    def test_missing_triangle_and_replacement_overlap_are_not_watertight(self):
        polygons = triangular_shell()
        self.reject(polygons[:-1])
        polygons[-1]['points'] = copy.deepcopy(polygons[0]['points'])
        self.reject(polygons)

    def test_oversized_untrimmed_side_net_rejected(self):
        polygons = shell()
        polygons[2]['points'] = [[10, 20, 11], [10, 28, 11], [10, 28, 16], [10, 20, 16]]
        with self.assertRaisesRegex(ORACLE.RoofGeometryError, 'halfspaces'):
            self.verify(polygons)

    def test_nonplanar_or_interior_face_rejected(self):
        polygons = shell()
        polygons[0]['points'][0][2] += .1
        self.reject(polygons)
        polygons = shell()
        for point in polygons[0]['points']:
            point[2] += HEIGHT / 2
        self.reject(polygons)

    def test_crossed_and_star_polygons_rejected(self):
        polygons = shell()
        a, b, c, d = polygons[0]['points']
        polygons[0]['points'] = [a, c, b, d]
        self.reject(polygons)
        ring = [[15 + 2 * math.cos(i * 2 * math.pi / 5), 24 + 2 * math.sin(i * 2 * math.pi / 5)] for i in range(5)]
        polygons = shell()
        polygons[0]['points'] = [[ring[i][0], ring[i][1], 12 + (ring[i][1] - 20) / 4] for i in (0, 2, 4, 1, 3)]
        with self.assertRaisesRegex(ORACLE.RoofGeometryError, 'simple convex'):
            self.verify(polygons)

    def test_unmatched_edge_subdivision_and_repeated_vertex_rejected(self):
        polygons = shell()
        a, b = polygons[0]['points'][:2]
        polygons[0]['points'].insert(1, [(x + y) / 2 for x, y in zip(a, b)])
        with self.assertRaisesRegex(ORACLE.RoofGeometryError, 'watertight'):
            self.verify(polygons)
        polygons = shell()
        polygons[0]['points'].insert(2, polygons[0]['points'][0][:])
        self.reject(polygons)

    def test_malformed_polygon_and_point_shapes_rejected(self):
        for value in (None, {}, (), [], [1] * 6, shell() * 11):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(ORACLE.RoofGeometryError):
                    ORACLE.validate_roof_body(value, **PARAMETERS)
        for value in (None, {}, [1, 2], [1, 2, 3, 4], '123'):
            polygons = shell()
            polygons[0]['points'][0] = value
            self.reject(polygons)
        for field, value in (('face_id', ''), ('face_id', '  '), ('face_id', True), ('face_id', []), ('points', None), ('points', [[0, 0, 0]] * 33)):
            polygons = shell()
            polygons[0][field] = value
            self.reject(polygons)
        polygons = shell()
        polygons[0]['uuid'] = 'native identifiers are not part of this contract'
        self.reject(polygons)

    def test_nonfinite_boolean_and_unrepresentable_coordinates_rejected(self):
        for bad in (True, False, float('nan'), float('inf'), -float('inf'), 10 ** 10000, '10'):
            polygons = shell()
            polygons[0]['points'][0][0] = bad
            self.reject(polygons)

    def test_invalid_fixture_dimensions_slopes_and_tolerances_rejected(self):
        for key, value in (('x_bounds', (20, 10)), ('x_bounds', (10, 10)), ('y_bounds', (20, 20.0000001)),
                           ('base_z', True), ('base_z', float('nan')), ('normal_thickness', 0),
                           ('normal_thickness', -.5), ('normal_thickness', True), ('slope_xy', (0, float('inf'))),
                           ('slope_xy', (False, .25)), ('abs_tol', 0), ('abs_tol', -1), ('abs_tol', True),
                           ('abs_tol', float('nan')), ('abs_tol', .01)):
            with self.subTest(key=key, value=value):
                self.reject(shell(), **{key: value})

    def test_wrong_thickness_or_slope_cannot_pass_volume_checks(self):
        self.reject(shell(), normal_thickness=.75)
        self.reject(shell(), slope_xy=(0, -.25))
        self.reject(shell(), base_z=12.1)

    def test_optimized_python_does_not_disable_validation(self):
        code = ('import importlib.util,sys\n'
                's=importlib.util.spec_from_file_location("oracle",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n'
                'try:m.validate_roof_body([],x_bounds=(10,20),y_bounds=(20,28),base_z=12,slope_xy=(0,.25),normal_thickness=.5)\n'
                'except m.RoofGeometryError:sys.exit(0)\n'
                'sys.exit(1)\n')
        result = subprocess.run([sys.executable, '-O', '-B', '-c', code, str(ROOT / 'tools/sdk_architecture_oracles.py')],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
