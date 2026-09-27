"""Offline checks for the guarded probe planner; no host is connected."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROBE = load('sdk_live_probe_test', ROOT / 'tools/sdk_live_probe.py')
RUNTIME = load('sdk_runtime_probe_test', ROOT / 'vwx-plugin/sdk_runtime.py')
UUID = '12345678-1234-4234-8234-123456789abc'


class SDKLiveProbeTests(unittest.TestCase):
    def test_all_fixture_calls_match_the_generated_catalog(self):
        catalog = json.loads((ROOT / 'vwx-plugin/sdk_catalog.json').read_text(encoding='utf-8'))
        plan = PROBE.build_plan('document', 'offline')
        captures = dict.fromkeys(('rectangle', 'polygon', 'text', 'worksheet'), UUID)
        for step in plan['steps']:
            calls = step.get('calls', [step.get('call')])
            for call in calls:
                with self.subTest(step=step['id'], function=call['name']):
                    args = PROBE._substitute(call['arguments'], captures)
                    result = RUNTIME.validate(call['name'], {'arguments': args}, catalog=catalog,
                                              invocation_context={'sequence': True},
                                              reference_validator=lambda value, _: isinstance(value, dict) and '$ref' in value)
                    self.assertNotIn('error', result, result)
            compile(PROBE.render_job(step, captures)['params']['code'], '<probe>', 'exec')

    def test_guard_rejects_real_document_before_any_generated_wrapper(self):
        commands = SimpleNamespace(sdk_call=Mock(), sdk_sequence=Mock())
        step = {'id': 'mutation', 'call': {'name': 'Rect', 'arguments': {'p1': [0, 1], 'p2': [1, 0]}}}
        source = PROBE.render_job(step)['params']['code']
        namespace = {'vs': SimpleNamespace(GetFName=lambda: 'Important client project.vwx')}
        with patch.dict(sys.modules, {'commands': commands}):
            exec(source, namespace)
        self.assertEqual(namespace['__result__']['code'], 'SDK_PROBE_DOCUMENT')
        commands.sdk_call.assert_not_called()
        commands.sdk_sequence.assert_not_called()

    def test_area_fixtures_use_verified_coordinate_unit_api(self):
        steps = PROBE.build_plan('document', 'offline')['steps']
        areas = [step for step in steps if step['id'].endswith('_area')]
        self.assertEqual(len(areas), 2)
        for step in areas:
            self.assertEqual(step['call']['name'], 'HAreaN')
            self.assertEqual(set(step['call']['arguments']), {'ObjectHandle'})

    def test_guarded_document_dispatches_wrapper_and_preserves_arguments(self):
        commands = SimpleNamespace(sdk_call=Mock(return_value={'status': 'ok', 'result': None}))
        text = "a'\n__import__('os')\n"
        step = {'id': 'text', 'call': {'name': 'CreateText', 'arguments': {'theText': text}}}
        namespace = {'vs': SimpleNamespace(GetFName=lambda: PROBE.DOCUMENT_PREFIX + 'offline.vwx')}
        with patch.dict(sys.modules, {'commands': commands}):
            exec(PROBE.render_job(step)['params']['code'], namespace)
        commands.sdk_call.assert_called_once_with(step['call'])
        self.assertEqual(namespace['__result__']['status'], 'ok')

    def test_pure_plan_uses_four_separate_jobs_and_records_assertions(self):
        sent = []
        responses = iter([{'status': 'ok', 'result': value} for value in [(32, 0, 0, 2), 12.5, 9.0, 0.0]])

        def send(job):
            sent.append(job)
            return {'output': '', 'error': None, 'result': next(responses)}

        result = PROBE.run_plan(send, PROBE.build_plan('pure', 'offline'))
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(len(sent), 4)
        self.assertTrue(all(record['assertion']['passed'] for record in result['records']))

    def test_failure_stops_without_retry_or_cleanup_mutations(self):
        sender = Mock(return_value={'error': 'uncertain host outcome', 'code': 'VW_DISPATCH_UNCONFIRMED'})
        result = PROBE.run_plan(sender, PROBE.build_plan('document', 'offline'))
        self.assertEqual(result['status'], 'failed')
        sender.assert_called_once()
        self.assertFalse(result['captures'])

    def test_prefix_cannot_be_disabled_and_inspection_is_a_separate_job(self):
        with self.assertRaises(ValueError):
            PROBE.render_job({'call': {'name': 'Rect', 'arguments': {}}}, document_prefix='')
        plan = PROBE.build_plan('document', 'offline')
        creation = next(step for step in plan['steps'] if step['id'] == 'create_rectangle')
        inspection = next(step for step in plan['steps'] if step['id'] == 'inspect_rectangle_bbox')
        self.assertNotEqual(creation, inspection)
        self.assertNotIn('GetBBox', [call['name'] for call in creation['calls']])
        self.assertNotIn('DelObject', json.dumps(plan))


if __name__ == '__main__':
    unittest.main()
