"""Same-job sequence lifecycle regressions using a fake host, never Vectorworks."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / 'vwx-plugin/sdk_catalog.json').read_text(encoding='utf-8'))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNTIME = load('sequence_test_runtime', 'vwx-plugin/sdk_runtime.py')
with patch.dict(sys.modules, {'sdk_runtime': RUNTIME}):
    SEQUENCES = load('sequence_test_runner', 'vwx-plugin/sdk_sequences.py')


class SDKSequenceTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.handle = object()
        self.uuid = '12345678-1234-4234-8234-123456789abc'
        self.host = SimpleNamespace(GetVersion=Mock(return_value=(32, 0, 0, 2)),
                                    GetObjectByUuid=Mock(return_value=self.handle),
                                    GetObjectUuid=Mock(return_value=self.uuid),
                                    GetTypeN=Mock(return_value=3))
        for name in ('BeginGroup', 'EndGroup', 'BeginPoly', 'EndPoly', 'AddPoint',
                     'BeginContext', 'EndContext', 'Rect'):
            self.bind(name)

    def bind(self, name, result=None, error=None):
        def call(*args):
            self.events.append((name, args))
            if error:
                raise error
            return result
        fn = Mock(side_effect=call)
        setattr(self.host, name, fn)
        return fn

    def run_plan(self, calls, **extra):
        return SEQUENCES.run({'calls': calls, **extra}, vs_module=self.host, catalog=CATALOG)

    @staticmethod
    def call(function, **arguments):
        return {'name': function, 'arguments': arguments}

    def test_balanced_nested_builders_run_serially_in_one_job(self):
        calls = [self.call('BeginGroup'), self.call('BeginPoly'),
                 self.call('AddPoint', p=[0, 0]), self.call('AddPoint', p=[10, 0]),
                 self.call('AddPoint', p=[10, 10]), self.call('EndPoly'), self.call('EndGroup')]
        result = self.run_plan(calls)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual([name for name, args in self.events], [call['name'] for call in calls])
        self.assertEqual(result['cleanup'], [])
        self.assertIn('after', result['regeneration_boundary'])

    def test_entire_plan_is_preflighted_before_any_host_operation(self):
        plans = [
            [self.call('BeginGroup'), self.call('Rect', p1=[1], p2=[3, 4]), self.call('EndGroup')],
            [self.call('BeginPoly'), self.call('EndGroup')],
            [self.call('BeginGroup')],
            [self.call('EndGroup')],
            [self.call('BeginGroup'), self.call('NotAnSdkApi'), self.call('EndGroup')],
        ]
        for calls in plans:
            with self.subTest(calls=calls):
                result = self.run_plan(calls)
                self.assertIn('error', result)
                self.assertEqual(result['results'], [])
        self.assertEqual(self.events, [])
        self.host.GetVersion.assert_not_called()

    def test_member_requires_matching_active_family(self):
        for calls in ([self.call('AddPoint', p=[0, 0])],
                      [self.call('BeginGroup'), self.call('AddPoint', p=[0, 0]), self.call('EndGroup')]):
            with self.subTest(calls=calls):
                self.assertIn('error', self.run_plan(calls))
        self.assertEqual(self.events, [])

    def test_forward_references_and_bad_paths_fail_before_mutation(self):
        references = [{'$ref': 1}, {'$ref': True}, {'$ref': -1}, {'$ref': 0, 'path': [-1]},
                      {'$ref': 0, 'path': 'result'}, {'$ref': 0, 'extra': True}]
        for reference in references:
            with self.subTest(reference=reference):
                calls = [self.call('Abs', v=2), self.call('Sqrt', v=reference)]
                self.assertIn('error', self.run_plan(calls))
        self.assertEqual(self.events, [])
        self.host.GetVersion.assert_not_called()

    def test_reference_destination_type_mismatch_rejected_in_preflight(self):
        calls = [self.call('Abs', v=2), self.call('GetName', h={'$ref': 0})]
        result = self.run_plan(calls)
        self.assertIn('error', result)
        self.assertEqual(self.events, [])
        self.host.GetVersion.assert_not_called()

    def test_uuid_result_reference_resolves_again_before_next_native_call(self):
        self.bind('CreateMaterial', self.handle)
        self.bind('GetName', 'Stone')
        calls = [self.call('CreateMaterial', name='Stone', isSimpleMaterial=True),
                 self.call('GetName', h={'$ref': 0})]
        result = self.run_plan(calls)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['results'][0]['result'], self.uuid)
        self.host.GetName.assert_called_once_with(self.handle)
        self.host.GetObjectByUuid.assert_called_once_with(self.uuid)

    def test_named_and_indexed_multi_output_references(self):
        self.bind('GetUnits', (0, 0, 0, 25.4, 'mm', 'mm2'))
        self.bind('Abs', 25.4)
        for path in (['result', 3], ['outputs', 'upi']):
            with self.subTest(path=path):
                calls = [self.call('GetUnits'), self.call('Abs', v={'$ref': 0, 'path': path})]
                self.assertEqual(self.run_plan(calls)['status'], 'ok')
        self.assertEqual(self.host.Abs.call_count, 2)
        self.host.Abs.assert_called_with(25.4)

    def test_stops_on_first_native_failure_and_closes_nested_scopes_once(self):
        self.bind('AddPoint', error=RuntimeError('native failure'))
        calls = [self.call('BeginGroup'), self.call('BeginPoly'), self.call('AddPoint', p=[0, 0]),
                 self.call('AddPoint', p=[1, 1]), self.call('EndPoly'), self.call('EndGroup')]
        result = self.run_plan(calls)
        self.assertEqual(result['failed_step'], 2)
        self.assertTrue(result['dispatched'])
        self.assertEqual([name for name, args in self.events],
                         ['BeginGroup', 'BeginPoly', 'AddPoint', 'EndPoly', 'EndGroup'])
        self.assertEqual([item['function'] for item in result['cleanup']], ['EndPoly', 'EndGroup'])
        self.host.AddPoint.assert_called_once()

    def test_begin_serialization_failure_closes_possible_scope_without_replaying_begin(self):
        self.bind('BeginGroup', result='unexpected procedure result')
        result = self.run_plan([self.call('BeginGroup'), self.call('EndGroup')])
        self.assertIn('error', result)
        self.assertTrue(result['dispatched'])
        self.assertEqual([name for name, args in self.events], ['BeginGroup', 'EndGroup'])
        self.assertEqual(len(result['cleanup']), 1)

    def test_failing_end_is_not_retried_when_native_dispatch_may_have_closed_it(self):
        self.bind('EndGroup', error=RuntimeError('uncertain end'))
        result = self.run_plan([self.call('BeginGroup'), self.call('EndGroup')])
        self.assertIn('error', result)
        self.host.EndGroup.assert_called_once()
        self.assertEqual(result['cleanup'], [])

    def test_end_context_cleanup_rejects_unfinished_context(self):
        self.bind('Rect', error=RuntimeError('failed drawing'))
        result = self.run_plan([self.call('BeginContext'),
                                self.call('Rect', p1=[0, 0], p2=[1, 1]),
                                self.call('EndContext', acceptOrReject=1)])
        self.assertIn('error', result)
        self.host.EndContext.assert_called_once_with(0)

    def test_limits_and_unknown_options_are_rejected_without_host_access(self):
        for params in ({'calls': []}, {'calls': [self.call('Abs', v=1)] * 201},
                       {'calls': [self.call('Abs', v=1)], 'options': {'force': 'yes'}},
                       {'calls': [self.call('Abs', v=1)], 'transaction': True}):
            self.assertIn('error', SEQUENCES.run(params, vs_module=self.host, catalog=CATALOG))
        self.assertEqual(self.events, [])

    def test_local_compatibility_before_undispatched_failure_does_not_claim_native_dispatch(self):
        result = self.run_plan([self.call('UprString', str='ascii'), self.call('Abs', v=1)])
        self.assertIn('error', result)
        self.assertFalse(result['dispatched'])
        self.assertFalse(result['results'][0]['native_dispatched'])
        self.assertFalse(result['results'][1]['dispatched'])
        self.assertEqual(self.events, [])

    def test_native_step_before_failure_remains_dispatched_in_mixed_sequence(self):
        self.bind('Abs', 1)
        result = self.run_plan([self.call('UprString', str='ascii'), self.call('Abs', v=1),
                                self.call('Sqrt', v=1)])
        self.assertIn('error', result)
        self.assertTrue(result['dispatched'])
        self.assertEqual([name for name, args in self.events], ['Abs'])


if __name__ == '__main__':
    unittest.main()
