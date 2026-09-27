"""Offline analytic fixture checks; these do not establish native SDK behavior."""
import copy
import importlib.util
import itertools
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
DOCUMENT = r'C:\SDK-tests\VWX-MCP-SDK-TEST-modeling-offline.vwx'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODELING = load('sdk_modeling_fixture_tests', ROOT / 'tools/sdk_modeling_fixtures.py')
HOST = MODELING.DESIGN.HOST
REGISTRY = load('sdk_modeling_registry_tests', ROOT / 'tools/sdk_regression_suite.py')
RUNNER = load('sdk_modeling_runner_tests', ROOT / 'tools/sdk_design_runner.py')
POLICY = load('sdk_modeling_policy_tests', ROOT / 'mcp-server/background_policy.py')
CATALOG = json.loads((ROOT / 'vwx-plugin/sdk_catalog.json').read_text(encoding='utf-8'))
INDEX = json.loads((ROOT / 'vwx-plugin/vs_index.json').read_text(encoding='utf-8'))
RUNTIME = HOST._load_runtime(ROOT)
with patch.dict(sys.modules, {'sdk_runtime': RUNTIME}):
    SEQUENCES = load('sdk_modeling_sequence_tests', ROOT / 'vwx-plugin/sdk_sequences.py')


def _plan(run_id, families):
    plan = HOST.build_plan(DOCUMENT, run_id=run_id, include_contracts=False,
                           include_native=False, include_document=False)
    plan['jobs'] = MODELING.modeling_fixtures(run_id, families)
    return plan


def _cells(first, second, operation):
    """Independent interval partition oracle for the volume of two boxes.

    Subdivide at every boundary and classify each open cell by its midpoint;
    no fixture's expected dimensions, volume, or centroid enter this model.
    """
    intervals = []
    for axis in range(3):
        values = sorted(set(first[axis] + second[axis]))
        intervals.append(list(zip(values, values[1:])))
    cells = []
    for cell in itertools.product(*intervals):
        point = [(a+b)/2 for a, b in cell]
        inside_first = all(a < p < b for (a, b), p in zip(first, point))
        inside_second = all(a < p < b for (a, b), p in zip(second, point))
        if operation(inside_first, inside_second):
            cells.append(cell)
    return cells


