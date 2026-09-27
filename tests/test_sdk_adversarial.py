"""Adversarial adapter tests, using deterministic independent fake host models.

These are transport/lifecycle tests, never evidence of native SDK semantics.
The generated matrix exercises every declared signature; this module instead
targets combinations, state transitions, swallowed callback errors and ownership
boundaries that a per-signature happy-path matrix does not establish.
"""
import copy
import importlib.util
import json
import math
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import Mock, patch
import uuid


ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNTIME = load('adversarial_runtime', 'vwx-plugin/sdk_runtime.py')
with patch.dict(sys.modules, {'sdk_runtime': RUNTIME}):
    SEQUENCES = load('adversarial_sequences', 'vwx-plugin/sdk_sequences.py')
CATALOG = json.loads((ROOT / 'vwx-plugin/sdk_catalog.json').read_text(encoding='utf-8'))
IDENTIFIER = '12345678-1234-4234-8234-123456789abc'
OTHER_IDENTIFIER = '87654321-4321-4321-8321-cba987654321'


def entry(parameters=(), returns=None, context=None, category='Test'):
    return {'parameters': [{'name': name, 'type': kind, 'required': True}
                           for name, kind in parameters],
            'returns': returns or {'kind': 'void'}, 'context': context or {},
            'category': category}


def catalog(**functions):
    return {'schema_version': 1, 'sdk_version': 3200, 'vectorworks_year': 2027,
            'functions': functions}


def call(name, **arguments):
    return {'name': name, 'arguments': arguments}


class RegistryHost:
    """A UUID/object registry whose lookup and identity checks are independent.

    Separate mappings let tests invalidate, replace or misresolve a handle
    between calls, without mocks that automatically bless every value as valid.
    """
    def __init__(self):
        self.by_uuid = {}
        self.by_handle = {}
        self.access = []
        self.first = self.add(IDENTIFIER, 3)
        self.second = self.add(OTHER_IDENTIFIER, 17)

    def add(self, identifier, kind):
        handle = object()
        self.by_uuid[identifier] = handle
        self.by_handle[handle] = (identifier, kind)
        return handle

    def GetVersion(self):
        self.access.append('version')
        return (32, 0, 0, 2)

    def GetObjectByUuid(self, identifier):
        self.access.append(('resolve', identifier))
        return self.by_uuid.get(identifier)

    def GetTypeN(self, handle):
        self.access.append(('type', handle))
        return self.by_handle.get(handle, ('', 0))[1]

    def GetObjectUuid(self, handle):
        self.access.append(('uuid', handle))
        return self.by_handle.get(handle, ('', 0))[0]


class SDKJsonAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.host = RegistryHost()

    def invoke(self, value, kind='ANY', target=None, returns=None):
        target = (lambda item: item) if target is None else target
        return RUNTIME.invoke('Echo', {'arguments': {'value': value}}, target,
                              vs_module=self.host,
                              catalog=catalog(Echo=entry([('value', kind)], returns or
                                             {'kind': 'scalar', 'type': kind})))

    def test_seeded_nested_json_roundtrips_against_json_library_oracle(self):
        rng = random.Random(20270926)

        def tree(depth):
            leaves = [None, False, True, '', 'Größe \u2603', '\x00\n', -2147483648,
                      2147483647, -0.0, 1e-200, 1e200, rng.randrange(-10000, 10000)]
            if depth == 0 or rng.randrange(3) == 0:
                return rng.choice(leaves)
            children = [tree(depth - 1) for _ in range(rng.randrange(5))]
            return ({'key_%d' % i: child for i, child in enumerate(children)}
                    if rng.randrange(2) else children)

        for number in range(100):
            value = tree(5)
            with self.subTest(seed_case=number):
                result = self.invoke(value)
                self.assertEqual(result['status'], 'ok', result)
                expected = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
                self.assertEqual(result['result'], expected)
                self.assertEqual(json.loads(json.dumps(result, allow_nan=False))['result'], expected)

    def test_shared_subtrees_are_not_cycles_and_native_mutation_does_not_alias_inputs(self):
        shared = {'points': [[1, 2], [3, 4]]}
        original = {'left': shared, 'right': shared}
        snapshot = copy.deepcopy(original)
        seen = []

        def mutate(value):
            seen.append(value)
            value['left']['points'][0][0] = 900
            self.assertEqual(value['right']['points'][0][0], 1)
            return value

        result = self.invoke(original, target=mutate)
        self.assertEqual(original, snapshot)
        self.assertEqual(result['result']['left']['points'][0][0], 900)
        seen[0]['left']['points'][0][0] = 901
        self.assertEqual(result['result']['left']['points'][0][0], 900)

    def test_cycles_at_multiple_depths_are_rejected_on_input_and_output(self):
        for depth in range(8):
            leaf = {}
            value = leaf
            for index in range(depth):
                value = {'nested_%d' % index: [value]}
            leaf['cycle'] = value
            with self.subTest(depth=depth):
                target = Mock(return_value=None)
                before = list(self.host.access)
                result = self.invoke(value, target=target)
                self.assertEqual(result['code'], 'SDK_TYPE')
                self.assertFalse(result['dispatched'])
                self.assertEqual(self.host.access, before)
                target.assert_not_called()
                result = self.invoke(None, target=lambda _: value)
                self.assertEqual(result['code'], 'SDK_RESULT')
                self.assertTrue(result['dispatched'])

    def test_every_nested_non_json_leaf_fails_without_stringifying_it(self):
        class Opaque:
            def __str__(self):
                raise AssertionError('An opaque value must not be stringified')
        bad_values = [Opaque(), {1: 'numeric key'}, {True: 'boolean key'}, b'bytes',
                      {1, 2}, complex(1, 2), math.nan, math.inf, -math.inf]
        for bad in bad_values:
            for wrap in (lambda x: x, lambda x: [x], lambda x: {'a': [0, {'b': x}]}):
                value = wrap(bad)
                with self.subTest(type=type(bad).__name__, depth=type(value).__name__):
                    target = Mock()
                    result = self.invoke(value, target=target)
                    self.assertIn(result['code'], ('SDK_TYPE', 'SDK_RANGE'))
                    target.assert_not_called()
                    result = self.invoke(None, target=lambda _: value)
                    self.assertEqual(result['code'], 'SDK_RESULT')
                    self.assertTrue(result['dispatched'])

    def test_integer_output_boundaries_reject_boolean_and_do_not_coerce(self):
        for kind, lower, upper in [('INTEGER', -32768, 32767),
                                   ('LONGINT', -2147483648, 2147483647),
                                   ('TEXTSTYLE', 0, 31)]:
            for value in [lower, upper, 0, lower - 1, upper + 1, True, False, 1.0, '1']:
                with self.subTest(kind=kind, value=value):
                    result = self.invoke(None, target=lambda _: value,
                                         returns={'kind': 'scalar', 'type': kind})
                    if type(value) is int and lower <= value <= upper:
                        self.assertEqual(result['result'], value)
                        self.assertIs(type(result['result']), int)
                    else:
                        self.assertEqual(result['code'], 'SDK_RESULT')
                        self.assertTrue(result['dispatched'])

    def test_point_and_color_bad_component_in_each_position_never_dispatches(self):
        for kind, size, good, invalid in [
                ('POINT', 2, 1.5, [True, None, math.nan, math.inf, '1', []]),
                ('POINT3D', 3, 1.5, [False, None, -math.inf, 10 ** 1000]),
                ('VECTOR', 3, -1.5, [True, {}, '0']),
                ('COLOR', 3, 65535, [True, -1, 65536, 1.0]),
                ('RGBCOLOR', 3, 0, [False, -1, 65536, 1.0])]:
            for index in range(size):
                for bad in invalid:
                    value = [good] * size
                    value[index] = bad
                    with self.subTest(kind=kind, component=index, bad=repr(bad)[:40]):
                        target = Mock()
                        result = self.invoke(value, kind, target=target)
                        self.assertIn(result['code'], ('SDK_TYPE', 'SDK_RANGE'))
                        self.assertFalse(result['dispatched'])
                        target.assert_not_called()

    def test_output_shape_failure_is_atomic_without_partial_named_outputs(self):
        returns = {'kind': 'tuple', 'items': [
            {'name': 'object', 'type': 'HANDLE'}, {'name': 'point', 'type': 'POINT'},
            {'name': 'value', 'type': 'REAL'}]}
        good = [self.host.first, [1, 2], 3.5]
        for index, bad in [(0, object()), (1, [1, True]), (2, math.inf)]:
            value = list(good)
            value[index] = bad
            result = self.invoke(None, target=lambda _: value, returns=returns)
            self.assertEqual(result['code'], 'SDK_RESULT')
            self.assertNotIn('result', result)
            self.assertNotIn('outputs', result)

    def test_duplicate_output_names_do_not_overwrite_or_drop_positional_values(self):
        returns = {'kind': 'tuple', 'items': [
            {'name': 'same', 'type': 'REAL'}, {'name': 'same', 'type': 'STRING'}]}
        result = self.invoke(None, target=lambda _: [1.25, 'second'], returns=returns)
        self.assertEqual(result['result'], [1.25, 'second'])
        self.assertNotIn('outputs', result)

    def test_handle_lookup_identity_mismatch_and_each_lookup_exception_do_not_dispatch(self):
        for method in ('GetObjectByUuid', 'GetTypeN', 'GetObjectUuid'):
            host = RegistryHost()
            setattr(host, method, Mock(side_effect=RuntimeError('stale native object')))
            target = Mock()
            result = RUNTIME.invoke('Use', {'arguments': {'h': IDENTIFIER}}, target,
                                    vs_module=host, catalog=catalog(Use=entry([('h', 'HANDLE')])))
            self.assertEqual(result['code'], 'SDK_HANDLE')
            self.assertFalse(result['dispatched'])
            target.assert_not_called()
        self.host.by_uuid[IDENTIFIER] = self.host.second
        target = Mock()
        result = self.invoke(IDENTIFIER, 'HANDLE', target=target)
        self.assertEqual(result['code'], 'SDK_HANDLE')
        target.assert_not_called()

    def test_seeded_uuid_normalization_preserves_identity(self):
        rng = random.Random(882699)
        for number in range(40):
            identifier = str(uuid.UUID(int=rng.getrandbits(128) or 1))
            handle = self.host.add(identifier, 3)
            variants = [identifier.upper(), '{' + identifier + '}', identifier.replace('-', '')]
            for variant in variants:
                result = self.invoke(variant, 'HANDLE')
                self.assertEqual(result['result'], identifier)
                self.assertIs(self.host.by_uuid[identifier], handle)

    def test_host_version_shape_and_lookup_errors_block_mutations(self):
        for version in (None, (), [], 32, '32', (True,), (32.0,), (31,), (33,), (2027,)):
            with self.subTest(version=version):
                self.host.GetVersion = Mock(return_value=version)
                target = Mock()
                result = self.invoke(None, target=target)
                self.assertEqual(result['code'], 'SDK_VERSION')
                self.assertFalse(result['dispatched'])
                target.assert_not_called()
        self.host.GetVersion = Mock(side_effect=RuntimeError('host unavailable'))
        target = Mock()
        result = self.invoke(None, target=target)
        self.assertEqual(result['code'], 'SDK_VERSION')
        self.assertFalse(result['dispatched'])
        target.assert_not_called()


