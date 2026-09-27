"""Obsolete HArea compatibility preserves units, failures and handle validation."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('sdk_compat_runtime', ROOT / 'vwx-plugin/sdk_runtime.py')
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)
UUID = '12345678-1234-4234-8234-123456789abc'


class AreaCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.handle = object()
        self.host = SimpleNamespace(
            GetVersion=Mock(return_value=(32, 0, 0, 2)),
            GetObjectByUuid=Mock(return_value=self.handle),
            GetTypeN=Mock(return_value=3),
            GetObjectUuid=Mock(return_value=UUID),
            HArea=Mock(return_value=None), HAreaN=Mock(return_value=600.0),
            ObjArea=Mock(return_value=600.0 / 144.0))

    def invoke(self, identifier=UUID):
        return RUNTIME.invoke('HArea', {'arguments': {'h': identifier}}, vs_module=self.host)

    def test_none_falls_back_once_using_same_validated_handle_and_reports_it(self):
        result = self.invoke()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['result'], 600.0)
        self.assertEqual(result['compatibility'], {
            'native_function': 'HArea', 'replacement_function': 'HAreaN',
            'reason': 'obsolete_native_returned_none'})
        self.host.HArea.assert_called_once_with(self.handle)
        self.host.HAreaN.assert_called_once_with(self.handle)
        # ObjArea uses area display units and is not an interchangeable fallback.
        self.host.ObjArea.assert_not_called()

    def test_valid_legacy_results_including_zero_are_preserved(self):
        for value in (0.0, 12.5, 600.0):
            with self.subTest(value=value):
                self.host.HArea.return_value = value
                result = self.invoke()
                self.assertEqual(result['result'], value)
                self.assertNotIn('compatibility', result)
        self.host.HAreaN.assert_not_called()

    def test_other_malformed_results_are_not_hidden(self):
        for value in (True, '600', float('nan'), float('inf'), [], {}):
            with self.subTest(value=value):
                self.host.HArea.return_value = value
                result = self.invoke()
                self.assertEqual(result['code'], 'SDK_RESULT')
                self.assertTrue(result['dispatched'])
                self.assertNotIn('compatibility', result)
        self.host.HAreaN.assert_not_called()

    def test_legacy_exception_is_not_retried(self):
        self.host.HArea.side_effect = RuntimeError('native error')
        result = self.invoke()
        self.assertEqual(result['code'], 'SDK_EXECUTION')
        self.host.HAreaN.assert_not_called()

    def test_invalid_or_stale_handles_never_reach_either_area_api(self):
        self.assertEqual(self.invoke('not-a-uuid')['code'], 'SDK_HANDLE')
        self.host.GetTypeN.return_value = 0
        self.assertEqual(self.invoke()['code'], 'SDK_HANDLE')
        self.host.HArea.assert_not_called()
        self.host.HAreaN.assert_not_called()

    def test_missing_or_invalid_replacement_preserves_disclosed_failure(self):
        for replacement in (None, Mock(return_value=None), Mock(return_value=True),
                            Mock(return_value=float('inf')), Mock(side_effect=RuntimeError('failed'))):
            with self.subTest(replacement=replacement):
                self.host.HAreaN = replacement
                result = self.invoke()
                self.assertIn(result['code'], ('SDK_RESULT', 'SDK_EXECUTION'))
                self.assertTrue(result['dispatched'])
                self.assertEqual(result['compatibility']['replacement_function'], 'HAreaN')
                self.assertNotIn('result', result)


if __name__ == '__main__':
    unittest.main()