class _GeometryModel:
    """Independent polygon vertices and axis-aligned volume cells.

    This implements only the valid domains selected by these offline tests.
    It cannot validate the Vectorworks geometry kernel or object lifecycle.
    """
    def __init__(self, fault=None, units_per_mm=1/25.4):
        self.fault, self.objects, self.last, self.calls = fault, {}, None, []
        self.units_per_mm = units_per_mm
        self.layer = self._new(kind=31)

    def _new(self, **values):
        h = SimpleNamespace(key=str(uuid.uuid4()), name='', **values)
        self.objects[h.key] = h
        self.last = h
        return h

    def GetVersion(self):
        return (32, 0, 0, 2)

    def GetFPathName(self):
        return DOCUMENT

    def GetObjectUuid(self, h):
        return h.key

    def GetObjectByUuid(self, key):
        return self.objects.get(key)

    def GetTypeN(self, h):
        return h.kind if h is not None and h.key in self.objects else 0

    def GetParent(self, h):
        return self.layer

    def LNewObj(self):
        return self.last

    def SetName(self, h, name):
        self.calls.append('SetName')
        h.name = name

    def GetName(self, h):
        return h.name

    @staticmethod
    def _vertices(p1, p2):
        x1, y1 = p1
        x2, y2 = p2
        return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]

    def Rect(self, p1, p2):
        self.calls.append('Rect')
        self._new(kind=3, vertices=self._vertices(p1, p2))

    def ValidNumStr(self, text):
        if not text.endswith('mm'):
            raise AssertionError('Only explicit millimetre fixtures are reviewed')
        factor = 1 if self.fault == 'ignore_unit_suffix' else self.units_per_mm
        return True, float(text[:-2])*factor

    def BeginPoly(self):
        self.pending_points = []

    def AddPoint(self, point):
        self.pending_points.append(list(point))

    def EndPoly(self):
        self._new(kind=5, vertices=self.pending_points)
        del self.pending_points

    def SetPolyClosed(self, h, closed):
        assert closed is True

    def GetBBox(self, h):
        xs, ys = zip(*h.vertices)
        return ((min(xs), max(ys)), (max(xs), min(ys)))

    def SetBBox(self, h, p1, p2):
        self.calls.append('SetBBox')
        if self.fault != 'ignore_bbox':
            h.vertices = self._vertices(p1, p2)

    def HWidth(self, h):
        return max(p[0] for p in h.vertices) - min(p[0] for p in h.vertices)

    def HHeight(self, h):
        return max(p[1] for p in h.vertices) - min(p[1] for p in h.vertices)

    def HCenter(self, h):
        p1, p2 = self.GetBBox(h)
        return tuple((a+b)/2 for a, b in zip(p1, p2))

    def _resize(self, h, axis, length):
        low = min(p[axis] for p in h.vertices)
        old_length = max(p[axis] for p in h.vertices) - low
        for point in h.vertices:
            point[axis] = low + (point[axis]-low) * length/old_length

    def SetWidth(self, h, width):
        self.calls.append('SetWidth')
        self._resize(h, 1 if self.fault == 'width_changes_height' else 0, width)

    def SetHeight(self, h, height):
        self.calls.append('SetHeight')
        if self.fault != 'ignore_height':
            self._resize(h, 1, height)

    def HAreaN(self, h):
        points = h.vertices
        return abs(sum(p[0]*q[1]-p[1]*q[0] for p, q in zip(points, points[1:]+points[:1])))/2

    def HPerimN(self, h):
        points = h.vertices
        return sum(math.dist(p, q) for p, q in zip(points, points[1:]+points[:1]))

    def Centroid(self, h):
        # General shoelace centroid, independent of the fixture's rectangle
        # center calculation and of the model's min/max dimension queries.
        points = h.vertices
        pairs = list(zip(points, points[1:]+points[:1]))
        twice_area = sum(p[0]*q[1]-p[1]*q[0] for p, q in pairs)
        coordinates = tuple(sum((p[axis]+q[axis])*(p[0]*q[1]-p[1]*q[0])
                                for p, q in pairs)/(3*twice_area) for axis in range(2))
        if self.fault == 'centroid_bounds_proxy':
            coordinates = self.HCenter(h)
        if self.fault != 'centroid_drawing_units':
            coordinates = tuple(value/self.units_per_mm for value in coordinates)
        return (True,) + coordinates

    def HMove(self, h, dx, dy):
        self.calls.append('HMove')
        h.vertices = [[x+dx, y+dy] for x, y in h.vertices]

    def _copy(self, h, operation):
        self.calls.append(operation)
        if self.fault == 'alias_' + operation:
            return h
        return self._new(kind=h.kind, vertices=copy.deepcopy(h.vertices))

    def CreateDuplicateObject(self, h, parent):
        if parent is not self.layer:
            raise AssertionError('Only the captured source parent is permitted')
        return self._copy(h, 'CreateDuplicateObject')

    def CreateDuplicateObjN(self, h, parent, maintain_height):
        if parent is not self.layer or type(maintain_height) is not bool:
            raise AssertionError('Invalid reviewed duplicate contract')
        return self._copy(h, 'CreateDuplicateObjN')

    def MakePolygon(self, h):
        result = self._copy(h, 'MakePolygon')
        result.kind = h.kind if self.fault == 'wrong_type_MakePolygon' else 5
        return result

    def MakePolyline(self, h):
        result = self._copy(h, 'MakePolyline')
        result.kind = h.kind if self.fault == 'wrong_type_MakePolyline' else 21
        return result

    def ConvertToPolyline(self, h):
        result = self._copy(h, 'ConvertToPolyline')
        del self.objects[h.key]
        return result

    def HExtrude(self, h, bottom, top):
        self.calls.append('HExtrude')
        (left, high), (right, low) = self.GetBBox(h)
        bounds = ((left, right), (low, high), (bottom, top))
        result = self._new(kind=24, cells=[bounds])
        del self.objects[h.key]
        return result

    def Get3DInfo(self, h):
        widths = [max(cell[axis][1] for cell in h.cells)-min(cell[axis][0] for cell in h.cells)
                  for axis in range(3)]
        return widths[1], widths[0], widths[2]

    def Centroid3D(self, h):
        volumes = [math.prod(b-a for a, b in cell) for cell in h.cells]
        return (True,) + tuple(sum(v*(cell[axis][0]+cell[axis][1])/2 for v, cell in zip(volumes, h.cells))
                                  /sum(volumes) for axis in range(3))

    def _boolean(self, a, b, api, operation):
        self.calls.append(api)
        if self.fault == 'union_as_intersection' and api == 'AddSolid':
            operation = lambda x, y: x and y
        if self.fault == 'subtract_reversed' and api == 'SubtractSolid':
            operation = lambda x, y: y and not x
        result = self._new(kind=84, cells=_cells(a.cells[0], b.cells[0], operation))
        # Make use-after-conversion/input-consumption mistakes fail at the
        # real UUID resolver rather than leave permissive mock handles alive.
        del self.objects[a.key]
        del self.objects[b.key]
        return 0, result

    def AddSolid(self, a, b):
        return self._boolean(a, b, 'AddSolid', lambda x, y: x or y)

    def IntersectSolid(self, a, b):
        return self._boolean(a, b, 'IntersectSolid', lambda x, y: x and y)

    def SubtractSolid(self, a, b):
        return self._boolean(a, b, 'SubtractSolid', lambda x, y: x and not y)