COLLECTORS = {
    'ForEachObject': ('callback', {'c': '(ALL)'}, None, None),
    'ForEachMaterial': ('callback', {'onlyUsed': False}, None, None),
    'ForEachObjectInLayer': ('actionFunc', {'objOptions': 0, 'travOptions': 0, 'layerOptions': 0}, False, True),
    'ForEachObjectInList': ('actionFunc', {'objOptions': 0, 'travOptions': 0, 'list': IDENTIFIER}, False, True),
    'ForEachObjectAtPoint': ('actionFunc', {'objOptions': 0, 'travOptions': 0, 'loc': [0, 0], 'pickRadius': 1}, True, False),
}
DIALOGS = ('RunLayoutDialog', 'RunLayoutDialogN', 'RunNamedDialog', 'RunNamedDialogN')


class SDKCallbackAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.host = RegistryHost()

    def setup_call(self, name, descriptor=None):
        if name in COLLECTORS:
            parameter, arguments, keep, stop = COLLECTORS[name]
            arguments = dict(arguments)
            descriptor = descriptor or {'mode': 'collect', 'limit': 2}
            raw_result = None
        elif name in DIALOGS:
            parameter, arguments, keep, stop = 'callback', {'dialogID': 42}, None, None
            if name.endswith('N'):
                arguments['enableContextualHelp'] = False
            if 'Named' in name:
                arguments['contextualHelpID'] = ''
            descriptor = descriptor or {'mode': 'dialog'}
            raw_result = 2
        elif name in ('TrackObject', 'TrackObjectN'):
            parameter, arguments, keep, stop = 'callback', {}, True, False
            if name.endswith('N'):
                arguments['traverseType'] = 0
            descriptor = descriptor or {'mode': 'filter', 'object_types': [3], 'limit': 2}
            raw_result = (None, (0, 0, 0))
        else:
            parameter, arguments, keep, stop = 'callback', {'listID': 1, 'index': 1}, 1, 0
            descriptor = descriptor or {'mode': 'conflict', 'action': 'replace', 'limit': 2}
            raw_result = None
        arguments[parameter] = descriptor
        parameters = CATALOG['functions'][name]['parameters']
        cb_index = [p['name'] for p in parameters].index(parameter)
        return arguments, parameter, cb_index, raw_result, stop

    def invoke_trace(self, name, events, descriptor=None, native_error=None):
        arguments, parameter, index, raw, stop = self.setup_call(name, descriptor)
        saved, replies = [], []

        def native(*args):
            callback = args[index]
            saved.append(callback)
            for event in events:
                # Real native code may swallow callback exceptions. Reporting
                # success in that situation would conceal a broken callback ABI.
                try:
                    replies.append(callback(*event))
                except Exception:
                    replies.append('host swallowed callback exception')
            if native_error is not None:
                raise native_error
            return raw

        target = Mock(side_effect=native)
        response = RUNTIME.invoke(name, {'arguments': arguments}, target,
                                   vs_module=self.host, catalog=CATALOG)
        return response, saved, replies, parameter, stop, target

    def test_all_callback_protocols_zero_events_and_late_calls_are_inert(self):
        names = tuple(COLLECTORS) + DIALOGS + ('TrackObject', 'TrackObjectN', 'ImportResToCurFileN')
        for name in names:
            for native_error in (None, RuntimeError('native outer failure')):
                with self.subTest(name=name, native_error=bool(native_error)):
                    response, saved, _, parameter, stop, target = self.invoke_trace(name, [], native_error=native_error)
                    self.assertEqual(response.get('status', response.get('code')),
                                     'ok' if native_error is None else 'SDK_EXECUTION')
                    before = copy.deepcopy(response)
                    access = list(self.host.access)
                    if name in DIALOGS:
                        self.assertEqual(saved[0](2255, 0), 2255)
                    elif name == 'ImportResToCurFileN':
                        self.assertEqual(saved[0]('late resource'), 0)
                    else:
                        self.assertIs(saved[0](self.host.first), stop)
                    self.assertEqual(self.host.access, access)
                    self.assertEqual(response, before)
                    target.assert_called_once()

    def test_callback_arity_errors_survive_host_swallowing_them(self):
        names = tuple(COLLECTORS) + DIALOGS + ('TrackObject', 'TrackObjectN', 'ImportResToCurFileN')
        for name in names:
            wrong_events = [(), (self.host.first, 1, 2, 3)]
            for event in wrong_events:
                with self.subTest(name=name, arity=len(event)):
                    response, _, _, parameter, _, _ = self.invoke_trace(name, [event])
                    self.assertEqual(response.get('code'), 'SDK_RESULT', response)
                    self.assertTrue(response['dispatched'])
                    self.assertIn('error', response['callbacks'][parameter])

    def test_callback_named_positional_arity_is_preserved_for_native_introspection(self):
        # TrackObject documents one-, three- and four-argument callback forms.
        # The supported form stays visibly one positional parameter after the
        # malformed-call guard is installed; dialog callbacks retain two.
        names = tuple(COLLECTORS) + DIALOGS + ('TrackObject', 'TrackObjectN', 'ImportResToCurFileN')
        for name in names:
            with self.subTest(name=name):
                response, saved, _, _, _, _ = self.invoke_trace(name, [])
                self.assertEqual(saved[0].__code__.co_argcount, 2 if name in DIALOGS else 1)
                before = copy.deepcopy(response)
                host_access = list(self.host.access)
                saved[0]()
                saved[0](None, None, None, unexpected='late')
                self.assertEqual(response, before)
                self.assertEqual(self.host.access, host_access)

    def test_unexpected_callback_keyword_does_not_escape_failure_capture(self):
        names = tuple(COLLECTORS) + DIALOGS + ('TrackObject', 'TrackObjectN', 'ImportResToCurFileN')
        for name in names:
            args, parameter, index, raw, _ = self.setup_call(name)

            def native(*values):
                callback = values[index]
                positional = (2255, 0) if name in DIALOGS else ('A',) if name == 'ImportResToCurFileN' else (self.host.first,)
                try:
                    callback(*positional, unsupported_keyword=True)
                except Exception:
                    pass
                return raw

            result = RUNTIME.invoke(name, {'arguments': args}, native,
                                    vs_module=self.host, catalog=CATALOG)
            self.assertEqual(result['code'], 'SDK_RESULT', result)
            self.assertEqual(result['callbacks'][parameter]['count'], 0)

    def test_fatal_outer_exception_propagates_but_callback_lifetime_still_ends(self):
        for exception in (SystemExit('simulated fatal exit'), KeyboardInterrupt()):
            saved = []

            def native(callback, criteria):
                saved.append(callback)
                callback(self.host.first)
                raise exception

            args, _, _, _, _ = self.setup_call('ForEachObject')
            with self.assertRaises(type(exception)):
                RUNTIME.invoke('ForEachObject', {'arguments': args}, native,
                               vs_module=self.host, catalog=CATALOG)
            access = list(self.host.access)
            self.assertIsNone(saved[0](self.host.second))
            self.assertEqual(self.host.access, access)

    def test_callbacks_remain_captured_when_native_return_serialization_fails(self):
        saved = []

        def native(callback, criteria):
            saved.append(callback)
            callback(self.host.second)
            return 'invalid void result'

        args, _, _, _, _ = self.setup_call('ForEachObject')
        response = RUNTIME.invoke('ForEachObject', {'arguments': args}, native,
                                  vs_module=self.host, catalog=CATALOG)
        self.assertEqual(response['code'], 'SDK_RESULT')
        self.assertTrue(response['dispatched'])
        self.assertEqual(response['callbacks']['callback']['items'], [OTHER_IDENTIFIER])
        before = copy.deepcopy(response)
        saved[0](self.host.first)
        self.assertEqual(response, before)

    def test_collectors_keep_order_duplicates_and_nulls_even_if_host_ignores_stop(self):
        for name, (_, _, keep, stop) in COLLECTORS.items():
            with self.subTest(name=name):
                events = [(self.host.second,), (None,), (self.host.second,), (self.host.first,)]
                response, _, replies, parameter, _, _ = self.invoke_trace(name, events)
                self.assertEqual(response['status'], 'ok', response)
                self.assertEqual(replies, [keep, keep, stop, stop])
                self.assertEqual(response['callbacks'][parameter], {
                    'items': [OTHER_IDENTIFIER, None], 'count': 4, 'truncated': True})

    def test_collector_first_error_stays_visible_and_all_later_callbacks_request_stop(self):
        for name, (_, _, _, stop) in COLLECTORS.items():
            with self.subTest(name=name):
                events = [(object(),), (self.host.first,), (object(),)]
                response, _, replies, parameter, _, _ = self.invoke_trace(name, events)
                self.assertEqual(response['code'], 'SDK_RESULT')
                self.assertEqual(replies, [stop, stop, stop])
                self.assertIn('invalid HANDLE', response['callbacks'][parameter]['error']['message'])

    def test_filter_budget_caps_recording_without_changing_acceptance_policy(self):
        for name in ('TrackObject', 'TrackObjectN'):
            events = [(self.host.first,), (self.host.second,), (None,), (self.host.first,)]
            response, _, replies, parameter, _, _ = self.invoke_trace(name, events)
            self.assertEqual(response['status'], 'ok', response)
            self.assertEqual(replies, [True, False, False, True])
            self.assertEqual(response['callbacks'][parameter]['items'], [IDENTIFIER, OTHER_IDENTIFIER])
            self.assertEqual(response['callbacks'][parameter]['count'], 4)
            self.assertTrue(response['callbacks'][parameter]['truncated'])

    def test_filter_handle_failure_is_sticky_and_never_accepts_later_valid_object(self):
        for name in ('TrackObject', 'TrackObjectN'):
            response, _, replies, parameter, _, _ = self.invoke_trace(
                name, [(object(),), (self.host.first,), (self.host.second,)])
            self.assertEqual(response['code'], 'SDK_RESULT')
            self.assertEqual(replies, [False, False, False])
            self.assertTrue(response['dispatched'])

    def test_conflict_exact_budget_then_overflow_never_silently_replaces(self):
        for action, accepted in [('replace', 1), ('skip', 0)]:
            descriptor = {'mode': 'conflict', 'action': action, 'limit': 2}
            response, _, replies, parameter, _, _ = self.invoke_trace(
                'ImportResToCurFileN', [('A',), ('B',)], descriptor)
            self.assertEqual(response['status'], 'ok')
            self.assertEqual(replies, [accepted, accepted])
            response, _, replies, parameter, _, _ = self.invoke_trace(
                'ImportResToCurFileN', [('A',), ('B',), ('C',), ('D',)], descriptor)
            self.assertEqual(response['code'], 'SDK_RANGE')
            self.assertEqual(replies, [accepted, accepted, 0, 0])
            self.assertEqual(response['callbacks'][parameter]['items'], ['A', 'B'])
            self.assertEqual(response['callbacks'][parameter]['count'], 4)

    def test_bad_resource_name_disables_remaining_replacements_and_preserves_first_error(self):
        response, _, replies, parameter, _, _ = self.invoke_trace(
            'ImportResToCurFileN', [(object(),), ('valid after error',), (None,)])
        self.assertEqual(response['code'], 'SDK_RESULT')
        self.assertEqual(replies, [0, 0, 0])
        self.assertIn('declared string type', response['callbacks'][parameter]['error']['message'])

    def test_all_dialog_variants_resolve_each_numeric_reference_and_preserve_events(self):
        for name in DIALOGS:
            calls = []
            self.host.SetControlData = lambda *args: calls.append(args)
            descriptor = {'mode': 'dialog', 'events': {'2255': [call('SetControlData',
                dialogID={'$dialog': True}, itemID={'$event': 'item'}, data={'$event': 'data'})]}}
            response, _, replies, parameter, _, _ = self.invoke_trace(
                name, [(2255, -2147483648), (2, 0)], descriptor)
            self.assertEqual(response['status'], 'ok', response)
            self.assertEqual(calls, [(42, 2255, -2147483648)])
            self.assertEqual(replies, [2255, 2])
            self.assertEqual(response['callbacks'][parameter]['items'][0]['results'][0]['status'], 'ok')
            direct = RUNTIME.invoke('SetControlData', {'arguments': {
                'dialogID': 42, 'itemID': 2255, 'data': 0}}, vs_module=self.host, catalog=CATALOG)
            self.assertEqual(direct['code'], 'SDK_CONTEXT')
            self.assertEqual(len(calls), 1)

    def test_dialog_limit_error_preserves_event_and_prevents_control_execution(self):
        self.host.SetControlData = Mock(return_value=None)
        descriptor = {'mode': 'dialog', 'limit': 1, 'events': {'2255': [call('SetControlData',
            dialogID=42, itemID=4, data=8)]}}
        for name in DIALOGS:
            self.host.SetControlData.reset_mock()
            response, _, replies, _, _, _ = self.invoke_trace(
                name, [(0, 0), (2255, 0), (2, 0)], descriptor)
            self.assertEqual(response['code'], 'SDK_RANGE')
            self.assertEqual(replies, [0, 2255, 2])
            self.host.SetControlData.assert_not_called()

    def test_malformed_dialog_event_is_retained_as_error_without_running_control(self):
        self.host.SetControlData = Mock(return_value=None)
        descriptor = {'mode': 'dialog', 'events': {'2255': [call('SetControlData',
            dialogID=42, itemID=4, data=8)]}}
        for event in [(True, 0), (2255, False), (2147483648, 0), (2255, -2147483649), ('2255', 0)]:
            response, _, replies, _, _, _ = self.invoke_trace('RunLayoutDialog', [event, (2255, 0)], descriptor)
            self.assertEqual(response['code'], 'SDK_RESULT')
            self.assertEqual(replies, [event[0], 2255])
        self.host.SetControlData.assert_not_called()

    def test_dialog_failure_stops_remaining_controls_and_later_events(self):
        self.host.SetControlData = Mock(side_effect=RuntimeError('control failed'))
        descriptor = {'mode': 'dialog', 'events': {'2255': [
            call('SetControlData', dialogID=42, itemID=1, data=1),
            call('SetControlData', dialogID=42, itemID=2, data=2)]}}
        response, _, replies, parameter, _, _ = self.invoke_trace(
            'RunLayoutDialog', [(2255, 0), (2255, 0), (2, 0)], descriptor)
        self.assertEqual(response['code'], 'SDK_EXECUTION')
        self.assertEqual(replies, [2255, 2255, 2])
        self.host.SetControlData.assert_called_once_with(42, 1, 1)
        self.assertEqual(len(response['callbacks'][parameter]['items'][0]['results']), 1)

    def test_dialog_bad_event_keys_and_oversized_recipes_fail_before_host_access(self):
        controls = [call('SetControlData', dialogID=42, itemID=4, data=0)]
        recipes = [{key: controls} for key in ('01', '-0', '+1', ' 1', '1.0', '--1', '2147483648')]
        recipes += [{1: controls}, {'1': {}}, {'1': controls * 101}]
        for events in recipes:
            target = Mock()
            before = list(self.host.access)
            args, _, _, _, _ = self.setup_call('RunLayoutDialog', {'mode': 'dialog', 'events': events})
            result = RUNTIME.invoke('RunLayoutDialog', {'arguments': args}, target,
                                    vs_module=self.host, catalog=CATALOG)
            self.assertIn('error', result)
            self.assertFalse(result['dispatched'])
            target.assert_not_called()
            self.assertEqual(self.host.access, before)

    def test_all_callback_limits_reject_nonintegers_and_out_of_bounds_before_host_access(self):
        names = tuple(COLLECTORS) + DIALOGS + ('TrackObject', 'TrackObjectN', 'ImportResToCurFileN')
        for name in names:
            for limit in (False, True, 0, -1, 100001, 1.0, None, '5'):
                args, parameter, _, _, _ = self.setup_call(name)
                args[parameter]['limit'] = limit
                target = Mock()
                before = list(self.host.access)
                response = RUNTIME.invoke(name, {'arguments': args}, target,
                                          vs_module=self.host, catalog=CATALOG)
                self.assertIn(response['code'], ('SDK_TYPE', 'SDK_RANGE'))
                self.assertFalse(response['dispatched'])
                target.assert_not_called()
                self.assertEqual(self.host.access, before)

    def test_nested_invocation_has_independent_capture_and_callback_lifetime(self):
        saved, inner_results = [], []

        def outer(callback, criteria):
            saved.append(callback)
            callback(self.host.first)
            inner, inner_saved, _, _, _, _ = self.invoke_trace('ForEachMaterial', [(self.host.second,)])
            inner_results.append(inner)
            self.assertIsNone(inner_saved[0](self.host.first))
            callback(self.host.first)

        args, _, _, _, _ = self.setup_call('ForEachObject', {'mode': 'collect', 'limit': 10})
        response = RUNTIME.invoke('ForEachObject', {'arguments': args}, outer,
                                  vs_module=self.host, catalog=CATALOG)
        self.assertEqual(response['callbacks']['callback']['items'], [IDENTIFIER, IDENTIFIER])
        self.assertEqual(inner_results[0]['callbacks']['callback']['items'], [OTHER_IDENTIFIER])
        snapshot = copy.deepcopy(response)
        self.assertIsNone(saved[0](self.host.second))
        self.assertEqual(response, snapshot)


class SDKSequenceAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.host = RegistryHost()

    def run_plan(self, calls, definitions):
        return SEQUENCES.run({'calls': calls}, vs_module=self.host, catalog=definitions)

    def test_seeded_nested_scope_faults_match_independent_stack_model_without_replay(self):
        rng = random.Random(3200882699)
        definitions = catalog(Work=entry())
        for family in range(4):
            for role, prefix in [('begin', 'Open'), ('end', 'Close')]:
                definitions['functions'][prefix + str(family)] = entry(context={
                    'requires_sequence': True, 'scope_role': role, 'scope_family': str(family)})

        for plan_number in range(16):
            names, planned_stack = [], []
            for _ in range(rng.randrange(5, 18)):
                action = rng.randrange(3)
                if action == 0 or not planned_stack:
                    family = rng.randrange(4)
                    names.append('Open' + str(family))
                    planned_stack.append(family)
                elif action == 1:
                    names.append('Close' + str(planned_stack.pop()))
                else:
                    names.append('Work')
            names += ['Close' + str(family) for family in reversed(planned_stack)]
            plan = [call(name) for name in names]
            for failed_index in range(len(names)):
                entered, stack = [], []

                def native(name):
                    def execute():
                        entered.append(name)
                        if name.startswith('Open'):
                            stack.append(name[-1])
                        elif name.startswith('Close'):
                            self.assertEqual(stack.pop(), name[-1])
                        if len(entered) == failed_index + 1:
                            raise RuntimeError('failure after entering native API')
                    return execute

                for name in definitions['functions']:
                    setattr(self.host, name, native(name))
                expected_stack = []
                for name in names[:failed_index + 1]:
                    if name.startswith('Open'):
                        expected_stack.append(name[-1])
                    elif name.startswith('Close'):
                        expected_stack.pop()
                expected_cleanup = ['Close' + family for family in reversed(expected_stack)]
                with self.subTest(plan=plan_number, failed_step=failed_index):
                    result = self.run_plan(plan, definitions)
                    self.assertEqual(result['failed_step'], failed_index)
                    self.assertEqual(entered, names[:failed_index + 1] + expected_cleanup)
                    self.assertEqual([r['function'] for r in result['cleanup']], expected_cleanup)
                    self.assertEqual(stack, [])
                    self.assertTrue(result['dispatched'])

    def test_cleanup_failure_does_not_skip_outer_cleanup_or_retry_failed_end(self):
        events = []
        definitions = catalog()
        for name, role, family in [('A', 'begin', 'a'), ('Z', 'end', 'a'),
                                   ('B', 'begin', 'b'), ('Y', 'end', 'b')]:
            definitions['functions'][name] = entry(context={
                'requires_sequence': True, 'scope_role': role, 'scope_family': family})
        definitions['functions']['Work'] = entry()
        for name in definitions['functions']:
            def execute(name=name):
                events.append(name)
                if name in ('Work', 'Y'):
                    raise RuntimeError('failure in ' + name)
            setattr(self.host, name, execute)
        result = self.run_plan([call(n) for n in ['A', 'B', 'Work', 'Y', 'Z']], definitions)
        self.assertEqual(events, ['A', 'B', 'Work', 'Y', 'Z'])
        self.assertEqual([r.get('code', r.get('status')) for r in result['cleanup']], ['SDK_EXECUTION', 'ok'])

    def test_missing_native_step_cleans_only_entered_scopes_and_never_calls_later_mutation(self):
        events = []
        definitions = catalog(
            Open=entry(context={'requires_sequence': True, 'scope_role': 'begin', 'scope_family': 'g'}),
            Close=entry(context={'requires_sequence': True, 'scope_role': 'end', 'scope_family': 'g'}),
            Missing=entry(), Later=entry())
        self.host.Open = lambda: events.append('Open')
        self.host.Close = lambda: events.append('Close')
        self.host.Later = lambda: events.append('Later')
        result = self.run_plan([call(n) for n in ['Open', 'Missing', 'Later', 'Close']], definitions)
        self.assertEqual(events, ['Open', 'Close'])
        self.assertEqual(result['failed_step'], 1)
        self.assertFalse(result['results'][1]['dispatched'])
        self.assertTrue(result['dispatched'])

    def test_late_reference_shape_errors_preflight_whole_plan_without_host_access(self):
        definitions = catalog(Source=entry(returns={'kind': 'tuple', 'items': [
            {'name': 'p', 'type': 'POINT'}, {'name': 'ok', 'type': 'BOOLEAN'}]}),
            Use=entry([('value', 'REAL')]), Mutate=entry())
        invalid_paths = [[], ['status'], ['result'], ['result', -1], ['result', True],
                         ['result', 2], ['result', 0, -1], ['result', 0, 2],
                         ['result', 0, 0, 0], ['outputs', 'unknown'], ['outputs', 'ok'],
                         ['outputs', 'p', 'x'], ['outputs', 'p', True], ['result'] * 17]
        for path in invalid_paths:
            with self.subTest(path=path):
                result = self.run_plan([call('Mutate'), call('Source'),
                    call('Use', value={'$ref': 1, 'path': path})], definitions)
                self.assertIn('error', result)
                self.assertEqual(result['results'], [])
                self.assertFalse(result['dispatched'])
        self.assertEqual(self.host.access, [])

    def test_named_and_positional_point_components_references_produce_same_number(self):
        definitions = catalog(Source=entry(returns={'kind': 'tuple', 'items': [
            {'name': 'vector', 'type': 'POINT3D'}, {'name': 'rgb', 'type': 'COLOR'}]}),
            Use=entry([('value', 'REAL')], {'kind': 'scalar', 'type': 'REAL'}))
        self.host.Source = lambda: ([1.25, -2.5, 3.75], [0, 32768, 65535])
        observed = []
        self.host.Use = lambda value: observed.append(value) or value
        paths = []
        for item, name in enumerate(('vector', 'rgb')):
            for index in range(3):
                paths += [['result', item, index], ['outputs', name, index]]
        result = self.run_plan([call('Source')] + [call('Use', value={'$ref': 0, 'path': p}) for p in paths], definitions)
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(observed, [1.25, 1.25, -2.5, -2.5, 3.75, 3.75,
                                    0.0, 0.0, 32768.0, 32768.0, 65535.0, 65535.0])

    def test_null_handle_result_stops_dependent_setter_without_replaying_creator(self):
        definitions = catalog(Create=entry(returns={'kind': 'scalar', 'type': 'HANDLE'}),
                              Set=entry([('h', 'HANDLE')]), Later=entry())
        self.host.Create = Mock(return_value=None)
        self.host.Set = Mock()
        self.host.Later = Mock()
        result = self.run_plan([call('Create'), call('Set', h={'$ref': 0}), call('Later')], definitions)
        self.assertEqual(result['failed_step'], 1)
        self.assertTrue(result['dispatched'])
        self.assertEqual(result['results'][1]['code'], 'SDK_HANDLE')
        self.assertFalse(result['results'][1]['dispatched'])
        self.host.Create.assert_called_once()
        self.host.Set.assert_not_called()
        self.host.Later.assert_not_called()

    def test_deleted_and_reassigned_handle_reference_is_rechecked_before_mutating(self):
        definitions = catalog(Get=entry(returns={'kind': 'scalar', 'type': 'HANDLE'}),
                              Delete=entry(), Set=entry([('h', 'HANDLE')]))
        for replacement in (None, self.host.second):
            self.host.by_uuid[IDENTIFIER] = self.host.first
            self.host.Get = Mock(return_value=self.host.first)
            self.host.Delete = Mock(side_effect=lambda: self.host.by_uuid.__setitem__(IDENTIFIER, replacement))
            self.host.Set = Mock()
            result = self.run_plan([call('Get'), call('Delete'), call('Set', h={'$ref': 0})], definitions)
            self.assertEqual(result['failed_step'], 2)
            self.assertEqual(result['results'][2]['code'], 'SDK_HANDLE')
            self.host.Set.assert_not_called()
            self.host.Get.assert_called_once()
            self.host.Delete.assert_called_once()

    def test_two_hundred_step_boundary_preserves_order_and_rejects_two_hundred_one(self):
        observed = []
        definitions = catalog(Use=entry([('n', 'LONGINT')]))
        self.host.Use = lambda number: observed.append(number)
        plan = [call('Use', n=n) for n in range(200)]
        self.assertEqual(self.run_plan(plan, definitions)['status'], 'ok')
        self.assertEqual(observed, list(range(200)))
        observed.clear()
        before = list(self.host.access)
        result = self.run_plan(plan + [call('Use', n=200)], definitions)
        self.assertIn('error', result)
        self.assertEqual(observed, [])
        self.assertEqual(self.host.access, before)


if __name__ == '__main__':
    unittest.main()
