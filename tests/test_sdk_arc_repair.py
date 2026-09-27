"""Independent offline state/fault tests for the measured arc binding repair.

The native extension itself needs separate ABI and live geometry verification.
These models prove adapter validation and no-replay behavior, not Vectorworks
compatibility. Expected angles and preserved fields are independent literals.
"""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('sdk_arc_repair_runtime', ROOT / 'vwx-plugin/sdk_runtime.py')
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)
TARGET_ID = '12345678-1234-4234-8234-123456789abc'
CONTROL_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'


class ArcHost:
    """Small document model with independently observable identity and angles."""

    def __init__(self):
        self.target = SimpleNamespace(uuid=TARGET_ID, kind=6, start=0.0, sweep=90.0,
                                      center=(31.0, -47.0), radii=(12.0, 8.0))
        self.control = SimpleNamespace(uuid=CONTROL_ID, kind=6, start=15.0, sweep=-70.0,
                                       center=(-22.0, 18.0), radii=(7.0, 3.0))
        self.writes = []
        self.events = []
        self.poison_original = True
        for name in ('GetVersion', 'GetVersionEx', 'GetObjectByUuid', 'GetObjectUuid',
                     'GetTypeN', 'GetArc', 'VWXBridgeRevision', 'VWXBridgeSetArc', 'SetArc'):
            setattr(self, name, Mock(wraps=getattr(self, name)))

    def GetVersion(self):
        return 32, 0, 0, 2

    def GetVersionEx(self):
        return 32, 0, 0, 2, 882075

    def GetObjectByUuid(self, identifier):
        return {TARGET_ID: self.target, CONTROL_ID: self.control}.get(identifier)

    def GetObjectUuid(self, obj):
        self.events.append('identity')
        return obj.uuid

    def GetTypeN(self, obj):
        self.events.append('type')
        return obj.kind

    def VWXBridgeRevision(self):
        self.events.append('revision')
        return 1

    def VWXBridgeSetArc(self, obj, start, sweep):
        self.events.append('replacement')
        self.writes.append((obj, start, sweep))
        obj.start, obj.sweep = start, sweep
        return 1

    def GetArc(self, obj):
        self.events.append('angles')
        return obj.start, obj.sweep

    def SetArc(self, obj, start, sweep):
        if self.poison_original:
            raise AssertionError('The measured broken Python binding must never run')
        self.events.append('original')
        obj.start, obj.sweep = start, sweep