class _OrientedModel(_GeometryModel):
    """Rotate construction-box corners, then independently measure extrema.

    The optional contour substitution preserves the historical wrong contract
    as an explicit fault. This model never reads fixture span expectations.
    """
    def _oriented(self, api, origin, direction, width, height, diameters=None):
        self.calls.append(api)
        angle = math.atan2(direction[1], direction[0])
        if self.fault == 'ignore_direction_' + api:
            angle = 0
        cosine, sine = math.cos(angle), math.sin(angle)
        if api == 'RectangleN':
            points = self._vertices((-width/2, height/2), (width/2, -height/2))
            area, kind = width*height, 3
        elif api == 'OvalN':
            # Stationary parameters of the rotated parametric ellipse, plus
            # their antipodes, give all four extrema without a span formula.
            parameters = (math.atan2(-height*sine, width*cosine),
                          math.atan2(height*cosine, width*sine))
            points = [(width/2*math.cos(t+opposite), height/2*math.sin(t+opposite))
                      for t in parameters for opposite in (0, math.pi)]
            area, kind = math.pi*width*height/4, 4
        else:
            assert diameters[0] == diameters[1]
            radius = diameters[0]/2
            points = []
            for quadrant, signs in enumerate(((1, 1), (-1, 1), (-1, -1), (1, -1))):
                start, end = quadrant*math.pi/2, (quadrant+1)*math.pi/2
                parameters = [start, end]
                parameters.extend(t for axis in range(4)
                                  if start <= (t := (axis*math.pi/2-angle) % (2*math.pi)) <= end)
                cx, cy = signs[0]*(width/2-radius), signs[1]*(height/2-radius)
                points.extend((cx+radius*math.cos(t), cy+radius*math.sin(t)) for t in parameters)
            area, kind = width*height - (4-math.pi)*radius**2, 13
        if self.fault != 'tight_contour_bounds':
            points = self._vertices((-width/2, height/2), (width/2, -height/2))
        vertices = [[origin[0]+x*cosine-y*sine, origin[1]+x*sine+y*cosine] for x, y in points]
        if self.fault == 'different_origin_convention':
            vertices = [[x+123.25, y-16.75] for x, y in vertices]
        self._new(kind=kind, vertices=vertices, area=area, diameters=diameters)

    def RectangleN(self, origin, direction, width, height):
        self._oriented('RectangleN', origin, direction, width, height)

    def OvalN(self, origin, direction, width, height):
        self._oriented('OvalN', origin, direction, width, height)

    def RRectangleN(self, origin, direction, width, height, x_diameter, y_diameter):
        self._oriented('RRectangleN', origin, direction, width, height, (x_diameter, y_diameter))

    def HAreaN(self, h):
        return h.area

    def GetRRDiam(self, h):
        return h.diameters

    def GetBBox(self, h):
        self.calls.append('GetBBox')
        return super().GetBBox(h)


