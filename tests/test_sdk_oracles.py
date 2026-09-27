"""Independent tests of fixture attribution, guard checks and numeric oracles.

No Vectorworks API is invoked. Protocol mutations must fail rather than award
native coverage; analytic spot checks prevent the fixture source and oracle
from silently agreeing on a wrong unit/sign/index convention.
"""
import copy
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = r'C:\SDK-tests\VWX-MCP-SDK-TEST-oracles.vwx'
UUID = '12345678-1234-4234-8234-123456789abc'


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOST = load('oracle_host', 'tools/sdk_host_suite.py')
RUNNER = load('oracle_runner', 'tools/sdk_design_runner.py')
NUMERIC = load('oracle_numeric', 'tools/sdk_numeric_fixtures.py')
REGISTRY = load('oracle_registry', 'tools/sdk_regression_suite.py')
RESOURCE = load('oracle_resource', 'tools/sdk_resource_fixtures.py')
RUNTIME = load('oracle_runtime', 'vwx-plugin/sdk_runtime.py')
CATALOG = json.loads((ROOT / 'vwx-plugin/sdk_catalog.json').read_text(encoding='utf-8'))


def response(name='Abs', result=2.0):
    return {'status': 'ok', 'function': name, 'result': result}


def fixture(expected=2.0, path=None):
    return {'id': 'oracle:Abs', 'kind': 'native', 'name': 'Abs', 'arguments': {'v': -2},
            'assertions': [{'path': path or ['result'], 'equals': expected}]}


def guard():
    return {'status': 'ok', 'count': 2, 'results': [response('GetFPathName', DOCUMENT),
                                                 response('GetVersion', [32, 0, 0, 2])]}


