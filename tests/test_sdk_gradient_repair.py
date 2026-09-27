"""Independent state and fault tests for the measured gradient binding repair.

These are offline adapter checks, never native Vectorworks pass evidence.
The substitute setter mutates only its input resource/spot; test expectations
are literal preservation and opacity oracles, not generated from runtime code.
"""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('sdk_gradient_repair_runtime', ROOT / 'vwx-plugin/sdk_runtime.py')
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)
TARGET_ID = '12345678-1234-4234-8234-123456789abc'
CONTROL_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
BASELINE = [0.25, 0.4, 19, 83, 151, 37]
SIBLING = [0.75, 0.6, 201, 37, 11, 71]


class GradientHost:
    def __init__(self):
        self.target = SimpleNamespace(uuid=TARGET_ID, kind=120, spots=[
            [0.0, 0.5, 255, 255, 255, 100], list(BASELINE), list(SIBLING),
            [1.0, 0.5, 0, 0, 0, 100]])
        self.control = SimpleNamespace(uuid=CONTROL_ID, kind=120, spots=[
            [0.0, 0.5, 255, 255, 255, 100], [0.3, 0.45, 23, 171, 41, 53],
            [1.0, 0.5, 0, 0, 0, 100]])
        self.writes = []
        self.events = []
        self.poison_original = True
        for name in ('GetVersion', 'GetVersionEx', 'GetObjectByUuid', 'GetObjectUuid', 'GetTypeN',
                     'GetNumGradientSegments', 'GetGradientDataN', 'GetGradientOpacity',
                     'SetGradientDataN', 'SetGradientOpacity'):
            setattr(self, name, Mock(wraps=getattr(self, name)))

    def GetVersion(self):
        return 32, 0, 0, 2

    def GetVersionEx(self):
        return 32, 0, 0, 2, 882075

    def GetObjectByUuid(self, identifier):
        return {TARGET_ID: self.target, CONTROL_ID: self.control}.get(identifier)

    def GetObjectUuid(self, obj):
        return obj.uuid

    def GetTypeN(self, obj):
        return obj.kind

    def GetNumGradientSegments(self, gradient):
        self.events.append('count')
        return len(gradient.spots)

    def GetGradientDataN(self, gradient, segmentIndex):
        self.events.append('data')
        return tuple(gradient.spots[segmentIndex - 1])

    def GetGradientOpacity(self, gradient, segmentIndex):
        self.events.append('opacity')
        return gradient.spots[segmentIndex - 1][5]

    def SetGradientDataN(self, gradient, segmentIndex, spotPosition, midpointPosition, red, green, blue, opacity):
        self.events.append('replacement')
        self.writes.append((gradient.uuid, segmentIndex, spotPosition, midpointPosition, red, green, blue, opacity))
        gradient.spots[segmentIndex - 1] = [spotPosition, midpointPosition, red, green, blue, opacity]
        return segmentIndex

    def SetGradientOpacity(self, gradient, segmentIndex, opacity):
        if self.poison_original:
            raise AssertionError('The known faulty native binding must never be called')
        self.events.append('original')
        gradient.spots[segmentIndex - 1][5] = opacity