class SDKArcRepairTests(unittest.TestCase):
    def setUp(self):
        self.host = ArcHost()

    def invoke(self, start=90, sweep=180, identifier=TARGET_ID, named_callable=None):
        return RUNTIME.invoke('SetArc', {'arguments': {
            'h': identifier, 'startAngle': start, 'arcAngle': sweep}},
            named_callable, vs_module=self.host)

    def assert_prewrite_failure(self, result):
        self.assertIn('error', result, result)
        self.assertNotIn('result', result)
        self.assertEqual(result['function'], 'SetArc')
        self.assertIs(result['dispatched'], False, result)
        self.host.SetArc.assert_not_called()
        if isinstance(self.host.VWXBridgeSetArc, Mock):
            self.host.VWXBridgeSetArc.assert_not_called()
        self.assertEqual(self.host.writes, [])

    def assert_postwrite_failure(self, result, code='SDK_RESULT'):
        self.assertIn('error', result, result)
        self.assertNotIn('result', result)
        self.assertEqual(result['function'], 'SetArc')
        self.assertEqual(result['code'], code, result)
        self.assertIs(result['dispatched'], True, result)
        self.host.SetArc.assert_not_called()
        self.host.VWXBridgeSetArc.assert_called_once()

    def test_success_uses_one_extension_call_and_discloses_bypassed_native_binding(self):
        named = Mock(side_effect=AssertionError('generated callable must be bypassed'))
        before_control = copy.deepcopy(vars(self.host.control))
        before_geometry = (self.host.target.center, self.host.target.radii)
        result = self.invoke(named_callable=named)
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['function'], 'SetArc')
        self.assertIsNone(result['result'])
        metadata = result['compatibility']
        self.assertEqual(metadata['native_function'], 'SetArc')
        self.assertEqual(metadata['replacement_function'], 'VWXBridgeSetArc')
        self.assertEqual(metadata['host_build'], 882075)
        self.assertEqual(metadata['helper_revision'], 1)
        self.assertIs(metadata['native_dispatched'], False)
        self.host.VWXBridgeRevision.assert_called_once_with()
        self.host.VWXBridgeSetArc.assert_called_once_with(self.host.target, 90.0, 180.0)
        args = self.host.VWXBridgeSetArc.call_args.args
        self.assertIs(type(args[1]), float)
        self.assertIs(type(args[2]), float)
        self.host.GetArc.assert_called_once_with(self.host.target)
        self.host.SetArc.assert_not_called()
        named.assert_not_called()
        self.assertEqual(self.host.writes, [(self.host.target, 90.0, 180.0)])
        self.assertEqual((self.host.target.start, self.host.target.sweep), (90, 180))
        self.assertEqual((self.host.target.center, self.host.target.radii), before_geometry)
        self.assertEqual(vars(self.host.control), before_control)
        self.assertGreater(self.host.events.index('angles'), self.host.events.index('replacement'))

    def test_extension_path_does_not_require_original_binding_to_exist(self):
        self.host.SetArc = None
        result = self.invoke()
        self.assertEqual(result.get('status'), 'ok', result)
        self.host.VWXBridgeSetArc.assert_called_once()

    def test_valid_negative_and_periodic_start_angles_preserve_sweep(self):
        cases = [(-90, -180, 270), (450, 90, 90), (-450, -90, 270),
                 (720, 360, 0), (0, 0, 360), (22.5, -37.25, 382.5)]
        for start, sweep, reported_start in cases:
            with self.subTest(start=start, sweep=sweep):
                self.host = ArcHost()
                self.host.GetArc.return_value = (reported_start, sweep)
                result = self.invoke(start, sweep)
                self.assertEqual(result.get('status'), 'ok', result)
                self.host.VWXBridgeSetArc.assert_called_once_with(self.host.target, float(start), float(sweep))

    def test_absolute_angle_tolerance_accepts_roundoff_but_not_geometry_change(self):
        for actual, accepted in [((90+5e-9, 180-5e-9), True),
                                 ((90+2e-8, 180), False),
                                 ((90, 180-2e-8), False),
                                 ((90, -180), False),
                                 ((90, 540), False)]:
            with self.subTest(actual=actual):
                self.host = ArcHost()
                self.host.GetArc.return_value = actual
                result = self.invoke()
                if accepted:
                    self.assertEqual(result.get('status'), 'ok', result)
                else:
                    self.assert_postwrite_failure(result)

    def test_start_wrap_boundary_is_periodic_but_zero_and_full_sweeps_are_distinct(self):
        for start, sweep, actual, accepted in [(0, 90, (360-5e-9, 90), True),
                (0, 90, (360-2e-8, 90), False), (0, 0, (0, 360), False),
                (0, 360, (0, 0), False), (0, -360, (0, 360), False)]:
            with self.subTest(start=start, sweep=sweep, actual=actual):
                self.host = ArcHost()
                self.host.GetArc.return_value = actual
                result = self.invoke(start, sweep)
                if accepted:
                    self.assertEqual(result.get('status'), 'ok', result)
                else:
                    self.assert_postwrite_failure(result)

    def test_large_sweep_does_not_enable_relative_tolerance(self):
        self.host.GetArc.return_value = (90, 1_000_000_000.001)
        self.assert_postwrite_failure(self.invoke(90, 1_000_000_000))

    def test_missing_or_noncallable_helpers_fail_before_mutation(self):
        for name in ('VWXBridgeRevision', 'VWXBridgeSetArc', 'GetArc'):
            for replacement in (None, 1, 'callable'):
                with self.subTest(name=name, replacement=replacement):
                    self.host = ArcHost()
                    setattr(self.host, name, replacement)
                    self.assert_prewrite_failure(self.invoke())

    def test_only_exact_integer_helper_revision_one_is_supported(self):
        for revision in (None, True, False, 1.0, '1', 0, 2, -1, [], {}):
            with self.subTest(revision=revision):
                self.host = ArcHost()
                self.host.VWXBridgeRevision.return_value = revision
                self.assert_prewrite_failure(self.invoke())
                self.host.GetArc.assert_not_called()

    def test_revision_exception_stops_before_mutation(self):
        self.host.VWXBridgeRevision.side_effect = RuntimeError('revision failed')
        self.assert_prewrite_failure(self.invoke())

    def test_preflight_requires_exact_arc_type_and_resolved_uuid_identity(self):
        for kind in (0, 3, 6.0, True, False, '6', None):
            with self.subTest(kind=kind):
                self.host = ArcHost()
                self.host.target.kind = kind
                self.assert_prewrite_failure(self.invoke())
        for actual_id in ('', 'not-a-uuid', '00000000-0000-0000-0000-000000000000', CONTROL_ID, None):
            with self.subTest(actual_id=actual_id):
                self.host = ArcHost()
                self.host.target.uuid = actual_id
                self.assert_prewrite_failure(self.invoke())
        self.host = ArcHost()
        self.host.GetObjectByUuid.return_value = None
        self.assert_prewrite_failure(self.invoke())

    def test_input_validation_rejects_bad_handles_and_nonfinite_or_boolean_angles(self):
        for identifier in (None, '', 'arc-name', '00000000-0000-0000-0000-000000000000', 3):
            with self.subTest(identifier=identifier):
                self.host = ArcHost()
                self.assert_prewrite_failure(self.invoke(identifier=identifier))
        for value in (True, False, None, '90', [], {}, float('nan'), float('inf'), -float('inf'), 10**400):
            for position in ('start', 'sweep'):
                with self.subTest(value=value, position=position):
                    self.host = ArcHost()
                    arguments = {position: value}
                    self.assert_prewrite_failure(self.invoke(**arguments))

    def test_nonaccepted_helper_status_is_dispatched_error_and_never_retried(self):
        for status in (None, True, False, 1.0, '1', 0, -1, -2, -3, -4, -5, 2, [], {}):
            with self.subTest(status=status):
                self.host = ArcHost()
                self.host.VWXBridgeSetArc.return_value = status
                self.assert_postwrite_failure(self.invoke())
                self.assertEqual(self.host.writes, [])
                self.host.GetArc.assert_not_called()

    def test_noop_and_stale_getter_cannot_be_reported_as_success(self):
        self.host.VWXBridgeSetArc.return_value = 1
        self.assert_postwrite_failure(self.invoke())
        self.assertEqual((self.host.target.start, self.host.target.sweep), (0, 90))
        self.host = ArcHost()
        self.host.GetArc.return_value = (0, 90)
        self.assert_postwrite_failure(self.invoke())
        self.assertEqual((self.host.target.start, self.host.target.sweep), (90, 180))
        self.assertEqual(len(self.host.writes), 1)

    def test_geometry_readback_requires_exact_pair_of_finite_nonboolean_numbers(self):
        malformed = [None, [], [90], [90, 180, 0], '90,180', {0: 90, 1: 180},
                     (True, 180), (90, False), ('90', 180), (90, None),
                     (float('nan'), 180), (90, float('inf')), (90, -float('inf')),
                     (10**400, 180), (90, 10**400)]
        for actual in malformed:
            with self.subTest(actual=actual):
                self.host = ArcHost()
                self.host.GetArc.return_value = actual
                self.assert_postwrite_failure(self.invoke())
                self.assertEqual(len(self.host.writes), 1)

    def test_postwrite_object_type_and_uuid_must_still_match_original(self):
        for field, value in [('kind', 0), ('kind', 3), ('kind', 6.0), ('kind', True),
                             ('uuid', CONTROL_ID), ('uuid', ''), ('uuid', None),
                             ('uuid', '00000000-0000-0000-0000-000000000000')]:
            with self.subTest(field=field, value=value):
                self.host = ArcHost()
                def mutate(obj, start, sweep):
                    ArcHost.VWXBridgeSetArc(self.host, obj, start, sweep)
                    setattr(obj, field, value)
                    return 1
                self.host.VWXBridgeSetArc.side_effect = mutate
                self.assert_postwrite_failure(self.invoke())
                self.assertEqual(len(self.host.writes), 1)

    def test_native_exception_after_mutation_is_uncertain_and_not_replayed(self):
        def mutate_then_raise(obj, start, sweep):
            ArcHost.VWXBridgeSetArc(self.host, obj, start, sweep)
            raise RuntimeError('native helper raised after write')
        self.host.VWXBridgeSetArc.side_effect = mutate_then_raise
        result = self.invoke()
        self.assert_postwrite_failure(result, 'SDK_EXECUTION')
        self.assertEqual(len(self.host.writes), 1)
        self.assertEqual((self.host.target.start, self.host.target.sweep), (90, 180))

    def test_getter_exception_after_mutation_keeps_dispatched_failure(self):
        self.host.GetArc.side_effect = RuntimeError('native getter raised')
        self.assert_postwrite_failure(self.invoke(), 'SDK_EXECUTION')
        self.assertEqual(len(self.host.writes), 1)

    def test_unknown_or_malformed_host_build_keeps_existing_native_path(self):
        versions = [(32, 0, 0, 2, 882076), (32, 0, 0, 1, 882075),
                    (32, 1, 0, 2, 882075), (32, 0, 0, 2, 882075.0),
                    (32, 0, 0, True, 882075), [32], None]
        for version in versions:
            with self.subTest(version=version):
                self.host = ArcHost()
                self.host.poison_original = False
                self.host.GetVersionEx.return_value = version
                result = self.invoke()
                self.assertEqual(result.get('status'), 'ok', result)
                self.assertNotIn('compatibility', result)
                self.host.SetArc.assert_called_once_with(self.host.target, 90, 180)
                self.host.VWXBridgeRevision.assert_not_called()
                self.host.VWXBridgeSetArc.assert_not_called()
                self.host.GetArc.assert_not_called()
        self.host = ArcHost()
        self.host.GetVersionEx = None
        named = Mock(return_value=None)
        result = self.invoke(named_callable=named)
        self.assertEqual(result.get('status'), 'ok', result)
        self.assertNotIn('compatibility', result)
        named.assert_called_once_with(self.host.target, 90, 180)
        self.host.VWXBridgeSetArc.assert_not_called()


if __name__ == '__main__':
    unittest.main()
