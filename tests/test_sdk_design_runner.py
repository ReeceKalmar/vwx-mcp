"""Typed-only execution guards and loss-of-response behavior, without a host."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = r'C:\SDK-tests\VWX-MCP-SDK-TEST-typed-offline.vwx'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = load('sdk_design_runner_guard_test', ROOT / 'tools/sdk_design_runner.py')


def plan():
    return {'schema_version': 1, 'run_id': 'typed_offline', 'document_path': DOCUMENT,
            'source_sha256': {name: 'a' * 64 for name in RUNNER.HOST.MODULE_FILES},
            'summary': {'native_cases': 2}, 'limitations': [],
            'jobs': [{'id': 'line_1', 'kind': 'native', 'name': 'MoveTo', 'arguments': {'p': [0, 0]},
                      'assertions': [{'path': ['result'], 'equals': None}]},
                     {'id': 'line_2', 'kind': 'native', 'name': 'LineTo', 'arguments': {'p': [30, 40]},
                      'assertions': [{'path': ['result'], 'equals': None}]}]}


def guard(path=DOCUMENT, version=32):
    return {'status': 'ok', 'count': 2, 'results': [
        {'status': 'ok', 'function': 'GetFPathName', 'result': path},
        {'status': 'ok', 'function': 'GetVersion', 'result': [version, 0, 0, 2]}]}


class SDKDesignRunnerTests(unittest.TestCase):
    def test_characterization_records_are_runnable_but_cannot_earn_semantic_passes(self):
        for kinds in (('characterization', 'characterization'), ('characterization', 'semantic')):
            p = plan()
            for fixture, kind in zip(p['jobs'], kinds):
                fixture['coverage_kind'] = kind
            sender = Mock(side_effect=[guard(), {'status': 'ok', 'function': 'MoveTo', 'result': None},
                                       guard(), {'status': 'ok', 'function': 'LineTo', 'result': None}])
            with tempfile.TemporaryDirectory() as directory:
                outcome = RUNNER.run_design_plan(sender, p, Path(directory)/'observations.jsonl',
                                                 deployed_source_hashes=lambda: p['source_sha256'])
            with self.subTest(kinds=kinds):
                self.assertEqual(outcome['status'], 'passed')
                expected_semantic = ['LineTo'] if kinds[1] == 'semantic' else []
                self.assertEqual(outcome['native_functions_passed'], expected_semantic)
                self.assertEqual(outcome['functions_all_planned_cases_passed'], expected_semantic)
                self.assertEqual(outcome['characterization_jobs_completed'], kinds.count('characterization'))
                self.assertEqual(outcome['characterization_native_functions_observed'],
                                 ['MoveTo'] if kinds[1] == 'semantic' else ['LineTo', 'MoveTo'])
                self.assertEqual([r['coverage_kind'] for r in outcome['records']], list(kinds))
                self.assertNotIn('GetVersion', outcome['characterization_native_functions_observed'])

    def test_legacy_characterization_marker_and_mixed_compatibility_sequence_stay_uncredited(self):
        p = plan()
        calls = [{'name': 'UprString', 'arguments': {'str': 'ascii'}}, {'name': 'Abs', 'arguments': {'v': -1}}]
        returned = [{'status': 'ok', 'function': 'UprString', 'result': 'ASCII',
                     'compatibility': {'replacement_function': 'python.str.upper'}},
                    {'status': 'ok', 'function': 'Abs', 'result': 1}]
        p['jobs'] = [{'id': 'observations', 'kind': 'native', 'calls': calls,
                      'verification_dimension': 'characterization',
                      'assertions': [{'path': ['results', 0, 'result'], 'equals': 'ASCII'}]}]
        sender = Mock(side_effect=[guard(), {'status': 'ok', 'count': 2, 'results': returned}])
        with tempfile.TemporaryDirectory() as directory:
            outcome = RUNNER.run_design_plan(sender, p, Path(directory)/'observations.jsonl',
                                             deployed_source_hashes=lambda: p['source_sha256'])
        self.assertEqual(outcome['status'], 'passed')
        self.assertEqual(outcome['native_functions_passed'], [])
        self.assertEqual(outcome['compatibility_functions_passed'], [])
        self.assertEqual(outcome['functions_all_planned_cases_passed'], [])
        self.assertEqual(outcome['characterization_native_functions_observed'], ['Abs'])
        self.assertEqual(outcome['characterization_compatibility_functions_observed'], ['UprString'])

    def test_invalid_or_removed_characterization_metadata_is_rejected_before_sender(self):
        for extra in ({'coverage_kind': 'semantic', 'verification_dimension': 'characterization'},
                      {'coverage_kind': None}, {'coverage_kind': False},
                      {'fixture_family': 'geometry:geometry_arc_characterization'}):
            p, sender = plan(), Mock()
            p['jobs'][1].update(extra)
            with tempfile.TemporaryDirectory() as directory, self.subTest(extra=extra), self.assertRaises(ValueError):
                RUNNER.run_design_plan(sender, p, Path(directory)/'bad.jsonl',
                                       deployed_source_hashes=lambda: p['source_sha256'])
            sender.assert_not_called()

    def test_hash_mismatch_and_missing_metadata_block_before_any_send(self):
        p = plan()
        for value in (None, {}, dict(p['source_sha256'], **{'sdk_runtime.py': 'b' * 64})):
            sender = Mock()
            with tempfile.TemporaryDirectory() as directory:
                result = RUNNER.run_design_plan(sender, p, Path(directory) / 'run.jsonl',
                                               deployed_source_hashes=lambda: value)
            self.assertEqual(result['status'], 'failed')
            self.assertIn('Deployed SDK files differ', result['error'])
            sender.assert_not_called()
            self.assertEqual(result['native_functions_passed'], [])

    def test_each_job_rechecks_deployment_and_document_before_mutation(self):
        p, sender = plan(), Mock(side_effect=[guard(), {'status': 'ok', 'function': 'MoveTo', 'result': None}, guard(path=r'C:\Client\Other.vwx')])
        hashes = Mock(return_value=p['source_sha256'])
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / 'run.jsonl'
            result = RUNNER.run_design_plan(sender, p, journal, deployed_source_hashes=hashes)
            events = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(hashes.call_count, 2)
        self.assertEqual(sender.call_count, 3)
        self.assertEqual(result['native_functions_passed'], ['MoveTo'])
        self.assertEqual(result['functions_all_planned_cases_passed'], ['MoveTo'])
        self.assertEqual([e['phase'] for e in events if e['event'] == 'intent'], ['guard', 'fixture', 'guard'])
        self.assertTrue(all(c.args[0]['command'] in {'sdk_call', 'sdk_sequence'} for c in sender.call_args_list))

    def test_wrong_year_prevents_mutation(self):
        p, sender = plan(), Mock(return_value=guard(version=31))
        with tempfile.TemporaryDirectory() as directory:
            result = RUNNER.run_design_plan(sender, p, Path(directory) / 'run.jsonl',
                                           deployed_source_hashes=lambda: p['source_sha256'])
        self.assertEqual(result['status'], 'failed')
        self.assertIn('2027', result['error'])
        self.assertEqual(sender.call_count, 1)

    def test_uncertain_native_result_is_not_a_failure_or_a_pass_and_never_replayed(self):
        p = plan()
        sender = Mock(side_effect=[guard(), {'error': 'Already claimed; unknown outcome',
                                           'code': 'VW_DISPATCH_UNCONFIRMED', 'cid': 'owned-123'}])
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / 'run.jsonl'
            result = RUNNER.run_design_plan(sender, p, journal, deployed_source_hashes=lambda: p['source_sha256'])
            with self.assertRaises(FileExistsError):
                RUNNER.run_design_plan(sender, p, journal, deployed_source_hashes=lambda: p['source_sha256'])
            events = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(result['status'], 'uncertain')
        self.assertIsNone(result['records'][0]['passed'])
        self.assertIsNone(result['records'][0]['native_api_executed'])
        self.assertEqual(result['records'][0]['result']['cid'], 'owned-123')
        self.assertEqual(result['native_functions_passed'], [])
        self.assertEqual(sender.call_count, 2)
        self.assertEqual(next(e for e in events if e['event'] == 'stop')['detail']['cid'], 'owned-123')

    def test_lost_response_after_dispatch_stops_uncertain(self):
        p, sender = plan(), Mock(side_effect=[guard(), TimeoutError('response lost')])
        with tempfile.TemporaryDirectory() as directory:
            result = RUNNER.run_design_plan(sender, p, Path(directory) / 'run.jsonl',
                                           deployed_source_hashes=lambda: p['source_sha256'])
        self.assertEqual(result['status'], 'uncertain')
        self.assertEqual(result['uncertain_job'], 'line_1')
        self.assertEqual(sender.call_count, 2)
        self.assertEqual(result['native_functions_passed'], [])

    def test_unclaimed_fixture_and_guard_preserve_transport_code_without_replay_or_sdk_credit(self):
        for code in RUNNER.HOST.UNCLAIMED_TRANSPORT_CODES:
            for explicit in (False, True):
                for phase in ('guard', 'fixture'):
                    p = plan()
                    response = {'error': 'Queue file removed before claim', 'code': code, 'cid': 'unclaimed'}
                    if explicit:
                        response['dispatched'] = False
                    sender = Mock(side_effect=[response] if phase == 'guard' else [guard(), response])
                    with self.subTest(code=code, explicit=explicit, phase=phase), tempfile.TemporaryDirectory() as directory:
                        journal = Path(directory) / 'run.jsonl'
                        result = RUNNER.run_design_plan(sender, p, journal, deployed_source_hashes=lambda: p['source_sha256'])
                        events = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
                        self.assertEqual(result['status'], 'blocked')
                        self.assertEqual(result['error_code'], code)
                        self.assertNotIn('uncertain_job', result)
                        self.assertEqual(sender.call_count, 1 if phase == 'guard' else 2)
                        self.assertEqual(result['native_functions_passed'], [])
                        self.assertEqual(result['compatibility_functions_passed'], [])
                        self.assertEqual(result['functions_all_planned_cases_passed'], [])
                        if phase == 'guard':
                            self.assertEqual(result['records'], [])
                        else:
                            recorded = result['records'][0]
                            self.assertIsNone(recorded['passed'])
                            self.assertIs(recorded['native_api_executed'], False)
                            self.assertEqual(recorded['result'], response)
                            self.assertNotIn('function_executions', recorded)
                        self.assertEqual(next(e for e in events if e['event'] == 'stop')['detail'], response)

    def test_transport_classifier_never_overrides_claim_uncertainty_or_successful_compatibility(self):
        classify = RUNNER.HOST.transport_outcome
        for code in RUNNER.HOST.UNCERTAIN_TRANSPORT_CODES:
            self.assertEqual(classify({'error': 'unknown', 'code': code, 'dispatched': False}), 'uncertain')
        for conflict in ({'dispatched': True}, {'native_dispatched': True}, {'results': [{'status': 'ok'}]}):
            self.assertEqual(classify(dict(error='conflict', code='VW_JOB_UNCLAIMED', **conflict)), 'uncertain')
        self.assertIsNone(classify({'status': 'ok', 'function': 'UprString', 'native_dispatched': False, 'result': 'OK'}))
        self.assertIsNone(classify({'error': 'SDK exception', 'code': 'SDK_EXECUTION', 'dispatched': True}))

    def test_returned_sdk_error_keeps_its_machine_code_instead_of_assertion_label(self):
        p = plan()
        response = {'error': 'native exception', 'code': 'SDK_EXECUTION', 'function': 'MoveTo', 'dispatched': True}
        sender = Mock(side_effect=[guard(), response])
        with tempfile.TemporaryDirectory() as directory:
            result = RUNNER.run_design_plan(sender, p, Path(directory) / 'run.jsonl',
                                           deployed_source_hashes=lambda: p['source_sha256'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error_code'], 'SDK_EXECUTION')
        self.assertEqual(result['records'][0]['result'], response)
        self.assertEqual(sender.call_count, 2)

    def test_server_background_rejection_stops_without_alternative_transport(self):
        p = plan()
        sender = Mock(side_effect=[guard(), {'error': 'Unattended action blocked',
                                           'code': 'VWX_BACKGROUND_INTERACTION_REQUIRED', 'dispatched': False}])
        with tempfile.TemporaryDirectory() as directory:
            result = RUNNER.run_design_plan(sender, p, Path(directory) / 'run.jsonl',
                                           deployed_source_hashes=lambda: p['source_sha256'])
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['error_code'], 'VWX_BACKGROUND_INTERACTION_REQUIRED')
        self.assertEqual(sender.call_count, 2)
        self.assertEqual(result['native_functions_passed'], [])
        self.assertEqual(result['records'][0]['result']['code'], 'VWX_BACKGROUND_INTERACTION_REQUIRED')

    def test_journal_contains_intent_before_sender_is_entered(self):
        p = plan()
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / 'run.jsonl'

            def send(request):
                events = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
                self.assertEqual(events[-1]['event'], 'intent')
                self.assertEqual(events[-1]['request'], request)
                return guard() if request['command'] == 'sdk_sequence' else {
                    'status': 'ok', 'function': request['params']['name'], 'result': None}

            result = RUNNER.run_design_plan(send, p, journal, deployed_source_hashes=lambda: p['source_sha256'])
        self.assertEqual(result['status'], 'passed')

    def test_raw_script_contract_and_malformed_capture_are_never_sent(self):
        p, sender = plan(), Mock()
        for extra in ({'kind': 'adapter_contract', 'cases': []}, {'code': 'vs.LineTo(0,0)'}):
            invalid = copy.deepcopy(p)
            invalid['jobs'][0].update(extra)
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    RUNNER.run_design_plan(sender, invalid, Path(directory) / 'bad.jsonl',
                                           deployed_source_hashes=lambda: p['source_sha256'])
        invalid = copy.deepcopy(p)
        invalid['jobs'][0]['arguments'] = {'p': {'$capture': 'not_created'}}
        with tempfile.TemporaryDirectory() as directory:
            result = RUNNER.run_design_plan(sender, invalid, Path(directory) / 'capture.jsonl',
                                           deployed_source_hashes=lambda: p['source_sha256'])
        self.assertEqual(result['status'], 'failed')
        sender.assert_not_called()

    def test_sequence_local_and_native_results_receive_separate_execution_credit(self):
        for mixed in (False, True):
            with self.subTest(mixed=mixed):
                p = plan()
                calls = [{'name': 'UprString', 'arguments': {'str': 'ascii'}}]
                returned = [{'status': 'ok', 'function': 'UprString', 'result': 'ASCII',
                             'compatibility': {'replacement_function': 'python.str.upper'}}]
                if mixed:
                    calls.append({'name': 'Abs', 'arguments': {'v': -1}})
                    returned.append({'status': 'ok', 'function': 'Abs', 'result': 1})
                p['jobs'] = [{'id': 'mixed', 'kind': 'native', 'calls': calls,
                              'assertions': [{'path': ['results', 0, 'result'], 'equals': 'ASCII'}]}]
                sender = Mock(side_effect=[guard(), {'status': 'ok', 'count': len(returned), 'results': returned}])
                with tempfile.TemporaryDirectory() as directory:
                    result = RUNNER.run_design_plan(sender, p, Path(directory) / 'run.jsonl',
                                                   deployed_source_hashes=lambda: p['source_sha256'])
                self.assertEqual(result['status'], 'passed')
                self.assertEqual(result['native_functions_passed'], ['Abs'] if mixed else [])
                self.assertEqual(result['compatibility_functions_passed'], ['UprString'])
                self.assertEqual(result['records'][0]['execution_kind'], 'compatibility')


if __name__ == '__main__':
    unittest.main()
