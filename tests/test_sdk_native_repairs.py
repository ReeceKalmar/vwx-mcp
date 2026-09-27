"""Verified narrow compatibility repairs must expose their original evidence."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('sdk_native_repairs', ROOT / 'vwx-plugin/sdk_runtime.py')
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)
IDENTIFIER = '12345678-1234-4234-8234-123456789abc'


class NativeRepairTests(unittest.TestCase):
    def setUp(self):
        self.handle = object()
        self.host = SimpleNamespace(GetVersion=Mock(return_value=(32, 0, 0, 2)),
            GetObjectByUuid=Mock(return_value=self.handle), GetTypeN=Mock(return_value=10),
            GetObjectUuid=Mock(return_value=IDENTIFIER),
            GetTextLeading=Mock(return_value=0.0), GetTextSpace=Mock(return_value=2))

    def leading(self, identifier=IDENTIFIER):
        return RUNTIME.invoke('GetTextLeading', {'arguments': {'theText': identifier}}, vs_module=self.host)

    def test_noncustom_zero_leading_uses_confirmed_mode_and_discloses_native_value(self):
        for mode in (2, 3, 4):
            self.host.GetTextSpace.return_value = mode
            result = self.leading()
            self.assertEqual(result['result'], -1.0)
            self.assertEqual(result['compatibility']['native_result'], 0.0)
            self.assertEqual(result['compatibility']['spacing_mode'], mode)
            self.host.GetTextSpace.assert_called_with(self.handle)

    def test_custom_zero_and_valid_native_leading_are_preserved(self):
        self.host.GetTextSpace.return_value = 0
        result = self.leading()
        self.assertEqual(result['result'], 0)
        self.assertNotIn('compatibility', result)
        self.host.GetTextSpace.reset_mock()
        for value in (-1.0, 12.0, 18.5):
            self.host.GetTextLeading.return_value = value
            self.assertEqual(self.leading()['result'], value)
        self.host.GetTextSpace.assert_not_called()

    def test_opacity_output_order_is_repaired_only_on_measured_affected_build(self):
        self.host.GetVersionEx = Mock(return_value=(32, 0, 0, 2, 882075))
        self.host.GetOpacityByClassN = Mock()
        for pen, fill in ((False, False), (True, False), (False, True), (True, True)):
            self.host.GetOpacityByClassN.return_value = (fill, pen)
            result = RUNTIME.invoke('GetOpacityByClassN', {'arguments': {'h': IDENTIFIER}}, vs_module=self.host)
            self.assertEqual(result['result'], [pen, fill])
            self.assertEqual(result['compatibility']['native_result'], [fill, pen])
        for version in ((32, 0, 0, 2, 882076), (32, 0, 0, 1, 882075), (32, 1, 0, 2, 882075),
                        (32, 0, 0, 2, 882075.0), [32], None):
            self.host.GetVersionEx.return_value = version
            self.host.GetOpacityByClassN.return_value = (False, True)
            result = RUNTIME.invoke('GetOpacityByClassN', {'arguments': {'h': IDENTIFIER}}, vs_module=self.host)
            self.assertEqual(result['result'], [False, True])
            self.assertNotIn('compatibility', result)
        del self.host.GetVersionEx
        result = RUNTIME.invoke('GetOpacityByClassN', {'arguments': {'h': IDENTIFIER}}, vs_module=self.host)
        self.assertEqual(result['result'], [False, True])

    def text_length(self, native_value, text):
        self.host.GetVersionEx = Mock(return_value=(32, 0, 0, 2, 882075))
        self.host.GetTextLength = Mock(return_value=native_value)
        self.host.GetText = Mock(return_value=text)
        return RUNTIME.invoke('GetTextLength', {'arguments': {'TextHd': IDENTIFIER}}, vs_module=self.host)

    def test_text_length_uses_utf16_units_not_bytes_codepoints_or_graphemes(self):
        for text, byte_length, unit_length in [('', 0, 0), ('ABC', 3, 3), ('é', 2, 1),
                ('東', 3, 1), ('e\u0301', 3, 2), ('A😀B', 6, 4), ('\r\n', 2, 2),
                ('café 東京 😀 e\u0301 ' * 40, 880, 560)]:
            with self.subTest(text=text):
                result = self.text_length(byte_length, text)
                self.assertEqual(result['result'], unit_length)
                self.host.GetText.assert_called_once_with(self.handle)
                if byte_length != unit_length:
                    self.assertEqual(result['compatibility']['native_result'], byte_length)
                    self.assertEqual(result['compatibility']['result_unit'], 'utf16_code_units')
                    self.assertNotIn(text, repr(result['compatibility']))
                else:
                    self.assertNotIn('compatibility', result)
        result = self.text_length(4, 'A😀B')
        self.assertEqual(result['result'], 4)
        self.assertNotIn('compatibility', result)

    def test_text_length_never_guesses_for_mismatch_malformed_or_failed_helper(self):
        for raw, text in [(3, 'A😀B'), (0, 'ABC'), (6, None), (6, b'A')]:
            result = self.text_length(raw, text)
            self.assertEqual(result['code'], 'SDK_RESULT')
            self.assertNotIn('result', result)
            self.assertNotIn('compatibility', result)
        self.text_length(6, 'A😀B')
        for helper in (None, Mock(side_effect=RuntimeError('helper failed')), Mock(return_value='\ud800')):
            self.host.GetText = helper
            result = RUNTIME.invoke('GetTextLength', {'arguments': {'TextHd': IDENTIFIER}}, vs_module=self.host)
            self.assertIn('error', result)
            self.assertNotIn('result', result)
            self.assertNotIn('compatibility', result)

    def test_text_length_requires_measured_host_and_valid_text_object(self):
        self.text_length(6, 'A😀B')
        for version in ((32, 0, 0, 2, 882076), (32, 0, 0, 1, 882075), (32, 1, 0, 2, 882075),
                        (32, 0, 0, 2, 882075.0), [32], None):
            self.host.GetVersionEx.return_value = version
            self.host.GetText.reset_mock()
            result = RUNTIME.invoke('GetTextLength', {'arguments': {'TextHd': IDENTIFIER}}, vs_module=self.host)
            self.assertEqual(result['result'], 6)
            self.assertNotIn('compatibility', result)
            self.host.GetText.assert_not_called()
        del self.host.GetVersionEx
        self.assertEqual(RUNTIME.invoke('GetTextLength', {'arguments': {'TextHd': IDENTIFIER}}, vs_module=self.host)['result'], 6)
        self.host.GetVersionEx = Mock(return_value=(32, 0, 0, 2, 882075))
        self.host.GetTypeN.return_value = 3
        self.host.GetText.reset_mock()
        result = RUNTIME.invoke('GetTextLength', {'arguments': {'TextHd': IDENTIFIER}}, vs_module=self.host)
        self.assertEqual(result['result'], 6)
        self.assertNotIn('compatibility', result)
        self.host.GetText.assert_not_called()
        self.host.GetTypeN.return_value = 0
        self.host.GetTextLength.reset_mock()
        result = RUNTIME.invoke('GetTextLength', {'arguments': {'TextHd': IDENTIFIER}}, vs_module=self.host)
        self.assertEqual(result['code'], 'SDK_HANDLE')
        self.host.GetTextLength.assert_not_called()

    def test_text_length_repair_requires_exact_integer_text_type(self):
        for kind in (10.0, True, 3, '10'):
            for raw in (6, -1):
                with self.subTest(kind=kind, raw=raw):
                    self.host.GetTypeN.return_value = kind
                    result = self.text_length(raw, 'A😀B')
                    self.assertEqual(result['result'], raw)
                    self.assertNotIn('compatibility', result)
                    self.host.GetText.assert_not_called()

    def test_text_length_rejects_negative_counts_only_on_measured_text_path(self):
        for raw in (-1, -32768):
            with self.subTest(raw=raw):
                result = self.text_length(raw, 'A😀B')
                self.assertEqual(result['code'], 'SDK_RESULT')
                self.assertIs(result['dispatched'], True)
                self.assertNotIn('result', result)
                self.assertNotIn('compatibility', result)
                self.host.GetText.assert_not_called()
                self.host.GetTextLength.assert_called_once_with(self.handle)
                for version in ((32, 0, 0, 2, 882076), (32, 0, 0, 1, 882075), None):
                    self.host.GetVersionEx.return_value = version
                    result = RUNTIME.invoke('GetTextLength', {'arguments': {'TextHd': IDENTIFIER}},
                                            vs_module=self.host)
                    self.assertEqual(result['result'], raw)
                    self.assertNotIn('compatibility', result)
                    self.host.GetText.assert_not_called()

    def test_text_length_malformed_or_out_of_range_counts_bypass_repair_helpers(self):
        for raw in (-32769, 32768, True, False, 6.0, '6', None, [], {}):
            with self.subTest(raw=raw):
                result = self.text_length(raw, 'A😀B')
                self.assertEqual(result['code'], 'SDK_RESULT')
                self.assertIs(result['dispatched'], True)
                self.assertNotIn('result', result)
                self.assertNotIn('compatibility', result)
                self.host.GetVersionEx.assert_not_called()
                self.host.GetText.assert_not_called()

    def test_text_length_maximum_signed_count_preserves_valid_utf16_and_byte_cases(self):
        for text, expected, repaired in [('a'*32767, 32767, False),
                                         ('a'*32765 + 'é', 32766, True),
                                         ('a'*32765 + '😀', 32767, False)]:
            with self.subTest(expected=expected, repaired=repaired):
                result = self.text_length(32767, text)
                self.assertEqual(result['result'], expected)
                self.assertEqual('compatibility' in result, repaired)
                self.host.GetText.assert_called_once_with(self.handle)
                if repaired:
                    self.assertEqual(result['compatibility']['native_result'], 32767)
                    self.assertEqual(result['compatibility']['result_unit'], 'utf16_code_units')

    def test_material_false_status_requires_matching_valid_material_resource(self):
        material = object()
        material_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        self.host.GetObjMaterialName = Mock(return_value=(False, 'Copper'))
        self.host.GetObjMaterialHandle = Mock(return_value=material)
        self.host.GetName = Mock(return_value='Copper')
        self.host.GetTypeN.side_effect = lambda h: 19 if h is material else 3
        self.host.GetObjectUuid.side_effect = lambda h: material_id if h is material else IDENTIFIER
        def invoke():
            return RUNTIME.invoke('GetObjMaterialName', {'arguments': {'h': IDENTIFIER}}, vs_module=self.host)
        result = invoke()
        self.assertEqual(result['result'], [True, 'Copper'])
        self.assertEqual(result['compatibility']['native_result'], [False, 'Copper'])
        self.assertEqual(result['compatibility']['material_id'], material_id)
        for returned, actual_name, kind in ((None, 'Copper', 19), (material, 'Other', 19),
                                             (material, 'Copper', 16), (material, 'Copper', 0)):
            self.host.GetObjMaterialHandle.return_value = returned
            self.host.GetName.return_value = actual_name
            self.host.GetTypeN.side_effect = lambda h: kind if h is material else 3
            result = invoke()
            self.assertEqual(result['result'], [False, 'Copper'])
            self.assertNotIn('compatibility', result)
        self.host.GetObjMaterialName.return_value = (False, '')
        self.host.GetObjMaterialHandle.reset_mock()
        self.assertEqual(invoke()['result'], [False, ''])
        self.host.GetObjMaterialHandle.assert_not_called()

    def test_material_independent_failures_or_invalid_uuid_do_not_invent_success(self):
        self.host.GetObjMaterialName = Mock(return_value=(False, 'Copper'))
        self.host.GetObjMaterialHandle = Mock(side_effect=RuntimeError('native failed'))
        self.host.GetName = Mock(return_value='Copper')
        result = RUNTIME.invoke('GetObjMaterialName', {'arguments': {'h': IDENTIFIER}}, vs_module=self.host)
        self.assertIn('error', result)
        self.assertNotIn('result', result)
        self.assertNotIn('compatibility', result)

        material = object()
        self.host.GetObjMaterialHandle = Mock(return_value=material)
        self.host.GetTypeN.side_effect = lambda h: 19 if h is material else 3
        self.host.GetObjectUuid.side_effect = lambda h: '' if h is material else IDENTIFIER
        result = RUNTIME.invoke('GetObjMaterialName', {'arguments': {'h': IDENTIFIER}}, vs_module=self.host)
        self.assertEqual(result['code'], 'SDK_RESULT')
        self.assertNotIn('result', result)
        self.assertNotIn('compatibility', result)
        for helper in ('GetName', 'GetObjMaterialHandle'):
            prior = getattr(self.host, helper)
            setattr(self.host, helper, None)
            result = RUNTIME.invoke('GetObjMaterialName', {'arguments': {'h': IDENTIFIER}}, vs_module=self.host)
            self.assertEqual(result['code'], 'SDK_RESULT')
            self.assertNotIn('result', result)
            setattr(self.host, helper, prior)

    def test_opacity_invalid_native_outputs_are_not_reordered_into_success(self):
        self.host.GetVersionEx = Mock(return_value=(32, 0, 0, 2, 882075))
        self.host.GetOpacityByClassN = Mock()
        for value in (None, (), (True,), (True, False, True), (0, 1), 'False,True'):
            self.host.GetOpacityByClassN.return_value = value
            result = RUNTIME.invoke('GetOpacityByClassN', {'arguments': {'h': IDENTIFIER}}, vs_module=self.host)
            self.assertEqual(result['code'], 'SDK_RESULT')
            self.assertNotIn('result', result)
            self.assertNotIn('compatibility', result)
        self.host.GetVersionEx.assert_not_called()

    def test_material_valid_native_success_and_invalid_native_shapes_bypass_repair(self):
        self.host.GetObjMaterialName = Mock(return_value=(True, 'Copper'))
        self.host.GetObjMaterialHandle = Mock(side_effect=AssertionError('must not run'))
        result = RUNTIME.invoke('GetObjMaterialName', {'arguments': {'h': IDENTIFIER}}, vs_module=self.host)
        self.assertEqual(result['result'], [True, 'Copper'])
        self.assertNotIn('compatibility', result)
        for value in ((0, 'Copper'), (False, None), ('False', 'Copper'), (False,), None):
            self.host.GetObjMaterialName.return_value = value
            result = RUNTIME.invoke('GetObjMaterialName', {'arguments': {'h': IDENTIFIER}}, vs_module=self.host)
            self.assertEqual(result['code'], 'SDK_RESULT')
        self.host.GetObjMaterialHandle.assert_not_called()

    def test_native_null_handle_output_uses_exact_native_type_and_null_equality(self):
        class Handle:
            def __init__(self, pointer=0):
                self.pointer = pointer
            def __eq__(self, other):
                return type(other) is Handle and self.pointer == other.pointer
            def __bool__(self):
                return False  # Falsiness alone deliberately says nothing.
        self.host.Handle = Handle
        self.host.GetTypeN.side_effect = lambda h: 10 if h is self.handle else 0
        self.host.GetObjMaterialHandle = Mock(return_value=Handle())
        def invoke():
            return RUNTIME.invoke('GetObjMaterialHandle', {'arguments': {'h': IDENTIFIER}}, vs_module=self.host)
        self.assertIsNone(invoke()['result'])
        self.host.GetObjMaterialHandle.return_value = Handle(987)
        self.assertEqual(invoke()['code'], 'SDK_RESULT')
        class Liar:
            def __eq__(self, other):
                return True
        self.host.GetObjMaterialHandle.return_value = Liar()
        self.assertEqual(invoke()['code'], 'SDK_RESULT')
        self.host.Handle = Mock(side_effect=RuntimeError('native null construction failed'))
        self.assertEqual(invoke()['code'], 'SDK_RESULT')

    def test_native_null_handle_comparison_failures_remain_errors(self):
        class Handle:
            def __eq__(self, other):
                raise RuntimeError('invalid handle comparison')
        self.host.Handle = Handle
        self.host.GetTypeN.side_effect = lambda h: 10 if h is self.handle else 0
        self.host.GetObjMaterialHandle = Mock(return_value=Handle())
        result = RUNTIME.invoke('GetObjMaterialHandle', {'arguments': {'h': IDENTIFIER}}, vs_module=self.host)
        self.assertEqual(result['code'], 'SDK_RESULT')
        self.assertNotIn('result', result)

    def test_missing_malformed_or_failed_independent_read_does_not_invent_sentinel(self):
        for getter in (None, Mock(return_value=True), Mock(return_value='2'),
                       Mock(side_effect=RuntimeError('native read failed'))):
            self.host.GetTextSpace = getter
            result = self.leading()
            self.assertIn('error', result)
            self.assertNotIn('result', result)
            self.assertNotIn('compatibility', result)

    def test_wrong_output_count_preserves_bounded_numeric_evidence_without_success(self):
        self.host.GetGradientDataN = Mock(return_value=(True, 0.25, 0.4, 0, 0, 255, 71))
        result = RUNTIME.invoke('GetGradientDataN',
            {'arguments': {'gradient': IDENTIFIER, 'segmentIndex': 2}}, vs_module=self.host)
        self.assertEqual(result['code'], 'SDK_RESULT')
        self.assertIs(result['dispatched'], True)
        self.assertNotIn('result', result)
        self.assertEqual(result['details']['native_return'], {
            'container': 'tuple', 'expected_count': 6, 'actual_count': 7,
            'numeric_outputs': [True, 0.25, 0.4, 0, 0, 255, 71]})

    def test_native_error_diagnostics_never_stringify_handles_or_unbounded_values(self):
        class Opaque:
            def __repr__(self):
                raise AssertionError('Opaque native values must not be inspected')
        values = [(Opaque(),), ('unrelated text',), (float('nan'),), (float('inf'),),
                  (2 ** 54,), ([1, 2],), tuple(range(33))]
        for value in values:
            self.host.GetGradientDataN = Mock(return_value=value)
            result = RUNTIME.invoke('GetGradientDataN',
                {'arguments': {'gradient': IDENTIFIER, 'segmentIndex': 2}}, vs_module=self.host)
            self.assertEqual(result['code'], 'SDK_RESULT')
            self.assertNotIn('result', result)
            self.assertNotIn('numeric_outputs', result['details']['native_return'])
            self.assertEqual(result['details']['native_return']['actual_count'], len(value))

    def test_invalid_handle_or_malformed_native_result_never_reaches_repair(self):
        self.assertEqual(self.leading('invalid')['code'], 'SDK_HANDLE')
        self.host.GetTextLeading.assert_not_called()
        for value in (False, None, '0', float('nan'), float('inf')):
            self.host.GetTextLeading.return_value = value
            self.assertEqual(self.leading()['code'], 'SDK_RESULT')
        self.host.GetTextSpace.assert_not_called()


if __name__ == '__main__':
    unittest.main()