class NativeOracleProtocolTests(unittest.TestCase):
    def test_single_result_requires_exact_function_identity(self):
        job = fixture()
        self.assertTrue(HOST.evaluate_native(job, response())[0])
        for returned in ({'status': 'ok', 'result': 2}, response('Cos'), response(None),
                         response('abs'), response(True)):
            with self.subTest(returned=returned):
                self.assertFalse(HOST.evaluate_native(job, returned)[0])

    def test_sequence_requires_order_identity_status_and_exact_integer_count(self):
        job = {'calls': [{'name': 'Abs'}, {'name': 'Sqr'}],
               'assertions': [{'path': ['results', 0, 'result'], 'equals': 2}]}
        good = {'status': 'ok', 'count': 2, 'results': [response(), response('Sqr', 4)]}
        self.assertTrue(HOST.evaluate_native(job, good)[0])
        mutations = []
        for count in (None, False, True, 0, 1, 3, 2.0, '2'):
            mutations.append(dict(good, count=count))
        missing_count = copy.deepcopy(good)
        missing_count.pop('count')
        mutations.append(missing_count)
        for values in (good['results'][:1], good['results'] + [response('Extra', 0)],
                       list(reversed(good['results'])), None, {}, 'result'):
            mutations.append(dict(good, results=values))
        for index in range(2):
            for key, value in [('function', None), ('function', 'wrong'), ('status', 'failed'),
                               ('error', ''), ('error', 'native error')]:
                changed = copy.deepcopy(good)
                changed['results'][index][key] = value
                mutations.append(changed)
        for changed in mutations:
            with self.subTest(response=changed):
                self.assertFalse(HOST.evaluate_native(job, changed)[0])

    def test_empty_or_malformed_assertions_cannot_award_native_credit(self):
        for assertions in (None, [], {}, 'equals', [None], ['invalid'], [{}],
                           [{'path': ['result']}], [{'path': ['result'], 'bogus': True}],
                           [{'path': ['result'], 'equals': 2, 'valid_uuid': True}],
                           [{'path': ['result'], 'equals': 2, 'ignored': True}]):
            with self.subTest(assertions=assertions):
                self.assertFalse(HOST.evaluate_native(dict(fixture(), assertions=assertions), response())[0])

    def test_invalid_paths_fail_closed_without_python_negative_or_boolean_indexing(self):
        returned = response(result={'a': [2, 9]})
        for path in (None, '', 'result', [], [True], ['result', 'a', True],
                     ['result', 'a', -1], ['result', 'a', 5], ['result', 'a', '0'],
                     ['result', 0], ['result', 'missing'], ['result', 'a', 0.0],
                     ['result', 'a', {}]):
            with self.subTest(path=path):
                job = fixture()
                job['assertions'] = [{'path': path, 'equals': 9}]
                passed, details = HOST.evaluate_native(job, returned)
                self.assertFalse(passed)
                self.assertTrue(details)
                self.assertFalse(details[0]['passed'])

    def test_range_predicate_requires_two_ordered_finite_nonboolean_bounds(self):
        for bounds in (None, 2, {}, [0], [0, 3, 4], [3, 0], [False, 3], [0, True],
                       [0, math.inf], [-math.inf, 3], [math.nan, 3], [0, 10 ** 1000], ['0', 3]):
            with self.subTest(bounds=repr(bounds)[:60]):
                job = dict(fixture(), assertions=[{'path': ['result'], 'range_inclusive': bounds}])
                self.assertFalse(HOST.evaluate_native(job, response())[0])
        for actual, expected in [(0, True), (2, True), (3, True), (-0.1, False), (3.1, False),
                                  (True, False), (math.nan, False), (math.inf, False), (10 ** 1000, False)]:
            job = dict(fixture(), assertions=[{'path': ['result'], 'range_inclusive': [0, 3]}])
            self.assertEqual(HOST.evaluate_native(job, response(result=actual))[0], expected)

    def test_nested_equality_is_numeric_but_never_boolean_or_nonfinite(self):
        expected = {'point': [1, 2.5, {'z': -3}], 'ok': True, 'label': 'x'}
        job = fixture(expected)
        correct = {'point': [1.0, 2.5 + 1e-10, {'z': -3.0}], 'ok': True, 'label': 'x'}
        self.assertTrue(HOST.evaluate_native(job, response(result=correct))[0])
        for path, value in [(['point', 0], True), (['point', 1], math.nan),
                            (['point', 2, 'z'], -math.inf), (['ok'], 1), (['label'], 0)]:
            wrong = copy.deepcopy(correct)
            parent = wrong
            for key in path[:-1]:
                parent = parent[key]
            parent[path[-1]] = value
            self.assertFalse(HOST.evaluate_native(job, response(result=wrong))[0])
        for expected_value in (math.inf, math.nan, 10 ** 1000, object(), {'nested': [math.inf]}):
            self.assertFalse(HOST.evaluate_native(fixture(expected_value), response(result=expected_value))[0])

    def test_numeric_oracle_overflow_and_cycles_fail_without_throwing(self):
        actual_cycle = []
        expected_cycle = []
        actual_cycle.append(actual_cycle)
        expected_cycle.append(expected_cycle)
        cases = [(10 ** 1000, 10 ** 1000), (1.0, 10 ** 1000), (actual_cycle, expected_cycle)]
        for actual, expected in cases:
            passed, assertions = HOST.evaluate_native(fixture(expected), response(result=actual))
            self.assertFalse(passed)
            self.assertTrue(assertions)

    def test_numeric_tolerances_are_finite_nonnegative_and_not_boolean(self):
        for name in ('abs_tol', 'rel_tol'):
            for value in (True, False, None, '0', [], {}, -1, -1e-20, math.nan, math.inf, 10 ** 1000):
                job = fixture()
                job['assertions'][0][name] = value
                with self.subTest(tolerance=name, value=repr(value)[:40]):
                    self.assertFalse(HOST.evaluate_native(job, response())[0])
        job = dict(fixture(), assertions=[{'path': ['result'], 'range_inclusive': [0, 3], 'abs_tol': 0}])
        self.assertFalse(HOST.evaluate_native(job, response())[0])

    def test_custom_tolerances_apply_recursively_and_zero_absolute_is_not_defaulted_away(self):
        job = fixture({'values': [1e-18, {'positive': 2.0}]})
        job['assertions'][0].update(abs_tol=0, rel_tol=1e-9)
        self.assertTrue(HOST.evaluate_native(job, response(result={
            'values': [1e-18 * (1 + 5e-10), {'positive': 2.0}]}))[0])
        self.assertFalse(HOST.evaluate_native(job, response(result={
            'values': [0.0, {'positive': 2.0}]}))[0])
        self.assertFalse(HOST.evaluate_native(job, response(result={
            'values': [1e-18, {'positive': 2.01}]}))[0])
        exact = fixture(2.0)
        exact['assertions'][0].update(abs_tol=0, rel_tol=0)
        self.assertTrue(HOST.evaluate_native(exact, response())[0])
        self.assertFalse(HOST.evaluate_native(exact, response(result=2.0 + 1e-12))[0])

    def test_uuid_oracle_rejects_nil_malformed_and_nonstring_values(self):
        job = dict(fixture(), assertions=[{'path': ['result'], 'valid_uuid': True}])
        self.assertTrue(HOST.evaluate_native(job, response(result=UUID))[0])
        for value in (None, False, 0, 1, '', 'object-name', '0' * 32,
                      '12345678-1234-4234-8234-123456789abz', [UUID], {'uuid': UUID}):
            self.assertFalse(HOST.evaluate_native(job, response(result=value))[0])

    def test_string_predicate_requires_true_and_nonempty_actual_string(self):
        for predicate in (False, 1, None, 'true'):
            job = dict(fixture(), assertions=[{'path': ['result'], 'nonempty_string': predicate}])
            self.assertFalse(HOST.evaluate_native(job, response(result='hello'))[0])
        job = dict(fixture(), assertions=[{'path': ['result'], 'nonempty_string': True}])
        for actual in ('', None, True, 7, ['text']):
            self.assertFalse(HOST.evaluate_native(job, response(result=actual))[0])
        self.assertTrue(HOST.evaluate_native(job, response(result='Ω'))[0])

    def test_capture_shape_missing_path_and_non_json_value_fail_before_pass_credit(self):
        for capture in (None, {}, {'name': 'saved'}, {'name': '', 'path': ['result']},
                        {'name': [], 'path': ['result']}, {'name': 'saved', 'path': ['missing']},
                        {'name': 'saved', 'path': []}, {'name': 'saved', 'path': ['result'], 'extra': 1}):
            job = dict(fixture(), capture=capture)
            self.assertFalse(HOST.evaluate_native(job, response())[0])
        job = dict(fixture(), capture={'name': 'saved', 'path': ['unasserted']})
        for value in (object(), math.nan, math.inf):
            self.assertFalse(HOST.evaluate_native(job, dict(response(), unasserted=value))[0])

    def test_bad_capture_never_gets_added_to_native_passes_by_runner(self):
        job = dict(fixture(), capture={'name': 'saved', 'path': ['not_returned']})
        plan = {'run_id': 'invalid_capture', 'document_path': DOCUMENT,
                'source_sha256': {name: 'a' * 64 for name in HOST.MODULE_FILES},
                'summary': {'native_cases': 1}, 'limitations': [], 'jobs': [job]}
        sender = Mock(side_effect=[guard(), response()])
        with tempfile.TemporaryDirectory() as directory:
            result = RUNNER.run_design_plan(sender, plan, Path(directory) / 'capture.jsonl',
                                           deployed_source_hashes=lambda: plan['source_sha256'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['native_functions_passed'], [])
        self.assertEqual(result['functions_all_planned_cases_passed'], [])
        self.assertEqual(result['captures'], {})
        sender.assert_called()
        self.assertEqual(sender.call_count, 2)


class NullableHandleOracleTests(unittest.TestCase):
    def sample(self, calls, *, sequence=False):
        responses = []
        for call in calls:
            entry = CATALOG['functions'][call['name']]
            returned = response(call['name'], REGISTRY._sample_result(entry))
            if entry['returns']['kind'] == 'tuple':
                returned['outputs'] = {item['name']: returned['result'][index]
                                       for index, item in enumerate(entry['returns']['items'])}
            responses.append(returned)
        return ({'status': 'ok', 'count': len(responses), 'results': responses}
                if sequence else responses[0])

    def validate(self, job):
        calls = job.get('calls', [{'name': job.get('name'), 'arguments': job.get('arguments')}])
        sequence = 'calls' in job
        return REGISTRY._validate_assertions(job, self.sample(calls, sequence=sequence),
            nullable_handle_paths=REGISTRY._nullable_handle_paths(
                calls, CATALOG['functions'], sequence=sequence))

    def test_unassigned_material_handle_plan_accepts_null_but_requires_actual_null(self):
        plan = REGISTRY.build_plan(DOCUMENT, run_id='null_handle', selected=['data:data_materials'])
        job = next(job for job in plan['jobs'] if job['id'].endswith(':unassigned_material_handle'))
        self.assertEqual(job['assertions'][0], {'path': ['result'], 'equals': None})
        self.assertTrue(REGISTRY.validate_plan(plan))
        self.assertTrue(HOST.evaluate_native(job, response('GetObjMaterialHandle', None))[0])
        for incorrect in (UUID, '', 'None', 0, False, [], {}):
            with self.subTest(incorrect=incorrect):
                self.assertFalse(HOST.evaluate_native(job, response('GetObjMaterialHandle', incorrect))[0])

    def test_tuple_handle_null_accepts_positional_named_and_full_tuple_assertions(self):
        job = {'id': 'oracle:AddSolid', 'kind': 'native', 'name': 'AddSolid',
               'arguments': {'obj1': UUID, 'obj2': UUID}, 'assertions': [
                   {'path': ['result'], 'equals': [1, None]},
                   {'path': ['result', 1], 'equals': None},
                   {'path': ['outputs', 'newSolid'], 'equals': None}]}
        self.validate(job)
        returned = dict(response('AddSolid', [1, None]), outputs={'result': 1, 'newSolid': None})
        self.assertTrue(HOST.evaluate_native(job, returned)[0])
        for wrong in ([None, None], [1, UUID], [False, None], [1, None, None]):
            changed = copy.deepcopy(job)
            changed['assertions'][0]['equals'] = wrong
            if wrong == [1, UUID]:
                self.validate(changed)
                self.assertFalse(HOST.evaluate_native(changed, returned)[0])
            else:
                with self.assertRaises(ValueError):
                    self.validate(changed)

    def test_sequence_nullable_paths_stay_at_the_correct_step_and_output(self):
        calls = [{'name': 'GetObjMaterialHandle', 'arguments': {'h': UUID}},
                 {'name': 'GetName', 'arguments': {'h': UUID}},
                 {'name': 'AddSolid', 'arguments': {'obj1': UUID, 'obj2': UUID}}]
        job = {'id': 'oracle:nullable_sequence', 'kind': 'native', 'calls': calls,
               'assertions': [{'path': ['results', 0, 'result'], 'equals': None},
                              {'path': ['results', 2, 'result'], 'equals': [1, None]},
                              {'path': ['results', 2, 'outputs', 'newSolid'], 'equals': None}]}
        self.validate(job)
        for wrong_path in (['results', 1, 'result'], ['results', 2, 'result', 0],
                           ['results', 2, 'outputs', 'result'], ['results', 0, 'status']):
            changed = dict(job, assertions=[{'path': wrong_path, 'equals': None}])
            with self.subTest(path=wrong_path), self.assertRaises(ValueError):
                self.validate(changed)

    def test_plain_strings_and_other_sdk_types_do_not_gain_null_oracles(self):
        for name, arguments in [('GetName', {'h': UUID}), ('Abs', {'v': 2}),
                                ('Get3DInfo', {'h': UUID}), ('ValidNumStr', {'str': '1'})]:
            job = {'id': 'oracle:' + name, 'kind': 'native', 'name': name,
                   'arguments': arguments, 'assertions': [{'path': ['result'], 'equals': None}]}
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.validate(job)
        # A UUID-looking sample alone is not a HANDLE schema declaration.
        with self.assertRaises(ValueError):
            REGISTRY._validate_assertions(fixture(None), response(result=UUID))
        self.assertFalse(REGISTRY._expected_shape(UUID, None))
        self.assertFalse(REGISTRY._expected_shape('ordinary string', None))
        self.assertTrue(REGISTRY._expected_shape(None, None))

    def test_nullable_contract_preserves_nonnull_uuid_predicate(self):
        job = {'id': 'oracle:GetObjMaterialHandle', 'kind': 'native',
               'name': 'GetObjMaterialHandle', 'arguments': {'h': UUID},
               'assertions': [{'path': ['result'], 'valid_uuid': True}]}
        self.validate(job)
        self.assertTrue(HOST.evaluate_native(job, response('GetObjMaterialHandle', UUID))[0])
        self.assertFalse(HOST.evaluate_native(job, response('GetObjMaterialHandle', None))[0])


class BoundingBoxOracleTests(unittest.TestCase):
    def job(self, spans, **options):
        return {'id': 'oracle:GetBBox', 'kind': 'native', 'name': 'GetBBox',
                'arguments': {'h': UUID},
                'assertions': [dict(path=['result'], bbox_size=spans, **options)]}

    def test_spans_ignore_origin_and_corner_order_but_preserve_axes(self):
        job = self.job([30, 20])
        for points in ([[0, 20], [30, 0]], [[30, 0], [0, 20]],
                       [[-100, -50], [-70, -30]], [[1010, -220], [1040, -240]],
                       ((30, 20), (0, 0))):
            with self.subTest(points=points):
                passed, checked = HOST.evaluate_native(job, response('GetBBox', points))
                self.assertTrue(passed)
                self.assertEqual(checked[0]['actual'], points, 'Evidence retains original coordinates')
                REGISTRY._validate_assertions(job, response('GetBBox', points))
        for wrong in ([[0, 30], [20, 0]], [[0, 0], [0, 0]], [[0, 20], [29, 0]], [[0, 19], [30, 0]]):
            self.assertFalse(HOST.evaluate_native(job, response('GetBBox', wrong))[0])

    def test_rotated_projected_spans_detect_direction_noop_and_intrinsic_dimensions(self):
        # Independent 3-4-5 rotation: x-span=30*.6+20*.8=34;
        # y-span=30*.8+20*.6=36. No insertion-point assumption is needed.
        job = self.job([34, 36])
        self.assertTrue(HOST.evaluate_native(job, response('GetBBox', [[-17, 18], [17, -18]]))[0])
        for wrong in ([[0, 20], [30, 0]], [[0, 36], [30, 0]], [[0, 34], [36, 0]]):
            self.assertFalse(HOST.evaluate_native(job, response('GetBBox', wrong))[0])

    def test_invalid_actual_shapes_and_nonfinite_coordinates_fail_closed(self):
        invalid = (None, True, 1, 'bbox', {}, [], [0, 0, 30, 20], [[0, 0]],
                   [[0, 0], [30, 20], [1, 1]], [[0], [30, 20]], [[0, 0], [30, 20, 0]],
                   [[True, 0], [30, 20]], [[0, False], [30, 20]], [[0, '0'], [30, 20]],
                   [[0, 0], [math.nan, 20]], [[0, math.inf], [30, 20]],
                   [[0, 0], [10 ** 1000, 20]], [[-1e308, 0], [1e308, 20]])
        for points in invalid:
            with self.subTest(points=repr(points)[:70]):
                self.assertFalse(HOST.evaluate_native(self.job([30, 20]), response('GetBBox', points))[0])
                with self.assertRaises(ValueError):
                    REGISTRY._validate_assertions(self.job([30, 20]), response('GetBBox', points))

    def test_expected_spans_require_exact_finite_nonnegative_pair(self):
        points = [[0, 20], [30, 0]]
        for spans in (None, True, 30, '30,20', {}, [], [30], [30, 20, 0],
                      [[30, 20]], [True, 20], [30, False], [30, '20'], [-30, 20],
                      [30, -1e-20], [math.nan, 20], [30, math.inf], [10 ** 1000, 20]):
            with self.subTest(spans=repr(spans)[:65]):
                self.assertFalse(HOST.evaluate_native(self.job(spans), response('GetBBox', points))[0])
                with self.assertRaises(ValueError):
                    REGISTRY._validate_assertions(self.job(spans), response('GetBBox', points))
        self.assertTrue(HOST.evaluate_native(self.job([0, 0]), response('GetBBox', [[2, 3], [2, 3]]))[0])
        REGISTRY._validate_assertions(self.job([0, 20]), response('GetBBox', [[0, 20], [0, 0]]))

    def test_small_bounded_tolerances_reject_invalid_and_permissive_values(self):
        points = [[0, 20], [30, 0]]
        for option, maximum in (('abs_tol', 1e-3), ('rel_tol', 1e-6)):
            for tolerance in (0, 1e-9, maximum):
                job = self.job([30, 20], **{option: tolerance})
                self.assertTrue(HOST.evaluate_native(job, response('GetBBox', points))[0])
                REGISTRY._validate_assertions(job, response('GetBBox', points))
            for tolerance in (True, False, None, '0', [], {}, -1e-20, math.nan,
                              math.inf, 10 ** 1000, maximum * 1.001, 1, 30):
                job = self.job([30, 20], **{option: tolerance})
                with self.subTest(option=option, tolerance=repr(tolerance)[:45]):
                    self.assertFalse(HOST.evaluate_native(job, response('GetBBox', points))[0])
                    with self.assertRaises(ValueError):
                        REGISTRY._validate_assertions(job, response('GetBBox', points))

    def test_tolerances_compare_spans_without_relaxing_coordinate_shape(self):
        job = self.job([30, 20], abs_tol=1e-6, rel_tol=0)
        self.assertTrue(HOST.evaluate_native(job, response('GetBBox', [[0, 0], [30 + 5e-7, 20]]))[0])
        self.assertFalse(HOST.evaluate_native(job, response('GetBBox', [[0, 0], [30 + 2e-6, 20]]))[0])
        tiny = self.job([1e-18, 2e-18], abs_tol=0, rel_tol=1e-9)
        self.assertTrue(HOST.evaluate_native(tiny, response('GetBBox', [[0, 0], [1e-18 * (1 + 5e-10), 2e-18]]))[0])
        self.assertFalse(HOST.evaluate_native(tiny, response('GetBBox', [[0, 0], [0, 2e-18]]))[0])
        self.assertFalse(HOST.evaluate_native(tiny, response('GetBBox', [[0, 0], [1e-18, True]]))[0])

    def test_sequence_paths_attribution_and_exclusive_predicate_rules_still_apply(self):
        job = {'id': 'bbox-sequence', 'kind': 'native', 'calls': [{'name': 'GetBBox', 'arguments': {'h': UUID}}],
               'assertions': [{'path': ['results', 0, 'result'], 'bbox_size': [30, 20]}]}
        returned = {'status': 'ok', 'count': 1, 'results': [response('GetBBox', [[0, 20], [30, 0]])]}
        self.assertTrue(HOST.evaluate_native(job, returned)[0])
        REGISTRY._validate_assertions(job, returned)
        wrong = copy.deepcopy(returned)
        wrong['results'][0]['function'] = 'HWidth'
        self.assertFalse(HOST.evaluate_native(job, wrong)[0])
        for key, value in (('equals', [30, 20]), ('unknown', True)):
            malformed = self.job([30, 20])
            malformed['assertions'][0][key] = value
            self.assertFalse(HOST.evaluate_native(malformed, response('GetBBox', [[0, 20], [30, 0]]))[0])
            with self.assertRaises(ValueError):
                REGISTRY._validate_assertions(malformed, response('GetBBox', [[0, 20], [30, 0]]))


class AngularOracleTests(unittest.TestCase):
    def job(self, angle, **options):
        return {'id': 'oracle:GetSymRot', 'kind': 'native', 'name': 'GetSymRot',
                'arguments': {'symHd': UUID},
                'assertions': [dict(path=['result'], angle_degrees=angle, **options)]}

    def test_equivalent_direction_representations_pass(self):
        for expected, actual in [(270, -90), (-90, 270), (0, 360), (360, 0),
                                  (0, -720), (45, 765), (180, -180), (-0.0, 0.0)]:
            with self.subTest(expected=expected, actual=actual):
                self.assertTrue(HOST.evaluate_native(self.job(expected), response('GetSymRot', actual))[0])

    def test_wrong_direction_radians_and_silent_zero_fail(self):
        for expected, actual in [(90, 0), (270, 90), (45, -45), (90, math.pi / 2), (0, .01)]:
            self.assertFalse(HOST.evaluate_native(self.job(expected), response('GetSymRot', actual))[0])
        # Ordinary equality remains appropriate for sweep/extent values.
        self.assertFalse(HOST.evaluate_native(fixture(270), response(result=-90))[0])
        self.assertFalse(HOST.evaluate_native(fixture(360), response(result=0))[0])

    def test_angular_values_require_finite_nonboolean_scalars(self):
        invalid = (True, False, None, '270', [270], {'angle': 270}, math.nan, math.inf, -math.inf, 10 ** 1000)
        for value in invalid:
            with self.subTest(value=repr(value)[:45]):
                self.assertFalse(HOST.evaluate_native(self.job(value), response('GetSymRot', 270))[0])
                self.assertFalse(HOST.evaluate_native(self.job(270), response('GetSymRot', value))[0])
                with self.assertRaises(ValueError):
                    REGISTRY._validate_assertions(self.job(value), response('GetSymRot', 1.0))
        # Independent reduction avoids overflow before taking circular distance.
        self.assertTrue(HOST.evaluate_native(self.job(1e308), response('GetSymRot', 1e308))[0])

    def test_tolerance_is_small_absolute_only_and_handles_wrap_boundary(self):
        job = self.job(0, abs_tol=1e-6)
        for actual in (-5e-7, 360 - 5e-7, 360 + 5e-7):
            self.assertTrue(HOST.evaluate_native(job, response('GetSymRot', actual))[0])
        for actual in (-2e-6, 360 + 2e-6, 90):
            self.assertFalse(HOST.evaluate_native(job, response('GetSymRot', actual))[0])
        self.assertTrue(HOST.evaluate_native(self.job(270, abs_tol=0), response('GetSymRot', -90))[0])
        for value in (True, False, None, '0', [], {}, -1, -1e-20, math.nan, math.inf, 10 ** 1000, .0011, 90, 360):
            with self.subTest(tolerance=repr(value)[:45]):
                bad = self.job(270, abs_tol=value)
                self.assertFalse(HOST.evaluate_native(bad, response('GetSymRot', -90))[0])
                with self.assertRaises(ValueError):
                    REGISTRY._validate_assertions(bad, response('GetSymRot', 1.0))
        for value in (0, 1e-9, True, math.nan):
            bad = self.job(270, rel_tol=value)
            self.assertFalse(HOST.evaluate_native(bad, response('GetSymRot', -90))[0])
            with self.assertRaises(ValueError):
                REGISTRY._validate_assertions(bad, response('GetSymRot', 1.0))

    def test_registry_checks_predicate_shape_and_rejects_multiple_predicates(self):
        REGISTRY._validate_assertions(self.job(270), response('GetSymRot', 1.0))
        REGISTRY._validate_assertions(self.job(-90, abs_tol=.001), response('GetSymRot', 1.0))
        for actual in (True, None, 'angle', [0]):
            with self.assertRaises(ValueError):
                REGISTRY._validate_assertions(self.job(270), response('GetSymRot', actual))
        for key, value in [('equals', 270), ('unknown', True)]:
            job = self.job(270)
            job['assertions'][0][key] = value
            self.assertFalse(HOST.evaluate_native(job, response('GetSymRot', -90))[0])
            with self.assertRaises(ValueError):
                REGISTRY._validate_assertions(job, response('GetSymRot', 1.0))

    def test_resource_angle_oracles_apply_only_to_getsymrot(self):
        jobs = RESOURCE.resource_fixtures('angles')
        rotations = [j for j in jobs if j.get('name') == 'GetSymRot']
        self.assertEqual(len(rotations), 6)
        for job in jobs:
            for assertion in job['assertions']:
                self.assertEqual('angle_degrees' in assertion, job.get('name') == 'GetSymRot')
        original = next(j for j in rotations if j['id'].endswith(':symbol_third_rotation'))
        self.assertEqual(original['assertions'][0]['angle_degrees'], 270)
        self.assertTrue(HOST.evaluate_native(original, response('GetSymRot', -90))[0])
        self.assertFalse(HOST.evaluate_native(original, response('GetSymRot', 90))[0])


class TypedGuardOracleTests(unittest.TestCase):
    def test_only_exact_attributed_guard_order_is_accepted(self):
        self.assertIsNone(RUNNER._check_guard(guard(), DOCUMENT))
        invalid = []
        for index in range(2):
            for name in (None, '', 'WrongApi'):
                changed = guard()
                changed['results'][index]['function'] = name
                invalid.append(changed)
            changed = guard()
            changed['results'][index].pop('function')
            invalid.append(changed)
        changed = guard()
        changed['results'].reverse()
        invalid.append(changed)
        for changed in invalid:
            self.assertEqual(RUNNER._check_guard(changed, DOCUMENT)['code'], 'SDK_DESIGN_GUARD')

    def test_guard_requires_complete_count_and_success_protocol(self):
        for count in (None, True, False, 1, 3, 2.0, '2'):
            self.assertIsNotNone(RUNNER._check_guard(dict(guard(), count=count), DOCUMENT))
        for results in (None, {}, [], guard()['results'][:1], guard()['results'] + [response()]):
            self.assertIsNotNone(RUNNER._check_guard(dict(guard(), results=results), DOCUMENT))
        for index in range(2):
            for key, value in [('status', 'failed'), ('status', None), ('error', ''), ('error', 'failed')]:
                changed = guard()
                changed['results'][index][key] = value
                self.assertIsNotNone(RUNNER._check_guard(changed, DOCUMENT))
        for returned in (None, [], 'ok', 1, dict(guard(), status='failed')):
            self.assertIsNotNone(RUNNER._check_guard(returned, DOCUMENT))

    def test_guard_checks_full_windows_2027_version_shape_and_exact_path(self):
        for version in (None, [], [32], [32, 0, 0], [32, 0, 0, 2, 882075],
                        [True, 0, 0, 2], [32.0, 0, 0, 2], [32, False, 0, 2],
                        [32, 0, -1, 2], [31, 0, 0, 2], [33, 0, 0, 2], [32, 0, 0, 1]):
            changed = guard()
            changed['results'][1]['result'] = version
            self.assertEqual(RUNNER._check_guard(changed, DOCUMENT)['code'], 'SDK_SUITE_VERSION')
        for path in ('', None, 1, r'C:\Client\VWX-MCP-SDK-TEST-oracles.vwx', DOCUMENT + '.bak'):
            changed = guard()
            changed['results'][0]['result'] = path
            self.assertEqual(RUNNER._check_guard(changed, DOCUMENT)['code'], 'SDK_SUITE_DOCUMENT')
        changed = guard()
        changed['results'][0]['result'] = DOCUMENT.upper().replace('\\', '/')
        self.assertIsNone(RUNNER._check_guard(changed, DOCUMENT))

    def test_wrong_guard_identity_prevents_fixture_send_and_coverage_credit(self):
        plan = {'run_id': 'guard_identity', 'document_path': DOCUMENT,
                'source_sha256': {name: 'a' * 64 for name in HOST.MODULE_FILES},
                'summary': {'native_cases': 1}, 'limitations': [], 'jobs': [fixture()]}
        changed = guard()
        changed['results'][0]['function'] = 'GetName'
        sender = Mock(return_value=changed)
        with tempfile.TemporaryDirectory() as directory:
            result = RUNNER.run_design_plan(sender, plan, Path(directory) / 'guard.jsonl',
                                           deployed_source_hashes=lambda: plan['source_sha256'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['records'], [])
        self.assertEqual(result['native_functions_passed'], [])
        sender.assert_called_once()


class NumericFixtureOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jobs = NUMERIC.numeric_fixtures('numeric_offline')

    def find(self, name, **arguments):
        return next(job for job in self.jobs if job['name'] == name and job['arguments'] == arguments)

    def assert_result(self, job, expected):
        self.assertTrue(HOST.evaluate_native(job, response(job['name'], expected))[0], job['id'])

    def test_all_numeric_jobs_have_unique_ids_finite_assertions_and_valid_sdk_signatures(self):
        self.assertEqual(len({job['id'] for job in self.jobs}), len(self.jobs))
        self.assertEqual({job['fixture_family'] for job in self.jobs}, set(NUMERIC.FAMILIES))
        for job in self.jobs:
            with self.subTest(job=job['id']):
                self.assertEqual(job['native_status'], 'pending_not_executed')
                self.assertTrue(job['verification_dimension'])
                self.assertTrue(job['evidence_basis'])
                checked = RUNTIME.validate(job['name'], {'arguments': job['arguments']}, catalog=CATALOG)
                self.assertEqual(checked.get('status'), 'ok', checked)
                json.dumps(job, allow_nan=False)
                self.assert_result(job, job['assertions'][0]['equals'])

    def test_scalar_domain_spots_use_exact_independent_values(self):
        for name, arguments, expected in [
                ('Sqrt', {'v': 0.25}, 0.5), ('Sqr', {'v': -0.25}, 0.0625),
                ('Abs', {'v': -100.0}, 100.0), ('Sin', {'v': math.pi / 6}, 0.5),
                ('Cos', {'v': math.pi}, -1.0), ('Tan', {'v': -math.pi / 4}, -1.0),
                ('Ln', {'v': 1.0}, 0.0), ('Exp', {'v': 0.0}, 1.0),
                ('Round', {'v': -2.51}, -3), ('Trunc', {'v': -2.99}, -2),
                ('Min', {'val1': -8, 'val2': 3}, -8), ('Max', {'val1': -4, 'val2': -2}, -2)]:
            self.assert_result(self.find(name, **arguments), expected)

    def test_vector_domain_spots_distinguish_orientation_degrees_and_normalization(self):
        for name, arguments, expected in [
                ('Norm', {'Vec': [2, 3, 6]}, 7),
                ('UnitVec', {'Vect': [-3, -4, 0]}, [-0.6, -0.8, 0]),
                ('CrossProduct', {'v1': [0, 1, 0], 'v2': [1, 0, 0]}, [0, 0, -1]),
                ('DotProduct', {'v1': [1, 2, 3], 'v2': [-4, 5, -6]}, -12),
                ('AngBVec', {'v1': [1, 0, 0], 'v2': [0, 1, 0]}, 90),
                ('Ang2Vec', {'angleR': 270, 'Length': 5.0}, [0, -5, 0]),
                ('Perp', {'Vec': [-3, 4, 0]}, [4, 3, 0])]:
            self.assert_result(self.find(name, **arguments), expected)

    def test_coordinate_domain_spots_distinguish_distance_projection_and_tolerance(self):
        for name, arguments, expected in [
                ('Distance', {'x1': -8, 'y1': -6, 'x2': -5, 'y2': -2}, 5),
                ('Distance3D', {'x1': -5, 'y1': -5, 'z1': -5, 'x2': -3, 'y2': -2, 'z2': 1}, 7),
                ('Eq', {'value1': 1.0, 'value2': 1.011, 'tolerance': 0.01}, False),
                ('PtInRect', {'point': [-1, 5], 'rect1': [0, 10], 'rect2': [10, 0]}, False),
                ('PtOnLine', {'pt': [5, 0.005, 0], 'begPt': [0, 0, 0], 'endPt': [10, 0, 0], 'tolerance': 0.01}, True),
                ('PtPerpLine', {'pt': [-2, 4, 0], 'begPt': [0, 0, 0], 'endPt': [10, 0, 0]}, [-2, 0, 0])]:
            self.assert_result(self.find(name, **arguments), expected)

    def test_string_domains_have_independent_one_based_unicode_and_empty_oracles(self):
        for name, arguments, expected in [
                ('Len', {'v': '中 Ω'}, 3), ('Concat', {'txt': ''}, ''),
                ('Chr', {'v': 65}, 'A'), ('UniChr', {'v': 937}, 'Ω'),
                ('Copy', {'source': 'abcdef', 'index': 2, 'count': 3}, 'bcd'),
                ('Delete', {'source': 'abcdef', 'index': 2, 'count': 3}, 'aef'),
                ('Pos', {'subStr': 'ef', 'str': 'abcdef'}, 5),
                ('Pos', {'subStr': 'x', 'str': ''}, 0),
                ('SubString', {'text': 'red,green,blue', 'delimiter': ',', 'index': 2}, 'green'),
                ('Str2Num', {'s': '-42'}, -42)]:
            self.assert_result(self.find(name, **arguments), expected)
        self.assertTrue(all(job.get('execution_kind') == 'compatibility'
                            for job in self.jobs if job['name'] == 'UprString'))

    def test_explicit_encodings_distinguish_bytes_units_and_codepoints(self):
        jobs = NUMERIC.numeric_fixtures('encoding', ['string_encoding'])
        self.assertEqual(len(jobs), 16)
        self.assertEqual({j['arguments']['encoding'] for j in jobs}, {3, 4})
        for job in jobs:
            value, encoding = job['arguments']['v'], job['arguments']['encoding']
            # An independent codec checks the literal fixture table. UTF16-LE
            # omits a BOM; the SDK counts units rather than encoded byte size.
            expected = len(value.encode('utf-8')) if encoding == 3 else len(value.encode('utf-16-le')) // 2
            self.assert_result(job, expected)
            self.assertFalse(HOST.evaluate_native(job, response('LenEncoding', expected + 1))[0])
            self.assertFalse(HOST.evaluate_native(job, response('LenEncoding', True))[0])
        for encoding, expected in ((3, 6), (4, 4)):
            job = self.find('LenEncoding', v='A😀B', encoding=encoding)
            self.assert_result(job, expected)
            for wrong in (3, 4 if encoding == 3 else 6, 8):
                self.assertFalse(HOST.evaluate_native(job, response('LenEncoding', wrong))[0])

    def test_silent_wrong_radians_zero_sign_and_index_mutations_are_detected(self):
        mutations = [
            (self.find('Sin', v=math.pi / 6), math.sin(math.radians(math.pi / 6))),
            (self.find('Ang2Vec', angleR=90, Length=5.0), [5 * math.cos(90), 5 * math.sin(90), 0]),
            (self.find('AngBVec', v1=[1, 0, 0], v2=[0, 1, 0]), math.pi / 2),
            (self.find('Abs', v=-100.0), -100),
            (self.find('Trunc', v=-2.99), -3),
            (self.find('Norm', Vec=[2, 3, 6]), 0),
            (self.find('CrossProduct', v1=[0, 1, 0], v2=[1, 0, 0]), [0, 0, 1]),
            (self.find('Copy', source='abcdef', index=2, count=3), 'cde'),
            (self.find('Len', v='中 Ω'), 6),
            (self.find('Eq', value1=1.0, value2=1.011, tolerance=0.01), True),
        ]
        for job, wrong in mutations:
            with self.subTest(job=job['id']):
                self.assertFalse(HOST.evaluate_native(job, response(job['name'], wrong))[0])

    def test_small_nonzero_algebraic_values_reject_silent_zero_and_wrong_sign(self):
        for name in ('Abs', 'Sqr'):
            job = self.find(name, v=-1e-9)
            expected = 1e-9 if name == 'Abs' else 1e-18
            self.assertEqual(job['assertions'][0]['abs_tol'], 0)
            self.assert_result(job, expected)
            self.assert_result(job, expected * (1 + 1e-10))
            for wrong in (0, -expected, expected * 1.01, True):
                self.assertFalse(HOST.evaluate_native(job, response(name, wrong))[0])
        # Floating evaluation of sin(pi) need not return exact zero; preserve
        # the ordinary near-zero tolerance for this transcendental identity.
        job = self.find('Sin', v=math.pi)
        self.assertNotIn('abs_tol', job['assertions'][0])
        self.assert_result(job, 0.0)

    def test_family_selection_and_input_errors_are_deterministic(self):
        self.assertEqual(self.jobs, NUMERIC.numeric_fixtures('numeric_offline'))
        for family in NUMERIC.FAMILIES:
            self.assertEqual(NUMERIC.numeric_fixtures('numeric_offline', [family]),
                             [job for job in self.jobs if job['fixture_family'] == family])
        for families in ([], ['missing'], [NUMERIC.FAMILIES[0]] * 2):
            with self.assertRaises(ValueError):
                NUMERIC.numeric_fixtures('numeric_offline', families)
        for run_id in ('', 'space not valid', 'x' * 81, '../traversal', None, 1):
            with self.assertRaises(ValueError):
                NUMERIC.numeric_fixtures(run_id)


if __name__ == '__main__':
    unittest.main()
