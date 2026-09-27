"""Offline semantic quality checks; these are not Vectorworks native results."""
import copy
import cmath
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = r'C:\SDK-tests\VWX-MCP-SDK-TEST-geometry-offline.vwx'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEOMETRY = load('sdk_geometry_fixture_tests', ROOT / 'tools/sdk_geometry_fixtures.py')
HOST = GEOMETRY.DESIGN.HOST
RUNNER = load('sdk_geometry_runner_tests', ROOT / 'tools/sdk_design_runner.py')
REGISTRY = load('sdk_geometry_registry_tests', ROOT / 'tools/sdk_regression_suite.py')
POLICY = load('sdk_geometry_policy_tests', ROOT / 'mcp-server/background_policy.py')
CATALOG = json.loads((ROOT / 'vwx-plugin/sdk_catalog.json').read_text(encoding='utf-8'))
INDEX = json.loads((ROOT / 'vwx-plugin/vs_index.json').read_text(encoding='utf-8'))
RUNTIME = HOST._load_runtime(ROOT)
with patch.dict(sys.modules, {'sdk_runtime': RUNTIME}):
    SEQUENCES = load('sdk_geometry_sequence_tests', ROOT / 'vwx-plugin/sdk_sequences.py')


class _RectangleModel:
    """Independent polygon algebra, not a mock returning fixture expectations.

    Creation builds vertices. Mutations transform those vertices. Queries derive
    area, distance and extrema from their current state. Optional faults model
    silent native no-ops or scale/rotation mistakes and must fail later reads.
    """
    def __init__(self, fault=None):
        self.fault, self.objects, self.last, self.calls = fault, {}, None, []

    def GetVersion(self):
        return (32, 0, 0, 2)

    def GetFPathName(self):
        return DOCUMENT

    def Rect(self, p1, p2):
        self.calls.append('Rect')
        left, top = p1
        right, bottom = p2
        key = str(uuid.uuid4())
        self.last = SimpleNamespace(key=key, name='', vertices=[[left, top], [right, top], [right, bottom], [left, bottom]])
        self.objects[key] = self.last

    def LNewObj(self):
        return self.last

    def GetObjectUuid(self, h):
        return h.key

    def GetObjectByUuid(self, key):
        return self.objects.get(key)

    def GetTypeN(self, h):
        return 3 if h is not None and h.key in self.objects else 0

    def SetName(self, h, name):
        self.calls.append('SetName')
        h.name = name

    def GetName(self, h):
        return h.name

    def HAreaN(self, h):
        vertices = h.vertices
        return abs(sum(p[0]*q[1] - q[0]*p[1] for p, q in zip(vertices, vertices[1:]+vertices[:1]))) / 2

    def HPerim(self, h):
        vertices = h.vertices
        return sum(math.hypot(q[0]-p[0], q[1]-p[1]) for p, q in zip(vertices, vertices[1:]+vertices[:1]))

    HPerimN = HPerim

    def GetBBox(self, h):
        xs, ys = zip(*h.vertices)
        return ((min(xs), max(ys)), (max(xs), min(ys)))

    def HCenter(self, h):
        bounds = self.GetBBox(h)
        return tuple((bounds[0][axis] + bounds[1][axis])/2 for axis in (0, 1))

    def HMove(self, h, dx, dy):
        self.calls.append('HMove')
        if self.fault != 'ignore_translation':
            h.vertices = [[x+dx, y+dy] for x, y in h.vertices]

    def HRotate(self, h, center, angle):
        self.calls.append('HRotate')
        theta = math.radians(-angle if self.fault == 'reverse_rotation' else angle)
        c, s = math.cos(theta), math.sin(theta)
        cx, cy = center
        h.vertices = [[cx+c*(x-cx)-s*(y-cy), cy+s*(x-cx)+c*(y-cy)] for x, y in h.vertices]

    def HScale2D(self, h, cx, cy, sx, sy, scale_text):
        self.calls.append('HScale2D')
        if self.fault == 'uniform_instead_of_anisotropic':
            sy = sx
        h.vertices = [[cx+sx*(x-cx), cy+sy*(y-cy)] for x, y in h.vertices]