class _NurbsModel(_GeometryModel):
    """A degree-one curve with a deliberately non-unit knot domain.

    Parameter results are computed from projection/interpolation, not copied
    from planned assertions. This exercises numeric captures through the
    runtime and runner, independently of UUID captures for native handles.
    """
    domain = (-3.0, 7.0)

    def MoveTo(self, point):
        self.cursor = tuple(point)

    def LineTo(self, point):
        self._new(kind=2, endpoints=[self.cursor + (0,), tuple(point) + (0,)])

    def ConvertToNURBS(self, h, keep_orig):
        self.calls.append('ConvertToNURBS')
        if keep_orig is not True:
            raise AssertionError('This family must preserve its source line')
        return self._new(kind=111, endpoints=copy.deepcopy(h.endpoints))

    def NurbsCurveGetNumPieces(self, h):
        return 1

    def NurbsDegree(self, h, index):
        assert index == 0
        return 1

    def NurbsGetNumPts(self, h, index):
        assert index == 0
        return len(h.endpoints)

    def NurbsNumKnots(self, h, index):
        assert index == 0
        return 4

    def NurbsKnot(self, h, index, knot):
        assert index == 0 and 0 <= knot < 4
        return self.domain[knot // 2]

    def NurbsCurveEvalPt(self, h, index, parameter):
        assert index == 0 and self.domain[0] <= parameter <= self.domain[1]
        self.calls.append('NurbsCurveEvalPt')
        if self.fault == 'ignore_parameter':
            parameter = self.domain[0]
        fraction = (parameter-self.domain[0])/(self.domain[1]-self.domain[0])
        return tuple(a+(b-a)*fraction for a, b in zip(*h.endpoints))

    def GetPointAndParameterOnNurbsCurveAtGivenLength(self, h, fraction):
        assert 0 <= fraction <= 1
        self.calls.append('GetPointAndParameterOnNurbsCurveAtGivenLength')
        point = tuple(a+(b-a)*fraction for a, b in zip(*h.endpoints))
        parameter = self.domain[0] + fraction*(self.domain[1]-self.domain[0])
        if self.fault == 'wrong_sample_parameter':
            parameter = fraction
        return True, point, parameter, 0

    @staticmethod
    def _project(h, point):
        a, b = h.endpoints
        direction = [end-start for start, end in zip(a, b)]
        return sum((p-start)*delta for p, start, delta in zip(point, a, direction))/sum(d*d for d in direction)

    def GetParameterOnNurbsCurve(self, h, point):
        fraction = self._project(h, point)
        return True, self.domain[0]+fraction*(self.domain[1]-self.domain[0]), 0

    def GetNurbsObjectDistanceFromPoint(self, h, point):
        point = tuple(point)+(0,)
        fraction = min(1, max(0, self._project(h, point)))
        nearest = tuple(a+(b-a)*fraction for a, b in zip(*h.endpoints))
        distance = math.dist(point, nearest)
        if self.fault == 'signed_internal_distance':
            distance *= -25.4
        return True, distance


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


class SDKModelingFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jobs = MODELING.modeling_fixtures('offline')

    def job(self, family, label):
        return next(job for job in self.jobs if job['id'] == 'design:modeling_' + family + ':' + label)

    def test_every_call_has_independent_exact_signature_and_all_captures_are_typed(self):
        REGISTRY.validate_plan(_plan('offline', None))
        names = set()
        for job in self.jobs:
            self.assertEqual(job['native_status'], 'pending_not_executed')
            self.assertNotIn('execution_kind', job)
            self.assertNotIn('code', job)
            for item in job.get('calls', [job]):
                name = item['name']
                names.add(name)
                self.assertEqual(set(item['arguments']), set(INDEX[name]['args']))
                context = CATALOG['functions'][name]['context']
                self.assertFalse(context['interactive'], name)
                self.assertFalse(context['quarantined'], name)
                self.assertFalse(context['unsupported_reason'], name)
        self.assertGreaterEqual(len(self.jobs), 250)
        self.assertGreaterEqual(len(names), 40)
        self.assertFalse(names & {'Layer', 'SetSelect', 'SetDSelect', 'SelectAll', 'SetPref', 'SetPrefReal',
                                 'SetUnits', 'DoMenuTextByName', 'CombineIntoSurface', 'SetArc', 'UprString',
                                 'SetResourceTags', 'Open', 'Close', 'DelObject', 'DeleteObjs'})

    def test_each_family_is_self_contained_with_fresh_unique_object_names(self):
        def names(jobs):
            return [item['arguments']['name'] for job in jobs for item in job.get('calls', [job])
                    if item['name'] == 'SetName']
        for family in MODELING.FAMILIES:
            with self.subTest(family=family):
                first = _plan('first', [family])
                REGISTRY.validate_plan(first)
                second = MODELING.modeling_fixtures('second', [family])
                self.assertTrue(all(j['fixture_family'] == family for j in first['jobs']))
                self.assertTrue(names(first['jobs']))
                self.assertEqual(len(names(first['jobs'])), len(set(names(first['jobs']))))
                self.assertTrue(set(names(first['jobs'])).isdisjoint(names(second)))
        for selected in ([], ['unknown'], [MODELING.FAMILIES[0]] * 2):
            with self.assertRaises(ValueError):
                MODELING.modeling_fixtures('valid', selected)
        for run_id in ('', '../bad', 'a' * 81, None, 42):
            with self.assertRaises(ValueError):
                MODELING.modeling_fixtures(run_id)

    def test_every_mutation_has_later_semantic_readback_with_no_inspection_inside_creation(self):
        indices = {job['id']: index for index, job in enumerate(self.jobs)}
        self.assertEqual(len(indices), len(self.jobs))
        verified = set()
        for job in self.jobs:
            for prior_id in job.get('verifies_jobs', []):
                self.assertEqual(job['phase'], 'readback')
                self.assertLess(indices[prior_id], indices[job['id']])
                self.assertEqual(self.jobs[indices[prior_id]]['fixture_family'], job['fixture_family'])
                self.assertIn(self.jobs[indices[prior_id]]['phase'], ('creation', 'mutation'))
                verified.add(prior_id)
            if job['phase'] in ('creation', 'mutation'):
                for item in job.get('calls', [job]):
                    self.assertFalse(item['name'].startswith(('Get', 'NurbsGet')))
                    self.assertNotIn(item['name'], ('HAreaN', 'HPerimN', 'Centroid', 'Centroid3D', 'Products3D'))
        changed = {job['id'] for job in self.jobs if job['phase'] in ('creation', 'mutation')}
        self.assertEqual(changed - verified, set())

    def test_long_run_ids_have_unique_bounded_names_and_consistent_identity_readbacks(self):
        def names(jobs):
            return [item['arguments']['name'] for job in jobs for item in job.get('calls', [job])
                    if item['name'] == 'SetName']
        first_id, second_id = 'a'*79 + '1', 'a'*79 + '2'
        first, second = MODELING.modeling_fixtures(first_id), MODELING.modeling_fixtures(second_id)
        self.assertEqual(first, MODELING.modeling_fixtures(first_id))
        self.assertEqual(len(names(first)), len(set(names(first))))
        self.assertTrue(set(names(first)).isdisjoint(names(second)))
        for name in names(first) + names(second):
            self.assertTrue(name.isascii())
            self.assertLessEqual(len(name), 60)
        for family in ('modeling_bounds', 'modeling_duplicates', 'modeling_planar_conversion',
                       'modeling_csg', 'modeling_centroid_units', 'modeling_nurbs_sampling',
                       'modeling_nurbs_distance'):
            plan = _plan(first_id, [family])
            REGISTRY.validate_plan(plan)
            model_class = _NurbsModel if 'nurbs' in family else _GeometryModel
            with tempfile.TemporaryDirectory() as directory:
                result = RUNNER.run_design_plan(_sender(model_class(), []), plan, Path(directory)/'long-name.jsonl',
                                                deployed_source_hashes=lambda: plan['source_sha256'])
            self.assertEqual(result['status'], 'passed', (family, result))

    def test_unresolved_distance_and_characterizations_do_not_claim_semantic_native_results(self):
        self.assertEqual(set(MODELING.DIAGNOSTIC_FAMILIES), {'modeling_nurbs_distance', *MODELING.CHARACTERIZATION_FAMILIES})
        for job in self.jobs:
            self.assertEqual(job.get('diagnostic_only', False), job['fixture_family'] in MODELING.DIAGNOSTIC_FAMILIES)
            if job.get('diagnostic_only'):
                self.assertTrue(job['known_issue'])
            if job['fixture_family'] in MODELING.CHARACTERIZATION_FAMILIES:
                self.assertEqual(job['verification_dimension'], 'characterization')
        _, result, _ = self._run_model('modeling_nurbs_sampling', 'signed_internal_distance', _NurbsModel)
        self.assertEqual(result['status'], 'passed')
        _, result, _ = self._run_model('modeling_nurbs_distance', 'signed_internal_distance', _NurbsModel)
        self.assertEqual(result['status'], 'failed')
        failed = result['records'][-1]
        self.assertEqual(failed['result']['result'], [True, -127.0])
        self.assertEqual(failed['assertions'][0]['expected']['equals'], [True, 5])

    def test_documented_mm_centroid_contract_is_independent_of_drawing_units(self):
        jobs = MODELING.modeling_fixtures('units', ['modeling_centroid_units'])
        self.assertTrue(all(not job.get('diagnostic_only') for job in jobs))
        self.assertTrue(all(job['arguments']['str'].endswith('mm') for job in jobs if job.get('name') == 'ValidNumStr'))
        for units_per_mm in (1/25.4, 1, 0.1, 0.001):
            with self.subTest(units_per_mm=units_per_mm):
                model = _GeometryModel(units_per_mm=units_per_mm)
                _, result, _ = self._run_model('modeling_centroid_units', model_class=lambda _: model)
                self.assertEqual(result['status'], 'passed', result)
        for fault, failure in (('centroid_drawing_units', 'initial_centroid'),
                               ('ignore_unit_suffix', 'initial_centroid'),
                               ('centroid_bounds_proxy', 'ccw_triangle_centroid')):
            _, result, _ = self._run_model('modeling_centroid_units', fault)
            self.assertEqual(result['status'], 'failed', (fault, result))
            self.assertTrue(result['records'][-1]['id'].endswith(':' + failure))

    def test_nurbs_characterization_has_both_directions_sides_and_finite_endpoints(self):
        jobs = MODELING.modeling_fixtures('dist', ['modeling_nurbs_distance_characterization'])
        observations = [job for job in jobs if 'measurement_context' in job]
        self.assertEqual(len(observations), 14)
        for job in observations:
            context = job['measurement_context']
            start, end, query = context['start'], context['end'], context['query']
            delta = [b-a for a, b in zip(start, end)]
            parameter = max(0, min(1, sum((q-a)*d for q, a, d in zip(query, start, delta))/sum(d*d for d in delta)))
            nearest = [a+parameter*d for a, d in zip(start, delta)]
            self.assertAlmostEqual(math.dist(query, nearest), context['unsigned_segment_distance_mm'])
            self.assertEqual(job['verification_dimension'], 'characterization')
        for fault in (None, 'signed_internal_distance'):
            _, result, _ = self._run_model('modeling_nurbs_distance_characterization', fault, _NurbsModel)
            self.assertEqual(result['status'], 'passed', result)

    def test_bounds_characterization_preserves_both_competing_analytic_predictions(self):
        jobs = MODELING.modeling_fixtures('bounds-probe', ['modeling_curve_bounds_characterization'])
        observations = [job for job in jobs if 'measurement_context' in job]
        self.assertEqual(len(observations), 8)
        self.assertEqual(sum(job.get('name') == 'ResetBBox' for job in jobs), 4)
        for job in observations:
            context = job['measurement_context']
            self.assertEqual(context['projected_control_box_spans'], [34, 36])
            for tight, loose in zip(context['analytic_tight_spans'], context['projected_control_box_spans']):
                self.assertLess(tight, loose)
            self.assertEqual(job['verification_dimension'], 'characterization')
            self.assertEqual(len(job['assertions']), 4)

    def test_rounded_rectangle_oracles_use_subtracted_corner_ellipses(self):
        for index in range(4):
            diameters = self.job('rounded', 'set_diameters_' + str(index))['arguments']
            rx, ry = diameters['xDiam']/2, diameters['yDiam']/2
            self.assertGreater(rx, 0)
            self.assertGreater(ry, 0)
            self.assertLessEqual(rx, 20)
            self.assertLessEqual(ry, 10)
            area = 40*20 - 4*rx*ry + math.pi*rx*ry
            self.assertAlmostEqual(self.job('rounded', 'rounded_area_' + str(index))['assertions'][0]['equals'], area)
            if rx == ry:
                perimeter = 2*(40-2*rx) + 2*(20-2*ry) + 2*math.pi*rx
                self.assertAlmostEqual(self.job('rounded', 'rounded_perimeter_' + str(index))['assertions'][0]['equals'], perimeter)

    def test_oriented_primitives_have_unit_directions_and_rotation_invariant_areas(self):
        for index in range(3):
            for key in ('oriented_rect', 'oriented_oval', 'oriented_round'):
                arguments = self.job('oriented_primitives', 'create_' + key + str(index))['calls'][0]['arguments']
                self.assertAlmostEqual(math.hypot(*arguments['direction']), 1)
                width, height = arguments['width'], arguments['height']
                area = width*height
                if key == 'oriented_oval':
                    area *= math.pi/4
                if key == 'oriented_round':
                    corner_area = arguments['xDiam']*arguments['yDiam']
                    area -= corner_area*(1-math.pi/4)
                self.assertAlmostEqual(self.job('oriented_primitives', key + '_area_' + str(index))['assertions'][0]['equals'], area)

    def test_cone_mass_center_differs_from_bounds_center_and_sphere_radius_extremes(self):
        radii = []
        for index in range(3):
            args = self.job('primitive_solids', 'create_sphere_' + str(index))['calls'][0]['arguments']
            radii.append(args['radiusDistance'])
            self.assertEqual(self.job('primitive_solids', 'sphere_dimensions_' + str(index))['assertions'][0]['equals'], [2*args['radiusDistance']]*3)
            self.assertEqual(self.job('primitive_solids', 'sphere_centroid_' + str(index))['assertions'][0]['equals'], [True]+args['center'])
        self.assertLess(min(radii), 1)
        self.assertGreater(max(radii), 1)
        for index in range(2):
            args = self.job('primitive_solids', 'create_cone_' + str(index))['calls'][0]['arguments']
            base, tip = args['center'], args['tip']
            mass_center = [True] + [(3*a+b)/4 for a, b in zip(base, tip)]
            bounds_center = [(a+b)/2 for a, b in zip(base, tip)]
            job = self.job('primitive_solids', 'cone_mass_centroid_' + str(index))
            self.assertEqual(job['assertions'][0]['equals'], mass_center)
            self.assertFalse(HOST.evaluate_native(job, {'status': 'ok', 'function': 'Centroid3D', 'result': [True]+bounds_center})[0])

    def test_absolute_rotation_idempotence_and_asymmetric_resize_oracles(self):
        for label in ('quarter_turn', 'same_absolute_turn'):
            self.assertEqual(self.job('extrude_info', 'rotation_' + label)['arguments']['xAngle'], 90)
            self.assertEqual(self.job('extrude_info', label + '_dimensions')['assertions'][0]['equals'], [10, 30, 20])
        for index in range(2):
            job = self.job('extrude_info', 'resized_dimensions_' + str(index))
            expected = job['assertions'][0]['equals']
            self.assertEqual(len(set(expected)), 3)
            self.assertFalse(HOST.evaluate_native(job, {'status': 'ok', 'function': job['name'], 'result': expected[::-1]})[0])

    def test_nurbs_indices_and_knot_domain_are_checked_before_parameter_calls(self):
        jobs = MODELING.modeling_fixtures('offline', ['modeling_nurbs_sampling'])
        positions = {job['id'].split(':')[-1]: index for index, job in enumerate(jobs)}
        for job in jobs:
            if job.get('name') in ('NurbsKnot', 'NurbsCurveEvalPt', 'GetParameterOnNurbsCurve', 'GetPointAndParameterOnNurbsCurveAtGivenLength'):
                self.assertGreater(positions[job['id'].split(':')[-1]], positions['linear_knot_count'])
            if job.get('name') == 'NurbsCurveEvalPt':
                self.assertEqual(set(job['arguments']['u']), {'$capture'})
            if job.get('name') == 'GetPointAndParameterOnNurbsCurveAtGivenLength':
                fraction = job['arguments']['inPercentOfLength']
                self.assertLessEqual(0, fraction)
                self.assertLessEqual(fraction, 1)
                point = next(a['equals'] for a in job['assertions'] if a['path'] == ['result', 1])
                self.assertAlmostEqual(math.dist([0, 0, 0], point), 50*fraction)
                self.assertEqual(job['capture']['path'], ['result', 2])
        # Orthogonal 3-4-5 offset from the interior midpoint of the source line.
        distance_job = self.job('nurbs_distance', 'point_distance_2')
        offset = [a-b for a, b in zip(distance_job['arguments']['point'], [15, 20])]
        self.assertEqual(sum(a*b for a, b in zip(offset, [30, 40])), 0)
        self.assertEqual(math.hypot(*offset), distance_job['assertions'][0]['equals'][1])

    def _run_model(self, family, fault=None, model_class=_GeometryModel):
        model, seen = model_class(fault), []
        plan = _plan('model', [family])
        REGISTRY.validate_plan(plan)
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / 'modeling.jsonl'
            result = RUNNER.run_design_plan(_sender(model, seen), plan, journal,
                                            deployed_source_hashes=lambda: plan['source_sha256'])
            events = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
            before = len(seen)
            with self.assertRaises(FileExistsError):
                RUNNER.run_design_plan(_sender(model, seen), plan, journal,
                                       deployed_source_hashes=lambda: plan['source_sha256'])
            self.assertEqual(len(seen), before)
        self.assertEqual(sum(e['event'] == 'intent' for e in events), len(seen))
        self.assertTrue(all(record['kind'] == 'native' for record in result['records']))
        return model, result, seen

    def test_independent_polygon_model_passes_bounds_and_preserves_dimensions(self):
        model, result, seen = self._run_model('modeling_bounds')
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(model.calls.count('SetBBox'), 3)
        self.assertEqual(model.calls.count('SetWidth'), 3)
        self.assertEqual(model.calls.count('SetHeight'), 3)
        self.assertEqual(len(seen), 2*len(MODELING.modeling_fixtures('model', ['modeling_bounds'])))

    def test_silent_noops_and_swapped_resize_axes_fail_linked_readbacks_without_replay(self):
        for fault, label, setter in (('ignore_bbox', 'signed_bounds', 'SetBBox'),
                                      ('width_changes_height', 'width_0', 'SetWidth'),
                                      ('ignore_height', 'height_0', 'SetHeight')):
            with self.subTest(fault=fault):
                model, result, seen = self._run_model('modeling_bounds', fault)
                self.assertEqual(result['status'], 'failed', result)
                record = result['records'][-1]
                self.assertEqual(record['id'], 'design:modeling_bounds:' + label)
                self.assertTrue(record['verifies_jobs'])
                self.assertFalse(record['passed'])
                self.assertEqual(model.calls.count(setter), 1)
                self.assertLess(len(seen), 2*len(MODELING.modeling_fixtures('model', ['modeling_bounds'])))

    def test_duplicate_objects_are_independent_with_both_height_options(self):
        model, result, _ = self._run_model('modeling_duplicates')
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(model.calls.count('CreateDuplicateObject'), 1)
        self.assertEqual(model.calls.count('CreateDuplicateObjN'), 2)
        self.assertEqual(len(model.objects), 5)  # source, three copies, and parent
        for api in ('CreateDuplicateObject', 'CreateDuplicateObjN'):
            model, result, _ = self._run_model('modeling_duplicates', 'alias_' + api)
            self.assertEqual(result['status'], 'failed', result)
            self.assertIn('source_bounds_survive', result['records'][-1]['id'])
            self.assertEqual(model.calls.count(api), 1)

    def test_planar_conversions_preserve_copy_sources_and_never_reuse_consumed_handle(self):
        model, result, _ = self._run_model('modeling_planar_conversion')
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(model.calls.count('ConvertToPolyline'), 1)
        for api in ('MakePolygon', 'MakePolyline'):
            _, result, _ = self._run_model('modeling_planar_conversion', 'alias_' + api)
            self.assertEqual(result['status'], 'failed', result)
            self.assertIn('source_not_aliased', result['records'][-1]['id'])

    def test_planar_conversions_reject_unchanged_object_type_despite_correct_geometry(self):
        for api, key, expected in (('MakePolygon', 'made_polygon', 5), ('MakePolyline', 'made_polyline', 21)):
            with self.subTest(api=api):
                job = self.job('planar_conversion', key + '_type')
                self.assertEqual(job['assertions'][0]['equals'], expected)
                model, result, _ = self._run_model('modeling_planar_conversion', 'wrong_type_' + api)
                self.assertEqual(result['status'], 'failed', result)
                self.assertEqual(result['records'][-1]['id'], job['id'])
                self.assertEqual(model.calls.count(api), 1)
                self.assertTrue(result['records'][-1]['verifies_jobs'])

    def test_oriented_spans_match_independent_rotated_construction_box_corners(self):
        model, result, _ = self._run_model('modeling_oriented_primitives', model_class=_OrientedModel)
        self.assertEqual(result['status'], 'passed', result)
        for api in ('RectangleN', 'OvalN', 'RRectangleN'):
            self.assertEqual(model.calls.count(api), 3)
        self.assertEqual(model.calls.count('GetBBox'), 9)
        jobs = MODELING.modeling_fixtures('offline', ['modeling_oriented_primitives'])
        self.assertFalse(any(job.get('name') in ('HWidth', 'HHeight') for job in jobs))
        # Non-square quarter turns exchange spans. GetBBox projects the same
        # construction box for all three primitives, including curved ones.
        for key in ('oriented_rect', 'oriented_oval', 'oriented_round'):
            self.assertEqual(self.job('oriented_primitives', key + '_projected_bounds_1')['assertions'][0]['bbox_size'], [20, 30])
            self.assertEqual(self.job('oriented_primitives', key + '_projected_bounds_2')['assertions'][0]['bbox_size'], [34, 36])

    def test_tight_contour_substitution_does_not_satisfy_construction_box_contract(self):
        _, result, _ = self._run_model('modeling_oriented_primitives', 'tight_contour_bounds', _OrientedModel)
        self.assertEqual(result['status'], 'failed', result)
        self.assertTrue(result['records'][-1]['id'].endswith(':oriented_oval_projected_bounds_2'))
        # Preserve both analytic contours as distinct quantities, not looser
        # numeric tolerances that happen to accept a mismatched contract.
        for key, tight in (('oriented_oval', [math.sqrt(580), math.sqrt(720)]),
                           ('oriented_round', [32.4, 34.4])):
            job = self.job('oriented_primitives', key + '_projected_bounds_2')
            self.assertFalse(HOST.evaluate_native(job, {'status': 'ok', 'function': 'GetBBox',
                                                        'result': [[0, 0], tight]})[0])

    def test_projection_oracle_does_not_depend_on_an_undocumented_origin_corner(self):
        _, result, _ = self._run_model('modeling_oriented_primitives', 'different_origin_convention', _OrientedModel)
        self.assertEqual(result['status'], 'passed', result)

    def test_oriented_spans_reject_ignored_direction_even_when_area_passes(self):
        for api, key in (('RectangleN', 'oriented_rect'), ('OvalN', 'oriented_oval'), ('RRectangleN', 'oriented_round')):
            with self.subTest(api=api):
                model, result, _ = self._run_model('modeling_oriented_primitives', 'ignore_direction_' + api, _OrientedModel)
                self.assertEqual(result['status'], 'failed', result)
                self.assertEqual(result['records'][-1]['id'], 'design:modeling_oriented_primitives:' + key + '_projected_bounds_1')
                area_id = 'design:modeling_oriented_primitives:' + key + '_area_1'
                self.assertTrue(next(r for r in result['records'] if r['id'] == area_id)['passed'])
                self.assertEqual(model.calls.count(api), 2)

    def test_csg_dimensions_and_centroids_match_independent_volume_partition(self):
        model, result, _ = self._run_model('modeling_csg')
        self.assertEqual(result['status'], 'passed', result)
        for name in ('AddSolid', 'IntersectSolid', 'SubtractSolid'):
            self.assertEqual(model.calls.count(name), 1)
        # HExtrude consumes six fresh profiles and three booleans consume both
        # inputs; only the three results and parent remain in this strict model.
        self.assertEqual(len(model.objects), 4)

    def test_csg_success_code_alone_does_not_pass_wrong_geometry(self):
        for fault, label, api in (('union_as_intersection', 'boolean_dimensions_0', 'AddSolid'),
                                  ('subtract_reversed', 'boolean_dimensions_2', 'SubtractSolid')):
            with self.subTest(fault=fault):
                model, result, _ = self._run_model('modeling_csg', fault)
                self.assertEqual(result['status'], 'failed', result)
                record = result['records'][-1]
                self.assertEqual(record['id'], 'design:modeling_csg:' + label)
                self.assertEqual(record['verifies_jobs'], ['design:modeling_csg:boolean_' + api])
                self.assertEqual(model.calls.count(api), 1)


    def test_nurbs_numeric_captures_work_with_nonstandard_knot_domain(self):
        model, result, _ = self._run_model('modeling_nurbs_sampling', model_class=_NurbsModel)
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(model.calls.count('NurbsCurveEvalPt'), 12)
        self.assertEqual(result['captures']['nurbs_domain_0'], -3.0)
        self.assertEqual(result['captures']['nurbs_domain_3'], 7.0)
        self.assertEqual(result['captures']['nurbs_sample_parameter_2'], 2.0)
        self.assertEqual(result['captures']['nurbs_projected_parameter_2'], 2.0)

    def test_nurbs_oracles_detect_ignored_parameter_and_incorrect_success_output(self):
        for fault, label in (('ignore_parameter', 'domain_endpoint_3'),
                             ('wrong_sample_parameter', 'evaluate_fraction_parameter_0')):
            with self.subTest(fault=fault):
                model, result, _ = self._run_model('modeling_nurbs_sampling', fault, _NurbsModel)
                self.assertEqual(result['status'], 'failed', result)
                self.assertEqual(result['records'][-1]['id'], 'design:modeling_nurbs_sampling:' + label)
                self.assertFalse(result['records'][-1]['passed'])
                self.assertEqual(model.calls.count('ConvertToNURBS'), 1)


if __name__ == '__main__':
    unittest.main()
