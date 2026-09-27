"""JSON SDK contract tests with a fake host; no Vectorworks calls."""
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('sdk_runtime_test', ROOT / 'vwx-plugin/sdk_runtime.py')
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)
UUID = '12345678-1234-4234-8234-123456789abc'
OTHER_UUID = '87654321-4321-4321-8321-cba987654321'


class SDKRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.handle = object()
        self.host = SimpleNamespace(
            GetVersion=Mock(return_value=(32, 0, 0, 2)),
            GetObjectByUuid=Mock(return_value=self.handle),
            GetTypeN=Mock(return_value=3),
            GetObjectUuid=Mock(return_value=UUID),
        )
        self.call = Mock(return_value=None)

    def catalog(self, parameters=(), returns=None, context=None, name='Example'):
        return {'schema_version': 1, 'sdk_version': 3200, 'vectorworks_year': 2027,
                'functions': {name: {
                    'parameters': [{'name': key, 'type': typename, 'required': True}
                                   for key, typename in parameters],
                    'returns': returns or {'kind': 'void'}, 'context': context or {}}}}

    def invoke(self, parameters=(), arguments=None, returns=None, context=None,
               name='Example', options=None, invocation_context=None):
        return RUNTIME.invoke(name, {'arguments': arguments or {}, 'options': options or {}},
                              self.call, vs_module=self.host,
                              catalog=self.catalog(parameters, returns, context, name),
                              invocation_context=invocation_context)

    def test_primitive_values_are_converted_in_declared_order(self):
        params = [('b', 'BOOLEAN'), ('i', 'INTEGER'), ('l', 'LONGINT'),
                  ('r', 'REAL (Coordinate)'), ('s', 'STRING'), ('c', 'CHAR'),
                  ('p', 'POINT'), ('p3', 'POINT3D'), ('v', 'VECTOR'),
                  ('rgb', 'COLOR'), ('text', 'TEXTSTYLE'), ('criteria', 'CRITERIA')]
        arguments = dict(b=True, i=-32768, l=2147483647, r=1, s='é', c='é',
                         p=[1, 2], p3=[3, 4, 5], v=[0, 1, 0], rgb=[0, 65535, 257],
                         text=3, criteria='(ALL)')
        result = self.invoke(params, arguments)
        self.assertEqual(result['status'], 'ok')
        self.call.assert_called_once_with(True, -32768, 2147483647, 1.0, 'é', 'é',
                                          (1.0, 2.0), (3.0, 4.0, 5.0), (0.0, 1.0, 0.0),
                                          (0, 65535, 257), 3, '(ALL)')

    def test_invalid_primitives_are_rejected_before_host_access(self):
        cases = [('BOOLEAN', 1), ('INTEGER', True), ('INTEGER', 32768),
                 ('INTEGER', -32769), ('LONGINT', 2147483648), ('LONGINT', -2147483649),
                 ('REAL', True), ('REAL', float('nan')), ('REAL', float('inf')),
                 ('REAL', 10 ** 1000), ('STRING', 1), ('CHAR', ''), ('CHAR', 'ab'),
                 ('POINT', [1]), ('POINT3D', [1, 2]), ('VECTOR', [True, 0, 1]),
                 ('COLOR', [0, 1, 65536]), ('COLOR', [0, 1.0, 2]), ('TEXTSTYLE', 32)]
        for typename, value in cases:
            with self.subTest(type=typename, value=value):
                result = self.invoke([('value', typename)], {'value': value})
                self.assertIn(result['code'], ('SDK_TYPE', 'SDK_RANGE'))
                self.assertFalse(result['dispatched'])
        self.call.assert_not_called()
        self.host.GetVersion.assert_not_called()

    def test_missing_extra_and_malformed_envelope_are_rejected_first(self):
        catalog = self.catalog([('handle', 'HANDLE')], context={'unsupported_reason': 'native context'})
        for params in [[], {'handle': UUID}, {'arguments': []},
                       {'arguments': {}, 'options': {'force': 'yes'}},
                       {'arguments': {'wrong': 2}}]:
            with self.subTest(params=params):
                result = RUNTIME.invoke('Example', params, self.call,
                                        vs_module=self.host, catalog=catalog)
                self.assertEqual(result['code'], 'SDK_ARGUMENTS')
                self.assertFalse(result['dispatched'])

    def test_uuid_only_handles_are_resolved_and_read_back(self):
        result = self.invoke([('h', 'HANDLE')], {'h': UUID.upper()})
        self.assertEqual(result['status'], 'ok')
        self.call.assert_called_once_with(self.handle)
        self.host.GetObjectByUuid.assert_called_once_with(UUID)
        self.host.GetObjectUuid.assert_called_once_with(self.handle)
        for invalid in (1, True, self.handle, None, 'named object', '0' * 32):
            with self.subTest(value=invalid):
                self.assertEqual(self.invoke([('h', 'HANDLE')], {'h': invalid})['code'], 'SDK_HANDLE')

    def test_invalid_and_mismatched_resolved_handles_never_dispatch(self):
        self.host.GetTypeN.return_value = 0
        self.assertEqual(self.invoke([('h', 'HANDLE')], {'h': UUID})['code'], 'SDK_HANDLE')
        self.host.GetTypeN.return_value = 3
        self.host.GetObjectUuid.return_value = OTHER_UUID
        self.assertEqual(self.invoke([('h', 'HANDLE')], {'h': UUID})['code'], 'SDK_HANDLE')
        self.call.assert_not_called()

    def test_known_nullable_handle_only(self):
        self.call.return_value = self.handle
        result = self.invoke([('groupHandle', 'HANDLE')], {'groupHandle': None},
                             {'kind': 'scalar', 'type': 'HANDLE'},
                             name='BeginGroupN', context={'requires_sequence': True},
                             invocation_context={'sequence': True})
        self.assertEqual(result['result'], UUID)
        self.call.assert_called_once_with(None)

    def test_catalog_and_host_version_mismatch_never_dispatch(self):
        catalog = self.catalog()
        catalog['sdk_version'] = 3100
        self.assertEqual(RUNTIME.invoke('Example', {}, self.call, vs_module=self.host,
                                        catalog=catalog)['code'], 'SDK_VERSION')
        self.host.GetVersion.return_value = (31, 0, 0, 2)
        self.assertEqual(self.invoke()['code'], 'SDK_VERSION')
        self.call.assert_not_called()

    def test_context_and_force_contract(self):
        self.assertEqual(self.invoke(context={'requires_sequence': True})['code'], 'SDK_CONTEXT')
        self.assertEqual(self.invoke(context={'required_host_context': 'tool event'},
                                     options={'force': True})['code'], 'SDK_CONTEXT')
        self.assertEqual(self.invoke(context={'unsupported_reason': 'transient native handle'},
                                     options={'force': True})['code'], 'SDK_UNSUPPORTED')
        self.assertEqual(self.invoke(name='CombineIntoSurface')['code'], 'SDK_CONTEXT')
        self.assertEqual(self.invoke(name='CombineIntoSurface', options={'force': True})['status'], 'ok')

    def test_returned_handles_and_multivalues_preserve_structure(self):
        self.call.return_value = (True, self.handle, (1, 2), [4, 5, 6])
        returns = {'kind': 'tuple', 'items': [
            {'name': 'ok', 'type': 'BOOLEAN'}, {'name': 'object', 'type': 'HANDLE'},
            {'name': 'point', 'type': 'POINT'}, {'name': 'vector', 'type': 'VECTOR'}]}
        result = self.invoke(returns=returns)
        self.assertEqual(result['result'], [True, UUID, [1.0, 2.0], [4.0, 5.0, 6.0]])
        self.assertEqual(result['outputs']['object'], UUID)
        self.call.return_value = None
        self.assertIsNone(self.invoke(returns={'kind': 'scalar', 'type': 'HANDLE'})['result'])

    def test_serializer_never_stringifies_opaque_handles_or_drops_values(self):
        cases = [(object(), {'kind': 'scalar', 'type': 'ANY'}),
                 ({'nested': object()}, {'kind': 'scalar', 'type': 'ANY'}),
                 (math.inf, {'kind': 'scalar', 'type': 'REAL'}),
                 ((1,), {'kind': 'tuple', 'items': []}),
                 (1, {'kind': 'void'}), (1, {'kind': 'scalar', 'type': 'BOOLEAN'})]
        for value, returns in cases:
            with self.subTest(returns=returns):
                self.call.return_value = value
                result = self.invoke(returns=returns)
                self.assertEqual(result['code'], 'SDK_RESULT')
                self.assertTrue(result['dispatched'])
        self.call.return_value = self.handle
        self.host.GetObjectUuid.return_value = ''
        self.assertEqual(self.invoke(returns={'kind': 'scalar', 'type': 'HANDLE'})['code'], 'SDK_RESULT')

    def test_unknown_return_contract_is_rejected_before_native_call(self):
        result = self.invoke(returns={'kind': 'scalar', 'type': 'UNKNOWN'})
        self.assertEqual(result['code'], 'SDK_UNSUPPORTED')
        self.assertFalse(result['dispatched'])
        self.call.assert_not_called()

    def test_native_none_area_remains_a_contract_failure_not_zero(self):
        # Observed by the root live probe on a valid 2027 rectangle: HArea can
        # return None despite the SDK's REAL declaration. Preserve the failure.
        self.call.return_value = None
        result = self.invoke([('h', 'HANDLE')], {'h': UUID},
                             {'kind': 'scalar', 'type': 'REAL'}, name='HArea')
        self.assertEqual(result['code'], 'SDK_RESULT')
        self.assertTrue(result['dispatched'])
        self.assertNotIn('result', result)

    def test_json_arrays_validate_documented_elements_and_cycles(self):
        self.assertEqual(self.invoke([('tags', 'ARRAY')], {'tags': ['one', 'two']},
                                     name='SetResourceTags')['status'], 'ok')
        self.assertEqual(self.invoke([('tags', 'ARRAY')], {'tags': [1]},
                                     name='SetResourceTags')['code'], 'SDK_TYPE')
        self.assertEqual(self.invoke([('arrOptions', 'ARRAY')], {'arrOptions': ['one']},
                                     name='AlertInformDontShowAgain')['code'], 'SDK_RANGE')
        circular = []
        circular.append(circular)
        self.assertEqual(self.invoke([('a', 'ARRAY')], {'a': circular})['code'], 'SDK_TYPE')
        self.assertEqual(self.invoke([('a', 'ANY')], {'a': {1: 'value'}})['code'], 'SDK_TYPE')
        self.assertEqual(self.invoke([('nativePtr', 'ANY')], {'nativePtr': 123})['code'], 'SDK_UNSUPPORTED')

    def test_tag_arrays_use_documented_native_tuples_without_changing_json_input(self):
        # The official SetResourceTags reference links to SetObjectTags's
        # Python tuple example. A permissive Mock would miss this ABI mismatch.
        for name, handle_key, tags_key, returned in [
                ('SetResourceTags', 'handle', 'tags', None),
                ('SetObjectTags', 'objectHandle', 'arrTags', True)]:
            for source in [[], ['one'], ['fa\u00e7ade \u6771\u4eac', '', 'one', 'one'],
                           ('first', 'second')]:
                with self.subTest(function=name, tags=source):
                    seen = []

                    def native(handle, tags):
                        self.assertIs(handle, self.handle)
                        self.assertIs(type(tags), tuple)
                        self.assertEqual(tags, tuple(source))
                        seen.append(tags)
                        return returned

                    arguments = {handle_key: UUID, tags_key: source}
                    result = RUNTIME.invoke(name, {'arguments': arguments}, native,
                                            vs_module=self.host,
                                            catalog=RUNTIME.load_catalog())
                    self.assertEqual(result.get('status'), 'ok', result)
                    self.assertIs(result['result'], returned)
                    self.assertEqual(len(seen), 1)
                    self.assertIs(arguments[tags_key], source)
                    if type(source) is list:
                        snapshot = tuple(source)
                        source.append('changed after dispatch')
                        self.assertEqual(seen[0], snapshot)

    def test_tag_arrays_reject_nested_and_nonstring_values_before_host_access(self):
        circular = []
        circular.append(circular)
        for name, key in [('SetResourceTags', 'tags'), ('SetObjectTags', 'arrTags')]:
            for value in [None, 'one', [['nested']], [('nested',)], [{'tag': 'one'}],
                          ['valid', ['nested']], ['valid', None], [True], [1],
                          [b'bytes'], circular]:
                with self.subTest(function=name, value=value):
                    result = self.invoke([(key, 'ARRAY')], {key: value}, name=name)
                    self.assertEqual(result['code'], 'SDK_TYPE', result)
                    self.assertFalse(result['dispatched'])
        self.call.assert_not_called()
        self.host.GetVersion.assert_not_called()

    def test_other_array_native_arguments_keep_their_existing_list_contract(self):
        cases = [
            ('Example', 'tags', ['one', {'nested': [(1, 2), [3]]}],
             ['one', {'nested': [[1, 2], [3]]}]),
            ('SetResourceTags', 'unrelated', [(1, {'nested': [2]})],
             [[1, {'nested': [2]}]]),
            ('PopupSetChoices', 'popUpValues', ('one', 'two'), ['one', 'two']),
            ('AlertInformDontShowAgain', 'arrOptions', ('a', 'b', 'c'), ['a', 'b', 'c']),
        ]
        for name, key, original, expected in cases:
            with self.subTest(function=name, parameter=key):
                self.call.reset_mock()
                result = self.invoke([(key, 'ARRAY')], {key: original}, name=name)
                self.assertEqual(result['status'], 'ok', result)
                native_value = self.call.call_args.args[0]
                self.assertIs(type(native_value), list)
                self.assertEqual(native_value, expected)
                self.assertIsNot(native_value, original)
                if isinstance(native_value[-1], dict):
                    native_value[-1]['nested'].append('host mutation')
                    self.assertEqual(len(original[-1]['nested']), 2)

    def test_callback_collect_and_stop_conventions_are_api_specific(self):
        for name, param, keep_going, stop in [
                ('ForEachObject', 'callback', None, None),
                ('ForEachMaterial', 'callback', None, None),
                ('ForEachObjectInList', 'actionFunc', False, True),
                ('ForEachObjectInLayer', 'actionFunc', False, True),
                ('ForEachObjectAtPoint', 'actionFunc', True, False)]:
            with self.subTest(name=name):
                flags = []
                self.call.side_effect = lambda cb: flags.extend([cb(self.handle), cb(self.handle)])
                result = self.invoke([(param, 'PROCEDURE')],
                                     {param: {'mode': 'collect', 'limit': 1}}, name=name)
                self.assertEqual(flags, [keep_going, stop])
                self.assertEqual(result['callbacks'][param],
                                 {'items': [UUID], 'count': 2, 'truncated': True})

    def test_async_unknown_and_pointer_callbacks_are_never_dispatched(self):
        for name in ('RunTempTool', 'ResList_Filter', 'PDF_CreateBlob'):
            result = self.invoke([('callback', 'PROCEDURE')],
                                 {'callback': {'mode': 'collect'}}, name=name)
            self.assertEqual(result['code'], 'SDK_UNSUPPORTED')
            self.assertFalse(result['dispatched'])
        self.call.assert_not_called()

    def test_collector_callback_failures_survive_a_host_swallowing_exceptions(self):
        self.host.GetObjectUuid.return_value = 'bad-uuid'
        self.call.side_effect = lambda cb: cb(self.handle)
        response = self.invoke([('callback', 'PROCEDURE')],
                               {'callback': {'mode': 'collect'}}, name='ForEachMaterial')
        self.assertEqual(response['code'], 'SDK_RESULT')
        self.assertTrue(response['dispatched'])
        self.assertIn('error', response['callbacks']['callback'])

    def test_conflict_callback_only_uses_explicit_skip_or_replace_policy(self):
        for action, code in [('skip', 0), ('replace', 1)]:
            seen = []
            self.call.side_effect = lambda cb: seen.extend([cb('resource')])
            result = self.invoke([('callback', 'PROCEDURE')],
                                 {'callback': {'mode': 'conflict', 'action': action, 'limit': 1}},
                                 name='ImportResToCurFileN')
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(seen, [code])
        self.call.reset_mock()
        result = self.invoke([('callback', 'PROCEDURE')],
                             {'callback': {'mode': 'conflict', 'action': 'rename'}}, name='ImportResToCurFileN')
        self.assertEqual(result['code'], 'SDK_TYPE')
        self.call.assert_not_called()

    def test_track_object_filter_accepts_only_declared_types_and_limits(self):
        decisions = []
        self.call.side_effect = lambda cb: decisions.extend([cb(self.handle), cb(None), cb(self.handle)])
        result = self.invoke([('callback', 'PROCEDURE')],
                             {'callback': {'mode': 'filter', 'object_types': [3], 'limit': 2}},
                             name='TrackObject')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(decisions, [True, False, True])
        self.assertEqual(result['callbacks']['callback']['items'], [UUID, None])
        for kinds in ([], [True], [0], [32768], 'all'):
            self.call.reset_mock()
            result = self.invoke([('callback', 'PROCEDURE')],
                                 {'callback': {'mode': 'filter', 'object_types': kinds}}, name='TrackObject')
            self.assertIn(result['code'], ('SDK_TYPE', 'SDK_RANGE'))
            self.call.assert_not_called()

    def test_dialog_callback_grants_context_only_inside_handler_and_preserves_event(self):
        self.host.SetControlData = Mock(return_value=None)
        catalog = RUNTIME.load_catalog()
        seen = []
        def dialog(dialog_id, callback):
            seen.extend([callback(2255, 0), callback(1, 7)])
            return 1
        self.host.RunLayoutDialog = Mock(side_effect=dialog)
        arguments = {'dialogID': 42, 'callback': {'mode': 'dialog', 'events': {
            '2255': [{'name': 'SetControlData', 'arguments': {
                'dialogID': {'$dialog': True}, 'itemID': 4, 'data': {'$event': 'data'}}}]}}}
        result = RUNTIME.invoke('RunLayoutDialog', {'arguments': arguments}, vs_module=self.host, catalog=catalog)
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(seen, [2255, 1])
        self.host.SetControlData.assert_called_once_with(42, 4, 0)
        direct = RUNTIME.invoke('SetControlData', {'arguments': {'dialogID': 42, 'itemID': 4, 'data': 0}},
                                vs_module=self.host, catalog=catalog)
        self.assertEqual(direct['code'], 'SDK_CONTEXT')
        self.assertFalse(direct['dispatched'])

    def test_dialog_recipe_rejects_bad_later_calls_before_opening_dialog(self):
        catalog = RUNTIME.load_catalog()
        self.host.RunLayoutDialog = Mock()
        bad_calls = [
            {'name': 'Rect', 'arguments': {'p1': [0, 0], 'p2': [1, 1]}},
            {'name': 'RunLayoutDialog', 'arguments': {'dialogID': 1, 'callback': {'mode': 'dialog'}}},
            {'name': 'SetControlData', 'arguments': {'dialogID': {'$dialog': 1}, 'itemID': 4, 'data': 0}},
            {'name': 'SetControlData', 'arguments': {'dialogID': 1, 'itemID': True, 'data': 0}},
            {'name': 'SetControlData', 'arguments': {'dialogID': 1, 'itemID': 4}},
        ]
        for call in bad_calls:
            result = RUNTIME.invoke('RunLayoutDialog', {'arguments': {'dialogID': 42,
                'callback': {'mode': 'dialog', 'events': {'2255': [call]}}}},
                vs_module=self.host, catalog=catalog)
            self.assertIn('error', result, result)
            self.assertFalse(result['dispatched'])
        self.host.RunLayoutDialog.assert_not_called()

    def test_dialog_handler_failure_is_reported_and_does_not_dismiss_dialog(self):
        self.host.SetControlData = Mock(side_effect=RuntimeError('native control failure'))
        returned = []
        def dialog(dialog_id, callback):
            returned.extend([callback(2255, 0), callback(2, 0)])
            return 2
        self.host.RunLayoutDialog = Mock(side_effect=dialog)
        result = RUNTIME.invoke('RunLayoutDialog', {'arguments': {'dialogID': 42,
            'callback': {'mode': 'dialog', 'events': {'2255': [{'name': 'SetControlData',
                'arguments': {'dialogID': 42, 'itemID': 4, 'data': 0}}]}}}}, vs_module=self.host)
        self.assertEqual(result['code'], 'SDK_EXECUTION')
        self.assertTrue(result['dispatched'])
        self.assertEqual(returned, [2255, 2])
        self.assertIn('error', result['callbacks']['callback'])

    def test_callback_lifetime_ends_when_native_invocation_returns(self):
        saved = []
        self.call.side_effect = lambda callback: saved.append(callback)
        result = self.invoke([('callback', 'PROCEDURE')], {'callback': {'mode': 'collect'}},
                             name='ForEachMaterial')
        self.assertEqual(result['status'], 'ok')
        self.host.GetTypeN.reset_mock()
        self.host.GetObjectUuid.reset_mock()
        self.assertIsNone(saved[0](self.handle))
        self.host.GetTypeN.assert_not_called()
        self.host.GetObjectUuid.assert_not_called()
        self.assertEqual(result['callbacks']['callback']['count'], 0)

    def test_conflict_budget_failure_is_explicit_instead_of_silent_policy_change(self):
        codes = []
        self.call.side_effect = lambda cb: codes.extend([cb('resource'), cb('resource')])
        result = self.invoke([('callback', 'PROCEDURE')],
                             {'callback': {'mode': 'conflict', 'action': 'replace', 'limit': 1}},
                             name='ImportResToCurFileN')
        self.assertEqual(codes, [1, 0])
        self.assertEqual(result['code'], 'SDK_RANGE')
        self.assertTrue(result['dispatched'])

    def test_native_exception_is_reported_as_already_dispatched(self):
        self.call.side_effect = RuntimeError('native operation failed')
        result = self.invoke()
        self.assertEqual(result['code'], 'SDK_EXECUTION')
        self.assertTrue(result['dispatched'])

    def test_preflight_checks_literals_without_importing_or_calling_host(self):
        catalog = self.catalog([('p', 'POINT'), ('h', 'HANDLE')])
        result = RUNTIME.validate('Example', {'arguments': {'p': [1, 2], 'h': UUID}}, catalog=catalog)
        self.assertEqual(result['status'], 'ok')
        result = RUNTIME.validate('Example', {'arguments': {'p': [1, True], 'h': UUID}}, catalog=catalog)
        self.assertEqual(result['code'], 'SDK_TYPE')
        self.host.GetVersion.assert_not_called()
        self.call.assert_not_called()

    def test_preflight_reference_hook_does_not_apply_to_actual_invocation(self):
        catalog = self.catalog([('h', 'HANDLE')])
        params = {'arguments': {'h': {'$ref': 0}}}
        reference_validator = Mock(return_value=True)
        result = RUNTIME.validate('Example', params, catalog=catalog,
                                  reference_validator=reference_validator)
        self.assertEqual(result['status'], 'ok')
        reference_validator.assert_called_once_with({'$ref': 0}, catalog['functions']['Example']['parameters'][0])
        result = RUNTIME.invoke('Example', params, self.call, vs_module=self.host, catalog=catalog)
        self.assertEqual(result['code'], 'SDK_HANDLE')
        self.call.assert_not_called()

    def test_reference_hook_cannot_enable_unknown_callback_abi(self):
        catalog = self.catalog([('callback', 'PROCEDURE')], name='RunTempTool')
        result = RUNTIME.validate('RunTempTool', {'arguments': {'callback': {'$ref': 0}}},
                                  catalog=catalog, reference_validator=lambda *_: True)
        self.assertEqual(result['code'], 'SDK_UNSUPPORTED')


if __name__ == '__main__':
    unittest.main()