class _ArcModel(_RectangleModel):
    """Mutable circle geometry; an optional no-op setter must remain visible."""
    def Arc(self, p1, p2, start, sweep):
        assert math.isclose(abs(p2[0]-p1[0]), abs(p2[1]-p1[1]))
        self.ArcByCenter((p1[0]+p2[0])/2, (p1[1]+p2[1])/2, abs(p2[0]-p1[0])/2, start, sweep)

    def ArcByCenter(self, x, y, radius, start, sweep):
        key = str(uuid.uuid4())
        self.last = SimpleNamespace(key=key, name='', center=[x, y], radius=radius, start=start, sweep=sweep)
        self.objects[key] = self.last

    def GetTypeN(self, h):
        return 6 if h is not None and h.key in self.objects else 0

    def GetArc(self, h):
        return h.start, h.sweep

    def HCenter(self, h):
        return tuple(h.center)

    def SetArc(self, h, start, sweep):
        self.calls.append('SetArc')
        if self.fault == 'setter_requires_reset':
            h.pending_angles = (start, sweep)
        elif self.fault != 'ignore_set_arc':
            h.start, h.sweep = start, sweep

    def _reset(self, h):
        if hasattr(h, 'pending_angles'):
            h.start, h.sweep = h.pending_angles
            del h.pending_angles

    def ResetBBox(self, h):
        self.calls.append('ResetBBox')
        self._reset(h)

    def ResetObject(self, h):
        self.calls.append('ResetObject')
        self._reset(h)

    def HMove(self, h, dx, dy):
        self.calls.append('HMove')
        h.center = [h.center[0]+dx, h.center[1]+dy]

    def HRotate(self, h, center, angle):
        self.calls.append('HRotate')
        theta = math.radians(angle)
        x, y = (value-pivot for value, pivot in zip(h.center, center))
        h.center = [center[0]+x*math.cos(theta)-y*math.sin(theta), center[1]+x*math.sin(theta)+y*math.cos(theta)]
        h.start = (h.start+angle) % 360


class _ArcGeometryModel(_ArcModel):
    """Arc geometry is independent of its optionally stale angle readback."""
    def GetTypeN(self, h):
        return getattr(h, 'kind', 6) if h is not None and h.key in self.objects else 0

    def GetArc(self, h):
        if self.fault == 'stale_arc_getter' and hasattr(h, 'original_angles'):
            return h.original_angles
        return super().GetArc(h)

    def SetArc(self, h, start, sweep):
        h.original_angles = (h.start, h.sweep)
        super().SetArc(h, start, sweep)

    def HPerimN(self, h):
        self.calls.append('HPerimN')
        return 2*math.pi*h.radius*abs(h.sweep)/360

    def ConvertToNURBS(self, h, keep_orig):
        self.calls.append('ConvertToNURBS')
        assert keep_orig is True
        copied = copy.deepcopy(h)
        copied.key, copied.name = str(uuid.uuid4()), ''
        copied.kind = 11 if self.fault == 'conversion_returns_group' else 111
        self.objects[copied.key] = copied
        return copied

    def GetPointAndParameterOnNurbsCurveAtGivenLength(self, h, fraction):
        self.calls.append('GetPointAndParameterOnNurbsCurveAtGivenLength')
        assert h.kind == 111 and 0 <= fraction <= 1
        if self.fault == 'sample_ignores_fraction':
            fraction = 0
        # Complex rotations use only the model's actual current angles. The
        # fixture's analytic prediction is never fed to this injected host.
        vector = h.radius*cmath.exp(1j*math.radians(h.start))*cmath.exp(1j*math.radians(h.sweep)*fraction)
        return True, (h.center[0]+vector.real, h.center[1]+vector.imag, 0), -7+17*fraction, 0


class _ArcRepairGeometryModel(_ArcGeometryModel):
    """Measured-build adapter plus separately stored geometric arc state."""
    def GetVersionEx(self):
        return 32, 0, 0, 2, 882075

    def VWXBridgeRevision(self):
        return 1

    def SetArc(self, h, start, sweep):
        raise AssertionError('Measured build must bypass the original Python setter')

    def VWXBridgeSetArc(self, h, start, sweep):
        self.calls.append('VWXBridgeSetArc')
        assert type(start) is float and type(sweep) is float
        h.start, h.sweep = start, sweep
        if self.fault == 'lying_getter_rotates_geometry':
            h.reported_angles = (start, sweep)
            h.start += 15
        if self.fault == 'clobber_control':
            for other in self.objects.values():
                if other is not h and '_control-' in other.name:
                    other.start += 20
        if self.fault == 'rename_candidate':
            h.name = 'unexpected replacement identity'
        return 1

    def GetArc(self, h):
        return getattr(h, 'reported_angles', (h.start, h.sweep))


def _sender(model, requests):
    def send(request):
        requests.append(copy.deepcopy(request))
        command, params = request['command'], request['params']
        if command not in ('sdk_call', 'sdk_sequence'):
            raise AssertionError('Only typed SDK tools are permitted')
        denial = POLICY.check(command, params, sdk_catalog=CATALOG['functions'])
        if denial:
            raise AssertionError(denial)
        if command == 'sdk_sequence':
            return SEQUENCES.run(params, vs_module=model, catalog=CATALOG)
        return RUNTIME.invoke(params['name'], {'arguments': params['arguments']}, vs_module=model, catalog=CATALOG)
    return send


class SDKGeometryFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jobs = GEOMETRY.geometry_fixtures('offline')

    def job(self, family, label):
        return next(job for job in self.jobs if job['id'] == 'design:geometry_' + family + ':' + label)

    def test_all_concrete_calls_pass_independent_signatures_runtime_and_background_policy(self):
        captures, names = {}, set()
        for job in self.jobs:
            self.assertEqual(job['kind'], 'native')
            self.assertEqual(job['native_status'], 'pending_not_executed')
            self.assertTrue(job['assertions'])
            for item in job.get('calls', [job]):
                name = item['name']
                names.add(name)
                self.assertEqual(set(item['arguments']), set(INDEX[name]['args']), (job['id'], name))
                arguments = HOST._substitute(item['arguments'], captures)
                result = RUNTIME.validate(name, {'arguments': arguments}, catalog=CATALOG,
                                          invocation_context={'sequence': True},
                                          reference_validator=lambda value, _: isinstance(value, dict) and '$ref' in value)
                self.assertNotIn('error', result, (job['id'], result))
                context = CATALOG['functions'][name]['context']
                self.assertFalse(context['interactive'], name)
                self.assertFalse(context['quarantined'], name)
                self.assertFalse(context['unsupported_reason'], name)
            request = RUNNER.render_typed_job(job, captures)
            self.assertIsNone(POLICY.check(request['command'], request['params'], sdk_catalog=CATALOG['functions']))
            self.assertNotIn('code', request['params'])
            if 'capture' in job:
                self.assertNotIn(job['capture']['name'], captures)
                captures[job['capture']['name']] = HOST.FIXTURE_UUID
        self.assertGreaterEqual(len(self.jobs), 200)
        self.assertGreaterEqual(len(names), 45)
        self.assertFalse(names & {'UprString', 'DoMenuTextByName', 'SetPref', 'SetPrefReal', 'SetUnits', 'Layer',
                                  'SetSelect', 'SetDSelect', 'SelectAll', 'DeleteObjs', 'DelObject', 'Open', 'Close'})

    def test_every_family_is_independent_and_run_names_are_fresh(self):
        for family in GEOMETRY.FAMILIES:
            captures = {}
            first = GEOMETRY.geometry_fixtures('first', [family])
            second = GEOMETRY.geometry_fixtures('second', [family])
            for job in first:
                self.assertEqual(job['fixture_family'], family)
                HOST._substitute(job.get('calls', job.get('arguments')), captures)
                if 'capture' in job:
                    captures[job['capture']['name']] = HOST.FIXTURE_UUID
            def object_names(jobs):
                return [call['arguments']['name'] for job in jobs for call in job.get('calls', [job]) if call['name'] == 'SetName']
            self.assertTrue(object_names(first))
            self.assertTrue(set(object_names(first)).isdisjoint(object_names(second)))
            self.assertEqual(len(object_names(first)), len(set(object_names(first))))
        for families in ([], ['unknown'], ['geometry_lines', 'geometry_lines']):
            with self.assertRaises(ValueError):
                GEOMETRY.geometry_fixtures('valid', families)
        for run_id in ('', '../unsafe', "apostrophe'", 'a' * 81, None):
            with self.assertRaises(ValueError):
                GEOMETRY.geometry_fixtures(run_id)

    def test_every_creation_and_mutation_has_later_readback_and_never_reads_within_mutation_job(self):
        indices = {job['id']: index for index, job in enumerate(self.jobs)}
        self.assertEqual(len(indices), len(self.jobs), 'Duplicate evidence case IDs')
        verified = set()
        for job in self.jobs:
            for prior_id in job.get('verifies_jobs', []):
                self.assertEqual(job['phase'], 'readback')
                self.assertLess(indices[prior_id], indices[job['id']])
                self.assertIn(self.jobs[indices[prior_id]]['phase'], ('creation', 'mutation'))
                verified.add(prior_id)
            if job['phase'] in ('creation', 'mutation'):
                # UUID capture is permitted in a construction transaction;
                # geometric inspection waits for a separate invocation.
                for item in job.get('calls', [job]):
                    self.assertFalse(item['name'].startswith(('Get', 'NurbsGet')), item['name'])
                    self.assertNotIn(item['name'], ('HArea', 'HAreaN', 'HPerim', 'HPerimN', 'HLength', 'Centroid3D'))
        changed = {job['id'] for job in self.jobs if job['phase'] in ('creation', 'mutation')}
        self.assertEqual(changed - verified, set())

    def test_rectangle_numeric_oracles_from_coordinates_and_transform_determinants(self):
        for name in ('signed_rect', 'fractional_rect', 'thin_rect', 'far_rect'):
            create = self.job('rectangles', 'create_' + name)['calls'][0]['arguments']
            (left, top), (right, bottom) = create['p1'], create['p2']
            area, perimeter = (right-left)*(top-bottom), 2*((right-left)+(top-bottom))
            self.assertEqual(self.job('rectangles', name + '_HAreaN')['assertions'][0]['equals'], area)
            self.assertEqual(self.job('rectangles', name + '_HPerimN')['assertions'][0]['equals'], perimeter)
        anisotropic = self.job('rectangles', 'anisotropic_scale')['arguments']
        self.assertEqual(anisotropic['scaleX'] * anisotropic['scaleY'], 1)
        for label, area in (('initial', 600), ('translated', 600), ('rotated', 600), ('anisotropic', 600), ('uniform', 2400)):
            self.assertEqual(self.job('rectangles', label + '_HAreaN')['assertions'][0]['equals'], area)

    def test_circle_ellipse_rounded_rectangle_and_polygon_oracles_are_analytic(self):
        for key in ('unit_circle', 'offset_circle', 'ellipse'):
            box = self.job('ovals', 'create_' + key)['calls'][0]['arguments']
            a, b = (box['p2'][0]-box['p1'][0])/2, (box['p1'][1]-box['p2'][1])/2
            self.assertAlmostEqual(self.job('ovals', key + '_area')['assertions'][0]['equals'], math.pi*a*b)
        self.assertAlmostEqual(self.job('ovals', 'rounded_HAreaN')['assertions'][0]['equals'], 40*20-(4-math.pi)*2**2)
        for key in ('triangle_ccw', 'triangle_cw', 'concave_polygon'):
            points = [item['arguments']['p'] for item in self.job('polygons', 'create_' + key)['calls'] if item['name'] == 'AddPoint']
            area = abs(sum(p[0]*q[1]-p[1]*q[0] for p, q in zip(points, points[1:]+points[:1]))) / 2
            perimeter = sum(math.dist(p, q) for p, q in zip(points, points[1:]+points[:1]))
            label = 'concave' if key == 'concave_polygon' else key
            self.assertAlmostEqual(self.job('polygons', label + '_HAreaN')['assertions'][0]['equals'], area)
            self.assertAlmostEqual(self.job('polygons', label + '_HPerimN')['assertions'][0]['equals'], perimeter)

    def test_lines_have_length_and_orientation_oracles_that_distinguish_swapped_coordinates(self):
        for key in ('horizontal_line', 'vertical_line', 'reverse_line', 'fractional_line'):
            calls = self.job('lines', 'create_' + key)['calls']
            start, end = calls[0]['arguments']['p'], calls[1]['arguments']['p']
            self.assertEqual(self.job('lines', key + '_length')['assertions'][0]['equals'], math.dist(start, end))
        for label, result in (('reflected_start', [-10, 20]), ('reflected_end', [-40, 60]),
                              ('rotated_line_start', [-20, 10]), ('rotated_line_end', [-60, 40])):
            job = self.job('lines', label)
            self.assertTrue(HOST.evaluate_native(job, {'status': 'ok', 'function': job['name'], 'result': result})[0])
            self.assertFalse(HOST.evaluate_native(job, {'status': 'ok', 'function': job['name'], 'result': result[::-1]})[0])

    def test_asymmetric_3d_oracles_distinguish_dimension_axes_and_center_movement(self):
        for label, expected in (('extrude_distinct_dimensions', [20, 30, 10]),
                                 ('z_rotation_swaps_plan_dimensions', [30, 20, 10]),
                                 ('scaled_3d_dimensions', [15, 40, 30])):
            job = self.job('extrudes', label)
            self.assertEqual(job['assertions'][0]['equals'], expected)
            self.assertTrue(HOST.evaluate_native(job, {'status': 'ok', 'function': job['name'], 'result': expected})[0])
            self.assertFalse(HOST.evaluate_native(job, {'status': 'ok', 'function': job['name'], 'result': expected[::-1]})[0])
        centroid = self.job('extrudes', 'translated_mass_centroid')
        self.assertFalse(HOST.evaluate_native(centroid, {'status': 'ok', 'function': centroid['name'], 'result': [True, 315, 10, 0]})[0])

    def test_nurbs_indices_are_guarded_by_previous_piece_degree_and_point_count_assertions(self):
        jobs = GEOMETRY.geometry_fixtures('offline', ['geometry_nurbs'])
        ids = {job['id']: index for index, job in enumerate(jobs)}
        guard = ids['design:geometry_nurbs:linear_nurbs_control_count']
        for job in jobs:
            if job.get('name') in ('NurbsGetPt3D', 'NurbsSetPt3D', 'NurbsGetWeight', 'NurbsSetWeight'):
                self.assertGreater(ids[job['id']], guard)
                self.assertEqual(job['arguments']['index1'], 0)
                self.assertIn(job['arguments']['index2'], (0, 1))
        self.assertEqual(self.job('nurbs', 'linear_nurbs_control_count')['assertions'][0]['equals'], 2)
        self.assertEqual(self.job('nurbs', 'linear_nurbs_degree')['assertions'][0]['equals'], 1)
        self.assertEqual(self.job('nurbs', 'create_linear_nurbs')['calls'][0]['arguments']['keepOrig'], True)

    def test_harea_preserves_actual_compatibility_provenance_and_coordinate_units(self):
        jobs = GEOMETRY.geometry_fixtures('offline', ['geometry_harea'])
        checks = [job for job in jobs if job.get('name') == 'HArea']
        self.assertEqual(len(checks), 5)
        self.assertEqual([job['assertions'][0]['equals'] for job in checks], [1, 600, 0.5, 600, 2400])
        for job in checks:
            self.assertNotIn('execution_kind', job, 'Runtime provenance must determine native versus fallback')
            self.assertIn('compatibility_caution', job)
            response = {'status': 'ok', 'function': job['name'], 'result': job['assertions'][0]['equals'],
                        'compatibility': {'native_function': 'HArea', 'replacement_function': 'HAreaN',
                                          'reason': 'obsolete_native_returned_none'}}
            evidence = HOST.execution_evidence(job, response)
            self.assertEqual(evidence['execution_kind'], 'compatibility')
            self.assertEqual(evidence['function_executions'], [
                {'step': 0, 'function': 'HArea', 'execution_kind': 'compatibility'}])

    def _run_rectangle_model(self, model, family='geometry_rectangles'):
        plan = HOST.build_plan(DOCUMENT, run_id='model', include_contracts=False, include_native=False, include_document=False)
        plan['jobs'] = GEOMETRY.geometry_fixtures('model', [family])
        seen = []
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / 'geometry.jsonl'
            result = RUNNER.run_design_plan(_sender(model, seen), plan, journal,
                                            deployed_source_hashes=lambda: plan['source_sha256'])
            events = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
            before = len(seen)
            with self.assertRaises(FileExistsError):
                RUNNER.run_design_plan(_sender(model, seen), plan, journal,
                                       deployed_source_hashes=lambda: plan['source_sha256'])
            self.assertEqual(len(seen), before)
        return result, seen, events

    def test_arc_setter_void_result_does_not_prove_effect_and_failure_is_not_replayed(self):
        result, _, _ = self._run_rectangle_model(_ArcModel(), 'geometry_arcs')
        self.assertEqual(result['status'], 'passed', result)
        model = _ArcModel('ignore_set_arc')
        result, _, _ = self._run_rectangle_model(model, 'geometry_arcs')
        self.assertEqual(result['status'], 'failed')
        failed = result['records'][-1]
        self.assertEqual(failed['id'], 'design:geometry_arcs:changed_arc_angles')
        self.assertEqual(failed['verifies_jobs'], ['design:geometry_arcs:change_start_and_sweep'])
        self.assertEqual(model.calls.count('SetArc'), 1)

    def test_arc_characterization_collects_all_fresh_variants_without_claiming_effect(self):
        jobs = GEOMETRY.geometry_fixtures('probe', ['geometry_arc_characterization'])
        self.assertTrue(all(j['verification_dimension'] == 'characterization' and j['diagnostic_only'] for j in jobs))
        for fault in ('ignore_set_arc', 'setter_requires_reset'):
            model = _ArcModel(fault)
            result, _, _ = self._run_rectangle_model(model, 'geometry_arc_characterization')
            self.assertEqual(result['status'], 'passed', result)
            self.assertEqual(len(model.objects), 7)
            self.assertEqual(model.calls.count('SetArc'), 7)
            self.assertEqual(model.calls.count('ResetBBox'), 1)
            self.assertEqual(model.calls.count('ResetObject'), 1)
            readings = {r['id'].split(':')[-1]: r['result']['result'] for r in result['records'] if r['id'].endswith('_observed_angles')}
            self.assertEqual(readings['square_float_observed_angles'], [0, 90])
            expected = [90, 180] if fault == 'setter_requires_reset' else [0, 90]
            self.assertEqual(readings['square_reset_bbox_observed_angles'], expected)
            self.assertEqual(readings['square_reset_object_observed_angles'], expected)

    def test_arc_geometry_characterization_has_fresh_controls_and_type_gate_before_fraction_sampling(self):
        family = 'geometry_arc_geometry_characterization'
        jobs = GEOMETRY.geometry_fixtures('arc_geometry', [family])
        plan = HOST.build_plan(DOCUMENT, run_id='arc_geometry', include_contracts=False,
                               include_native=False, include_document=False)
        plan['jobs'] = jobs
        self.assertTrue(REGISTRY.validate_plan(plan))
        self.assertIn(family, GEOMETRY.CHARACTERIZATION_FAMILIES)
        self.assertTrue(all(j['verification_dimension'] == 'characterization' for j in jobs))
        self.assertEqual(sum(j.get('name') == 'SetArc' for j in jobs), 1)
        self.assertEqual(sum(j.get('name') == 'HPerimN' for j in jobs), 3)
        self.assertFalse(any(c['name'] == 'HLength' for j in jobs for c in j.get('calls', [j])))
        for role in ('quarter_control', 'target_control', 'setter_candidate'):
            gate_index = next(i for i, j in enumerate(jobs) if j['id'].endswith(':' + role + '_nurbs_type'))
            self.assertEqual(jobs[gate_index]['assertions'][0]['equals'], 111)
            samples = [(i, j) for i, j in enumerate(jobs) if j['id'].split(':')[-1].startswith(role + '_point_')]
            self.assertEqual([j['arguments']['inPercentOfLength'] for _, j in samples], [0, .5, 1])
            self.assertTrue(all(i > gate_index for i, _ in samples))
        conversion_calls = [c for j in jobs for c in j.get('calls', [j]) if c['name'] == 'ConvertToNURBS']
        self.assertEqual(len(conversion_calls), 3)
        self.assertTrue(all(c['arguments']['keepOrig'] is True for c in conversion_calls))
        names = [c['arguments']['name'] for j in GEOMETRY.geometry_fixtures('x'*80, [family])
                 for c in j.get('calls', [j]) if c['name'] == 'SetName']
        self.assertEqual(len(names), 6)
        self.assertEqual(len(set(names)), 6)
        self.assertTrue(all(len(name) <= 60 and name.isascii() for name in names))

    def test_arc_geometry_predictions_use_circle_geometry_not_getarc_or_control_responses(self):
        jobs = GEOMETRY.geometry_fixtures('prediction', ['geometry_arc_geometry_characterization'])
        points = {j['id'].split(':')[-1]: j['measurement_context'] for j in jobs
                  if 'length_fraction' in j.get('measurement_context', {})}
        quarter = ([330, -260, 0], [320+math.sqrt(50), -260+math.sqrt(50), 0], [320, -250, 0])
        target = ([320, -250, 0], [310, -260, 0], [320, -270, 0])
        for role, expected in (('quarter_control', quarter), ('target_control', target), ('setter_candidate', target)):
            for index, point in enumerate(expected):
                context = points[role + '_point_' + str(index)]
                for actual, coordinate in zip(context['analytic_intended_point'], point):
                    self.assertAlmostEqual(actual, coordinate)
                if role == 'setter_candidate':
                    for actual, coordinate in zip(context['analytic_unchanged_point'], quarter[index]):
                        self.assertAlmostEqual(actual, coordinate)

    def test_arc_geometry_observations_distinguish_noop_setter_from_stale_getter_without_semantic_credit(self):
        family = 'geometry_arc_geometry_characterization'
        for fault in (None, 'ignore_set_arc', 'stale_arc_getter'):
            with self.subTest(fault=fault):
                model = _ArcGeometryModel(fault)
                result, _, _ = self._run_rectangle_model(model, family)
                self.assertEqual(result['status'], 'passed', result)
                self.assertEqual(result['native_functions_passed'], [])
                self.assertEqual(result['functions_all_planned_cases_passed'], [])
                self.assertEqual(len(model.objects), 6, 'All original arcs survive conversion')
                self.assertEqual(model.calls.count('SetArc'), 1)
                rows = {r['id'].split(':')[-1]: r['result']['result'] for r in result['records']
                        if 'result' in r['result']}
                angles = rows['setter_candidate_observed_angles']
                self.assertEqual(angles, [0, 90] if fault else [90, 180])
                source = 'quarter_control' if fault == 'ignore_set_arc' else 'target_control'
                for index in range(3):
                    candidate = rows['setter_candidate_point_' + str(index)][1]
                    reference = rows[source + '_point_' + str(index)][1]
                    for coordinate, independent_control in zip(candidate, reference):
                        self.assertAlmostEqual(coordinate, independent_control)
                self.assertEqual(rows['setter_candidate_perimeter'], rows[source + '_perimeter'])

    def test_arc_geometry_type_guard_blocks_group_and_broken_sampler_remains_visible(self):
        family = 'geometry_arc_geometry_characterization'
        model = _ArcGeometryModel('conversion_returns_group')
        result, _, _ = self._run_rectangle_model(model, family)
        self.assertEqual(result['status'], 'failed', result)
        self.assertTrue(result['records'][-1]['id'].endswith(':quarter_control_nurbs_type'))
        self.assertNotIn('GetPointAndParameterOnNurbsCurveAtGivenLength', model.calls)
        model = _ArcGeometryModel('sample_ignores_fraction')
        result, _, _ = self._run_rectangle_model(model, family)
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(result['native_functions_passed'], [])
        rows = {r['id'].split(':')[-1]: r['result']['result'] for r in result['records']
                if 'result' in r['result']}
        self.assertEqual(rows['quarter_control_point_0'][1], rows['quarter_control_point_1'][1])
        self.assertNotEqual(rows['quarter_control_point_1'][1], [320+math.sqrt(50), -260+math.sqrt(50), 0])
        # The broken sample is retained as an observation, never silently
        # promoted to a semantic pass merely because both objects share it.

    def test_arc_repair_family_is_semantic_pending_with_separate_guarded_curve_reads(self):
        family = 'geometry_arc_repair_geometry'
        jobs = GEOMETRY.geometry_fixtures('arc_repair', [family])
        plan = HOST.build_plan(DOCUMENT, run_id='arc_repair', include_contracts=False,
                               include_native=False, include_document=False)
        plan['jobs'] = jobs
        self.assertTrue(REGISTRY.validate_plan(plan))
        self.assertNotIn(family, GEOMETRY.CHARACTERIZATION_FAMILIES)
        self.assertFalse(any(job.get('diagnostic_only') for job in jobs))
        self.assertTrue(all(job['native_status'] == 'pending_not_executed' for job in jobs))
        setters = [j for j in jobs if j.get('name') == 'SetArc']
        self.assertEqual([(j['arguments']['startAngle'], j['arguments']['arcAngle']) for j in setters],
                         [(90, 180), (300, 120), (30, 15), (45, 270)])
        self.assertTrue(all('compatibility_caution' in j and 'execution_kind' not in j for j in setters))
        calls = [c for j in jobs for c in j.get('calls', [j])]
        self.assertEqual(sum(c['name'] == 'ConvertToNURBS' for c in calls), 8)
        self.assertTrue(all(c['arguments']['keepOrig'] is True for c in calls if c['name'] == 'ConvertToNURBS'))
        self.assertFalse(any(c['name'] in ('HLength', 'ResetObject', 'ResetBBox') for c in calls))
        for label in ('semicircle', 'cross_zero', 'small_sweep', 'major_sweep'):
            for role, fractions in (('candidate', [0, .25, .5, .75, 1]), ('control', [0, .5, 1])):
                key = 'arc_repair_' + label + '_' + role
                gate = next(i for i, j in enumerate(jobs) if j['id'].endswith(':' + key + '_nurbs_type'))
                self.assertEqual(jobs[gate]['assertions'][0]['equals'], 111)
                samples = [(i, j) for i, j in enumerate(jobs) if j['id'].split(':')[-1].startswith(key + '_point_')]
                self.assertEqual([j['arguments']['inPercentOfLength'] for _, j in samples], fractions)
                self.assertTrue(all(i > gate for i, _ in samples))
                for _, sample in samples:
                    point_assertion = sample['assertions'][1]
                    self.assertEqual(point_assertion['path'], ['result', 1])
                    self.assertEqual(point_assertion['abs_tol'], 1e-6)
                    self.assertEqual(point_assertion['rel_tol'], 0)
                    self.assertIn('design:' + family + ':' + label + '_change_angles', sample['verifies_jobs'])
        long_jobs = GEOMETRY.geometry_fixtures('x'*80, [family])
        names = [c['arguments']['name'] for j in long_jobs for c in j.get('calls', [j]) if c['name'] == 'SetName']
        self.assertEqual(len(names), 16)
        self.assertEqual(len(set(names)), 16)
        self.assertTrue(all(len(name) <= 60 and name.isascii() for name in names))

    def test_arc_repair_expected_points_use_independent_cardinal_and_triangle_geometry(self):
        jobs = GEOMETRY.geometry_fixtures('analytic', ['geometry_arc_repair_geometry'])
        by_label = {j['id'].split(':')[-1]: j for j in jobs}
        half = [[480, -250, 0], [480-math.sqrt(50), -260+math.sqrt(50), 0],
                [470, -260, 0], [480-math.sqrt(50), -260-math.sqrt(50), 0], [480, -270, 0]]
        crossing = [[546, -260-6*math.sqrt(3), 0], [540+6*math.sqrt(3), -266, 0],
                    [552, -260, 0], [540+6*math.sqrt(3), -254, 0], [546, -260+6*math.sqrt(3), 0]]
        for label, expected_points in (('semicircle', half), ('cross_zero', crossing)):
            for i, point in enumerate(expected_points):
                actual = by_label['arc_repair_' + label + '_candidate_point_' + str(i)]['assertions'][1]['equals']
                for value, expected in zip(actual, point):
                    self.assertAlmostEqual(value, expected, places=11)
        for label, perimeter in (('semicircle', 10*math.pi), ('cross_zero', 8*math.pi),
                                 ('small_sweep', 2*math.pi/3), ('major_sweep', 13.5*math.pi)):
            expected = by_label['arc_repair_' + label + '_candidate_open_length']['assertions'][0]['equals']
            self.assertAlmostEqual(expected, perimeter, places=12)

    def test_arc_repair_actual_adapter_preserves_compatibility_and_all_original_objects(self):
        model = _ArcRepairGeometryModel()
        result, requests, _ = self._run_rectangle_model(model, 'geometry_arc_repair_geometry')
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(model.calls.count('VWXBridgeSetArc'), 4)
        self.assertNotIn('SetArc', result['native_functions_passed'])
        self.assertIn('SetArc', result['compatibility_functions_passed'])
        self.assertEqual(len(model.objects), 16)
        self.assertEqual(model.calls.count('ConvertToNURBS'), 8)
        for obj in model.objects.values():
            if '_control-' in obj.name:
                self.assertEqual((obj.start, obj.sweep), (0, 90))
        for request in requests:
            if request['command'] == 'sdk_call' and request['params']['name'] == 'SetArc':
                identifier = request['params']['arguments']['h']
                self.assertIn(identifier, model.objects)
                same_object = [r for r in requests if r['command'] == 'sdk_call'
                               and r['params']['name'] == 'GetName' and r['params']['arguments']['h'] == identifier]
                self.assertGreaterEqual(len(same_object), 3)

    def test_arc_repair_lying_angle_getter_and_right_length_cannot_hide_wrong_curve(self):
        model = _ArcRepairGeometryModel('lying_getter_rotates_geometry')
        result, _, _ = self._run_rectangle_model(model, 'geometry_arc_repair_geometry')
        self.assertEqual(result['status'], 'failed')
        failure = result['records'][-1]
        self.assertTrue(failure['id'].endswith(':arc_repair_semicircle_candidate_point_0'), failure)
        self.assertIn('design:geometry_arc_repair_geometry:semicircle_change_angles', failure['verifies_jobs'])
        self.assertEqual(model.calls.count('VWXBridgeSetArc'), 1)
        passed_ids = [r['id'] for r in result['records'] if r['passed']]
        self.assertIn('design:geometry_arc_repair_geometry:arc_repair_semicircle_candidate_angles', passed_ids)
        self.assertIn('design:geometry_arc_repair_geometry:arc_repair_semicircle_candidate_open_length', passed_ids)

    def test_arc_repair_detects_unchanged_fraction_sampler_and_accidental_control_changes(self):
        for fault, suffix in (('sample_ignores_fraction', 'semicircle_candidate_point_1'),
                              ('clobber_control', 'semicircle_control_angles'),
                              ('rename_candidate', 'semicircle_candidate_name_preserved')):
            with self.subTest(fault=fault):
                model = _ArcRepairGeometryModel(fault)
                result, _, _ = self._run_rectangle_model(model, 'geometry_arc_repair_geometry')
                self.assertEqual(result['status'], 'failed')
                failure = result['records'][-1]
                self.assertTrue(failure['id'].endswith(':arc_repair_' + suffix), failure)
                self.assertIn('design:geometry_arc_repair_geometry:semicircle_change_angles', failure['verifies_jobs'])
                self.assertEqual(model.calls.count('VWXBridgeSetArc'), 1)

    def test_arc_repair_rejects_group_conversion_before_curve_specific_native_reads(self):
        model = _ArcRepairGeometryModel('conversion_returns_group')
        result, _, _ = self._run_rectangle_model(model, 'geometry_arc_repair_geometry')
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['records'][-1]['id'].endswith(':arc_repair_semicircle_candidate_nurbs_type'))
        self.assertNotIn('GetPointAndParameterOnNurbsCurveAtGivenLength', model.calls)

    def test_independent_rectangle_model_runs_actual_adapters_sequences_and_typed_runner(self):
        model = _RectangleModel()
        result, seen, events = self._run_rectangle_model(model)
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(len(model.objects), 5)
        self.assertEqual(len(seen), 2 * len(GEOMETRY.geometry_fixtures('model', ['geometry_rectangles'])))
        self.assertEqual(sum(e['event'] == 'intent' for e in events), len(seen))
        self.assertEqual(model.calls.count('HMove'), 1)
        self.assertEqual(model.calls.count('HRotate'), 2)
        self.assertEqual(model.calls.count('HScale2D'), 3)

    def test_noop_translation_and_wrong_scale_fail_semantic_reads_and_never_replay_mutations(self):
        for fault, expected_failure, mutator in (
                ('ignore_translation', 'translated_center', 'HMove'),
                ('uniform_instead_of_anisotropic', 'anisotropic_HAreaN', 'HScale2D')):
            with self.subTest(fault=fault):
                model = _RectangleModel(fault)
                result, seen, events = self._run_rectangle_model(model)
                self.assertEqual(result['status'], 'failed', result)
                self.assertEqual(result['records'][-1]['id'], 'design:geometry_rectangles:' + expected_failure)
                self.assertFalse(result['records'][-1]['passed'])
                self.assertEqual(model.calls.count(mutator), 1)
                self.assertLess(len(seen), 2 * len(GEOMETRY.geometry_fixtures('model', ['geometry_rectangles'])))
                self.assertEqual(sum(e['event'] == 'intent' for e in events), len(seen))


if __name__ == '__main__':
    unittest.main()
