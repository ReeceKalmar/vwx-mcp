"""UprString compatibility is local ASCII conversion, never native verification."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('sdk_runtime_uppercase', ROOT / 'vwx-plugin/sdk_runtime.py')
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


class UppercaseCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.host = SimpleNamespace(GetVersion=Mock(return_value=(32, 0, 0, 2)))
        self.native = Mock(side_effect=AssertionError('Native UprString must never be retried'))

    def invoke(self, value, **kwargs):
        return RUNTIME.invoke('UprString', {'arguments': {'str': value}, **kwargs},
                              self.native, vs_module=self.host)

    def test_sdk_example_and_every_ascii_character_use_local_conversion(self):
        inputs = ['', 'Vectorworks', 'already UPPER 123!?', ''.join(chr(i) for i in range(128))]
        for value in inputs:
            result = self.invoke(value)
            expected = ''.join(chr(ord(c) - 32) if 'a' <= c <= 'z' else c for c in value)
            self.assertEqual(result['result'], expected)
            self.assertFalse(result['native_dispatched'])
            self.assertEqual(result['compatibility']['replacement_function'], 'python.str.upper')
            self.assertEqual(result['compatibility']['reason'], 'native_uncertain_outcome')
            self.assertEqual(result['compatibility']['scope'], 'ASCII only')
        self.native.assert_not_called()
        self.assertEqual(self.host.GetVersion.call_count, len(inputs))

    def test_unicode_semantics_are_explicitly_unsupported_even_with_force(self):
        for value in ['é', 'straße', 'ı', 'İ', 'σ', '\U0001f600']:
            result = self.invoke(value, options={'force': True})
            self.assertEqual(result['code'], 'SDK_UNSUPPORTED')
            self.assertFalse(result['dispatched'])
            self.assertIn('Unicode/locale', result['error'])
        self.host.GetVersion.assert_not_called()
        self.native.assert_not_called()

    def test_argument_type_validation_and_host_version_guard_are_preserved(self):
        for value in [None, 1, True, ['text']]:
            result = self.invoke(value)
            self.assertEqual(result['code'], 'SDK_TYPE')
            self.assertFalse(result['dispatched'])
        self.host.GetVersion.assert_not_called()
        self.host.GetVersion.return_value = (31, 0, 0, 2)
        self.assertEqual(self.invoke('abc')['code'], 'SDK_VERSION')
        self.native.assert_not_called()

    def test_native_attribute_is_never_even_resolved(self):
        class Host:
            def GetVersion(self):
                return (32, 0, 0, 2)

            @property
            def UprString(self):
                raise AssertionError('Native function attribute must not be resolved')

        result = RUNTIME.invoke('UprString', {'arguments': {'str': 'abc'}}, vs_module=Host())
        self.assertEqual(result['result'], 'ABC')
        self.assertFalse(result['native_dispatched'])

    def test_catalog_preserves_signature_and_discloses_native_warning(self):
        entry = RUNTIME.load_catalog()['functions']['UprString']
        self.assertEqual(entry['python_signature'], 'str = vs.UprString(str)')
        self.assertEqual([p['name'] for p in entry['parameters']], ['str'])
        self.assertEqual(entry['parameters'][0]['direction'], 'inout')
        self.assertEqual(entry['compatibility']['native_execution'], 'blocked')
        self.assertIn('Causation is unproven', entry['compatibility']['native_warning'])

    def test_sequence_reference_is_preflighted_then_actual_string_is_checked(self):
        result = RUNTIME.validate('UprString', {'arguments': {'str': {'$ref': 0}}},
                                  reference_validator=lambda *_: True)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(self.invoke('ascii')['result'], 'ASCII')
        self.assertEqual(self.invoke('ß')['code'], 'SDK_UNSUPPORTED')
        self.native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