class SDKGradientRepairTests(unittest.TestCase):
    def setUp(self):
        self.host = GradientHost()

    def invoke(self, opacity=0, index=2, identifier=TARGET_ID, named_callable=None):
        return RUNTIME.invoke('SetGradientOpacity', {'arguments': {
            'gradient': identifier, 'segmentIndex': index, 'opacity': opacity}},
            named_callable, vs_module=self.host)

    def assert_prewrite_failure(self, result):
        self.assertIn('error', result, result)
        self.assertNotIn('result', result)
        self.assertEqual(result['function'], 'SetGradientOpacity')
        self.assertIs(result['dispatched'], False, result)
        self.host.SetGradientOpacity.assert_not_called()
        self.host.SetGradientDataN.assert_not_called()
        self.assertEqual(self.host.writes, [])

    def assert_postwrite_failure(self, result):
        self.assertIn('error', result, result)
        self.assertNotIn('result', result)
        self.assertIn(result['code'], ('SDK_RESULT', 'SDK_EXECUTION'))
        self.assertIs(result['dispatched'], True, result)
        self.host.SetGradientOpacity.assert_not_called()
        self.assertEqual(self.host.SetGradientDataN.call_count, 1)

    def test_success_preserves_all_fields_siblings_and_other_resources_with_explicit_provenance(self):
        control = copy.deepcopy(self.host.control.spots)
        for opacity in (0, 100, 75, 1, 37):
            with self.subTest(opacity=opacity):
                result = self.invoke(opacity)
                self.assertEqual(result.get('status'), 'ok', result)
                self.assertIsNone(result['result'])
                self.assertEqual(result['function'], 'SetGradientOpacity')
                compatibility = result['compatibility']
                self.assertIs(compatibility['native_dispatched'], False)
                self.assertEqual(compatibility['native_function'], 'SetGradientOpacity')
                self.assertEqual(compatibility['replacement_function'], 'SetGradientDataN')
                self.assertEqual(compatibility['reason'], 'native_setter_changes_spot_position')
                self.assertEqual(compatibility['host_build'], 882075)
                self.assertEqual(self.host.target.spots[1], [0.25, 0.4, 19, 83, 151, opacity])
                self.assertEqual(self.host.target.spots[2], SIBLING)
                self.assertEqual(self.host.control.spots, control)
                self.host.SetGradientDataN.assert_called_with(self.host.target, 2, 0.25, 0.4, 19, 83, 151, opacity)
        self.assertEqual(len(self.host.writes), 5)
        self.host.SetGradientOpacity.assert_not_called()
        self.assertEqual(self.host.GetGradientDataN.call_count, 10)
        self.assertEqual(self.host.GetGradientOpacity.call_count, 10)
        first_write = self.host.events.index('replacement')
        self.assertIn('data', self.host.events[:first_write])
        self.assertIn('opacity', self.host.events[:first_write])

    def test_supplied_generated_callable_is_bypassed_and_original_may_be_missing(self):
        poison = Mock(side_effect=AssertionError('Generated native callable invoked'))
        result = self.invoke(named_callable=poison)
        self.assertEqual(result.get('status'), 'ok', result)
        poison.assert_not_called()
        self.host.SetGradientOpacity.assert_not_called()
        self.host.SetGradientOpacity = None
        result = self.invoke(100, named_callable=poison)
        self.assertEqual(result.get('status'), 'ok', result)
        poison.assert_not_called()

    def test_endpoints_and_minimum_two_segment_gradient_keep_each_field_exact(self):
        for index in (1, 4):
            with self.subTest(index=index):
                self.host = GradientHost()
                baseline = copy.deepcopy(self.host.target.spots)
                result = self.invoke(0, index)
                self.assertEqual(result.get('status'), 'ok', result)
                baseline[index - 1][5] = 0
                self.assertEqual(self.host.target.spots, baseline)
        self.host = GradientHost()
        self.host.target.spots = [[0.0, 1.0, 0, 255, 1, 0], [1.0, 0.0, 255, 0, 0, 100]]
        result = self.invoke(100, 1)
        self.assertEqual(result.get('status'), 'ok', result)
        self.assertEqual(self.host.target.spots, [[0.0, 1.0, 0, 255, 1, 100], [1.0, 0.0, 255, 0, 0, 100]])

    def test_only_exact_known_windows_identity_repairs_and_other_hosts_keep_original_dispatch(self):
        identities = [(32, 0, 0, 2, 882076), (32, 0, 0, 1, 882075), (32, 1, 0, 2, 882075),
                      (32, 0, 1, 2, 882075), (32, 0, 0, 2, 882075.0), (32, 0, False, 2, 882075),
                      (32, 0, 0, True, 882075), (32, 0, 0, 2), None, '32,0,0,2,882075']
        for version in identities:
            with self.subTest(version=version):
                self.host = GradientHost()
                self.host.poison_original = False
                self.host.GetVersionEx.return_value = version
                result = self.invoke(75)
                self.assertEqual(result.get('status'), 'ok', result)
                self.assertNotIn('compatibility', result)
                self.host.SetGradientOpacity.assert_called_once_with(self.host.target, 2, 75)
                self.host.GetGradientDataN.assert_not_called()
                self.host.GetGradientOpacity.assert_not_called()
                self.host.SetGradientDataN.assert_not_called()

    def test_missing_version_helper_keeps_native_path_but_throwing_identity_fails_without_write(self):
        self.host.poison_original = False
        self.host.GetVersionEx = None
        self.assertEqual(self.invoke(75).get('status'), 'ok')
        self.host.SetGradientOpacity.assert_called_once()
        self.host = GradientHost()
        self.host.GetVersionEx.side_effect = RuntimeError('identity unavailable')
        self.assert_prewrite_failure(self.invoke())

    def test_unknown_host_still_respects_supplied_callable(self):
        self.host.GetVersionEx.return_value = (32, 0, 0, 2, 882076)
        supplied = Mock(return_value=None)
        result = self.invoke(75, named_callable=supplied)
        self.assertEqual(result.get('status'), 'ok', result)
        supplied.assert_called_once_with(self.host.target, 2, 75)
        self.host.SetGradientOpacity.assert_not_called()
        self.host.SetGradientDataN.assert_not_called()

    def test_repair_requires_exact_native_gradient_type_and_uuid_resolution(self):
        for kind in (3, 0, True, 120.0, '120', None):
            with self.subTest(kind=kind):
                self.host = GradientHost()
                self.host.target.kind = kind
                self.assert_prewrite_failure(self.invoke())
        self.host = GradientHost()
        self.host.GetObjectByUuid.return_value = None
        self.assert_prewrite_failure(self.invoke())
        self.host = GradientHost()
        self.host.GetObjectUuid.return_value = CONTROL_ID
        self.assert_prewrite_failure(self.invoke())

    def test_requested_opacity_rejects_boolean_noninteger_and_out_of_percent_range_before_write(self):
        for opacity in (-32768, -1, 101, 32767, True, False, 1.0, '1', None, float('nan')):
            with self.subTest(opacity=opacity):
                self.host = GradientHost()
                self.assert_prewrite_failure(self.invoke(opacity))

    def test_index_and_native_segment_count_are_exact_valid_integers_before_reading(self):
        for index in (-1, 0, 5, 32767, True, 2.0, '2', None):
            with self.subTest(index=index):
                self.host = GradientHost()
                self.assert_prewrite_failure(self.invoke(index=index))
                self.host.GetGradientDataN.assert_not_called()
        for count in (0, -1, 1, 32768, True, 4.0, '4', None):
            with self.subTest(count=count):
                self.host = GradientHost()
                self.host.GetNumGradientSegments.return_value = count
                self.assert_prewrite_failure(self.invoke())
                self.host.GetGradientDataN.assert_not_called()

    def test_missing_or_raising_helpers_cannot_fall_back_to_faulty_original(self):
        for name in ('GetNumGradientSegments', 'GetGradientDataN', 'GetGradientOpacity', 'SetGradientDataN'):
            for helper in (None, Mock(side_effect=RuntimeError('helper failed'))):
                with self.subTest(name=name, helper=helper):
                    self.host = GradientHost()
                    setattr(self.host, name, helper)
                    result = self.invoke()
                    self.host.SetGradientOpacity.assert_not_called()
                    self.assertIn('error', result)
                    self.assertNotIn('result', result)
                    # A callable replacement that throws has already been
                    # dispatched; all missing/read-helper cases are pre-write.
                    self.assertIs(result['dispatched'], name == 'SetGradientDataN' and helper is not None)
                    self.assertEqual(self.host.writes, [])

    def test_baseline_requires_six_finite_typed_values_in_public_domains(self):
        malformed = [None, {}, 'bad', BASELINE[:5], [*BASELINE, 1], [True, *BASELINE]]
        for offset in (0, 1):
            for invalid in (True, -0.01, 1.01, float('nan'), float('inf'), '0.5', None):
                values = list(BASELINE)
                values[offset] = invalid
                malformed.append(values)
        for offset in (2, 3, 4):
            for invalid in (-1, 256, True, 19.0, '19', float('nan')):
                values = list(BASELINE)
                values[offset] = invalid
                malformed.append(values)
        for invalid in (-1, 101, True, 37.0, '37', None):
            malformed.append([*BASELINE[:5], invalid])
        for values in malformed:
            with self.subTest(values=values):
                self.host = GradientHost()
                self.host.GetGradientDataN.return_value = values
                self.assert_prewrite_failure(self.invoke())

    def test_independent_preflight_opacity_must_be_exact_and_agree(self):
        for value in (0, 36, 38, -1, 101, True, 37.0, None, '37'):
            with self.subTest(value=value):
                self.host = GradientHost()
                self.host.GetGradientOpacity.return_value = value
                self.assert_prewrite_failure(self.invoke())

    def test_replacement_exception_is_dispatched_once_and_never_retried_or_rolled_back(self):
        for changed_before_error in (False, True):
            with self.subTest(changed_before_error=changed_before_error):
                self.host = GradientHost()
                def fail(*args):
                    if changed_before_error:
                        GradientHost.SetGradientDataN(self.host, *args)
                    raise RuntimeError('replacement interrupted')
                self.host.SetGradientDataN.side_effect = fail
                result = self.invoke()
                self.assert_postwrite_failure(result)
                self.assertEqual(result['code'], 'SDK_EXECUTION')
                self.assertEqual(len(self.host.writes), int(changed_before_error))
                self.assertEqual(self.host.target.spots[1][5], 0 if changed_before_error else 37)

    def test_replacement_index_must_be_exact_requested_integer_even_after_mutation(self):
        for returned in (None, True, False, 2.0, '2', 0, 1, 3, 5, [2], (2,)):
            with self.subTest(returned=returned):
                self.host = GradientHost()
                def replace(*args):
                    GradientHost.SetGradientDataN(self.host, *args)
                    return returned
                self.host.SetGradientDataN.side_effect = replace
                self.assert_postwrite_failure(self.invoke())
                self.assertEqual(len(self.host.writes), 1)
                self.assertEqual(self.host.target.spots[1][5], 0)

    def test_postwrite_data_must_preserve_every_field_and_requested_opacity(self):
        expected = [0.25, 0.4, 19, 83, 151, 0]
        malformed = [None, expected[:5], [*expected, 1], [True, *expected]]
        for offset in range(6):
            values = list(expected)
            values[offset] += 0.000001 if offset < 2 else 1
            malformed.append(values)
            values = list(expected)
            values[offset] = True
            malformed.append(values)
        for values in malformed:
            with self.subTest(values=values):
                self.host = GradientHost()
                self.host.GetGradientDataN.side_effect = [tuple(BASELINE), values]
                self.assert_postwrite_failure(self.invoke())
                self.assertEqual(len(self.host.writes), 1)

    def test_postwrite_independent_opacity_mismatch_and_read_exceptions_are_not_success(self):
        for value in (37, 1, True, 0.0, None, '0'):
            with self.subTest(value=value):
                self.host = GradientHost()
                self.host.GetGradientOpacity.side_effect = [37, value]
                self.assert_postwrite_failure(self.invoke())
                self.assertEqual(len(self.host.writes), 1)
        for name in ('GetGradientDataN', 'GetGradientOpacity'):
            self.host = GradientHost()
            getattr(self.host, name).side_effect = [tuple(BASELINE) if name == 'GetGradientDataN' else 37,
                                                   RuntimeError('readback failed')]
            self.assert_postwrite_failure(self.invoke())
            self.assertEqual(len(self.host.writes), 1)

    def test_postwrite_resource_type_count_and_identity_changes_are_dispatched_errors(self):
        for kind in (0, 3, 120.0, True, '120'):
            with self.subTest(kind=kind):
                self.host = GradientHost()
                self.host.GetTypeN.side_effect = [120, 120, kind]
                self.assert_postwrite_failure(self.invoke())
                self.assertEqual(len(self.host.writes), 1)
        for count in (3, 5, True, 4.0, None):
            with self.subTest(count=count):
                self.host = GradientHost()
                self.host.GetNumGradientSegments.side_effect = [4, count]
                self.assert_postwrite_failure(self.invoke())
                self.assertEqual(len(self.host.writes), 1)
        for identifier in (CONTROL_ID, '', None, 'bad'):
            with self.subTest(identifier=identifier):
                self.host = GradientHost()
                self.host.GetObjectUuid.side_effect = [TARGET_ID, TARGET_ID, identifier]
                self.assert_postwrite_failure(self.invoke())
                self.assertEqual(len(self.host.writes), 1)

    def test_silent_noop_or_wrong_object_replacement_is_caught_by_later_state_read(self):
        for wrong_object in (False, True):
            with self.subTest(wrong_object=wrong_object):
                self.host = GradientHost()
                def replacement(gradient, index, *values):
                    if wrong_object:
                        GradientHost.SetGradientDataN(self.host, self.host.control, index, *values)
                    return index
                self.host.SetGradientDataN.side_effect = replacement
                self.assert_postwrite_failure(self.invoke())
                self.assertEqual(self.host.target.spots[1], BASELINE)


if __name__ == '__main__':
    unittest.main()
