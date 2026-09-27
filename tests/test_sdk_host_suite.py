"""Host-suite checks execute emitted scripts with local canaries, never a host."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = r'C:\SDK-tests\VWX-MCP-SDK-TEST-offline.vwx'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUITE = load('sdk_host_suite_test', ROOT / 'tools/sdk_host_suite.py')
RUNTIME = load('sdk_runtime_host_suite_test', ROOT / 'vwx-plugin/sdk_runtime.py')
CATALOG = json.loads((ROOT / 'vwx-plugin/sdk_catalog.json').read_text(encoding='utf-8'))
with patch.dict(sys.modules, {'vs': SimpleNamespace(), 'sdk_runtime': RUNTIME}):
    GENERATED = load('sdk_generated_host_suite_test', ROOT / 'vwx-plugin/sdk_generated.py')


def commands_module():
    module = ModuleType('commands')
    module.__file__ = str(ROOT / 'vwx-plugin/commands.py')
    module._sdk_modules = lambda: (RUNTIME, GENERATED, None)
    module.sdk_call = Mock()
    module.sdk_sequence = Mock()
    return module


def execute(request, commands=None, path=DOCUMENT, vs_module=None):
    commands = commands or commands_module()
    namespace = {'vs': vs_module or SimpleNamespace(GetFPathName=lambda: path, GetVersion=lambda: (32, 0, 0, 2))}
    with patch.dict(sys.modules, {'commands': commands}):
        exec(request['params']['code'], namespace)
    return namespace['__result__']


class SDKHostSuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = SUITE.build_plan(DOCUMENT, run_id='offline', include_document=True)

    def subset(self, jobs):
        return dict(self.plan, jobs=jobs)

    def case(self, name):
        return next(case for job in self.plan['jobs'] for case in job.get('cases', []) if case['id'] == name)

    def job(self, name):
        return next(job for job in self.plan['jobs'] if job['id'] == name)

    def test_every_sdk_function_has_executable_rejection_cases(self):
        cases = [case for job in self.plan['jobs'] for case in job.get('cases', [])]
        self.assertEqual(set(c['function'] for c in cases), set(CATALOG['functions']))
        self.assertEqual(len([c for c in cases if c['mode'] == 'generated_rejection']), 3098)
        self.assertEqual(len({case['id'] for case in cases}), len(cases))
        self.assertTrue(all(f['native_status'] == 'pending_not_executed' for f in self.plan['functions'].values()))
        self.assertFalse(any(f['semantic_verification'] for f in self.plan['functions'].values()))

    def test_all_planned_adapter_oracles_match_actual_contracts_offline(self):
        # This is an actual exhaustive execution, not only counting the cases.
        checked = 0
        for job in self.plan['jobs']:
            if job['kind'] != 'adapter_contract':
                continue
            result = execute(SUITE.render_job(self.plan, job))
            failures = [r for r in result['records'] if not r['passed']]
            self.assertEqual(failures[:3], [], failures[:3])
            self.assertFalse(result['native_api_executed'])
            checked += len(result['records'])
        self.assertEqual(checked, self.plan['summary']['adapter_cases'])

    def test_no_unvalidated_type_checks_credited_for_unsupported_contexts(self):
        blocked = {name for name, item in self.plan['functions'].items() if item['type_checks_blocked']}
        self.assertTrue(blocked)
        for job in self.plan['jobs']:
            for case in job.get('cases', []):
                if case['function'] in blocked:
                    self.assertNotIn(case['dimension'], ('type_or_range_rejection', 'accepted_abi_boundary'))
        self.assertTrue(self.plan['functions']['RunTempTool']['type_checks_blocked'])

    def test_canary_detects_dispatch_regression_and_never_calls_native(self):
        job = {'id': 'canary-regression', 'kind': 'adapter_contract', 'cases': [self.case('Abs:invalid:v:0')]}

        def broken_invoke(name, params, callable=None, **kwargs):
            try:
                callable(7)
            except RuntimeError:
                return {'error': 'pretend expected rejection', 'code': 'SDK_TYPE', 'function': name, 'dispatched': False}

        with patch.object(RUNTIME, 'invoke', broken_invoke):
            result = execute(SUITE.render_job(self.plan, job))
        self.assertFalse(result['records'][0]['passed'])
        self.assertEqual(result['records'][0]['canary_attempts'], ['target'])

    def test_generated_binding_is_restored_even_if_generated_test_raises(self):
        job = {'id': 'wrapper', 'kind': 'adapter_contract', 'cases': [self.case('Abs:generated_envelope')]}
        previous = GENERATED.vs
        with patch.dict(GENERATED.WRAPPERS, {'Abs': Mock(side_effect=RuntimeError('test failure'))}):
            with self.assertRaises(RuntimeError):
                execute(SUITE.render_job(self.plan, job))
        self.assertIs(GENERATED.vs, previous)

    def test_document_guard_requires_exact_path_and_runs_before_dispatch(self):
        commands = commands_module()
        commands._sdk_modules = Mock(side_effect=AssertionError('must not import runtime'))
        job = self.job('native:Abs')
        result = execute(SUITE.render_job(self.plan, job), commands,
                         path=r'C:\Client\VWX-MCP-SDK-TEST-offline.vwx')
        self.assertEqual(result['code'], 'SDK_SUITE_DOCUMENT')
        commands._sdk_modules.assert_not_called()
        commands.sdk_call.assert_not_called()
        for path in ('', 'untitled.vwx', r'C:\Client\Project.vwx',
                     r'C:\tests\..\VWX-MCP-SDK-TEST-offline.vwx'):
            with self.assertRaises(ValueError):
                SUITE._document_path(path)

    def test_deployment_hash_drift_stops_before_sdk_call(self):
        plan = dict(self.plan, source_sha256=dict(self.plan['source_sha256'], **{'sdk_runtime.py': '0' * 64}))
        commands = commands_module()
        result = execute(SUITE.render_job(plan, self.job('native:Abs')), commands)
        self.assertEqual(result['code'], 'SDK_SUITE_SOURCE')
        commands.sdk_call.assert_not_called()

    def test_all_curated_native_calls_have_valid_signatures_and_assertions(self):
        captures = {'formatted_Angle2Str': '0', 'formatted_Area2Str': '0', 'formatted_Volume2Str': '0',
                    'formatted_Num2StrF': '0', 'rectangle': SUITE.FIXTURE_UUID, 'polygon': SUITE.FIXTURE_UUID,
                    'text': SUITE.FIXTURE_UUID, 'worksheet': SUITE.FIXTURE_UUID}
        for job in self.plan['jobs']:
            if job['kind'] != 'native':
                continue
            self.assertTrue(job['assertions'], job['id'])
            calls = job.get('calls', [{'name': job.get('name'), 'arguments': job.get('arguments')}])
            for call in calls:
                arguments = SUITE._substitute(call['arguments'], captures)
                result = RUNTIME.validate(call['name'], {'arguments': arguments}, catalog=CATALOG,
                                          invocation_context={'sequence': True},
                                          reference_validator=lambda value, _: isinstance(value, dict) and '$ref' in value)
                self.assertNotIn('error', result, (job['id'], result))
            compile(SUITE.render_job(self.plan, job, captures)['params']['code'], '<host-fixture>', 'exec')
        self.assertGreaterEqual(self.plan['summary']['native_apis_with_designed_fixture'], 80)

    def test_creation_and_dependent_inspection_are_distinct_jobs(self):
        creation = self.job('document:create_rectangle')
        inspection = self.job('document:inspect_rectangle_bbox')
        self.assertEqual(SUITE._functions(creation), ['Rect', 'LNewObj'])
        self.assertEqual(SUITE._functions(inspection), ['GetBBox'])
        self.assertLess(self.plan['jobs'].index(creation), self.plan['jobs'].index(inspection))
        self.assertEqual(inspection['arguments']['h'], {'$capture': 'rectangle'})
        self.assertNotIn('DelObject', [name for job in self.plan['jobs'] if job['kind'] == 'native' for name in SUITE._functions(job)])

    def test_native_oracles_reject_wrong_type_wrong_value_and_empty_assertions(self):
        job = self.job('native:CrossProduct')
        good = {'status': 'ok', 'function': 'CrossProduct', 'result': [0.0, 0.0, 1.0]}
        self.assertTrue(SUITE.evaluate_native(job, good)[0])
        self.assertFalse(SUITE.evaluate_native(job, dict(good, result=[0, 0, True]))[0])
        self.assertFalse(SUITE.evaluate_native(job, dict(good, result=[0, 0, -1]))[0])
        self.assertFalse(SUITE.evaluate_native(dict(job, assertions=[]), good)[0])
        self.assertFalse(SUITE.evaluate_native(job, {'error': 'native failure', 'code': 'SDK_RESULT', 'dispatched': True})[0])

    def test_runner_journals_intent_before_send_and_records_concrete_native_results(self):
        jobs = [self.job('native:Abs'), self.job('native:CrossProduct')]
        plan = self.subset(jobs)
        values = iter([12.5, [0, 0, 1]])
        names = iter(['Abs', 'CrossProduct'])
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / 'run.jsonl'

            def send(request):
                events = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
                self.assertEqual(events[-1]['event'], 'intent')
                return {'output': '', 'result': {'status': 'ok', 'function': next(names), 'result': next(values)}}

            result = SUITE.run_plan(send, plan, journal)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['native_functions_passed'], ['Abs', 'CrossProduct'])
            self.assertEqual(result['adapter_functions_passed'], [])
            records = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(sum(event['event'] == 'case_result' for event in records), 2)
            with self.assertRaises(FileExistsError):
                SUITE.run_plan(Mock(), plan, journal)

    def test_uncertain_transport_stops_and_never_replays(self):
        sender = Mock(side_effect=TimeoutError('claimed request timed out'))
        plan = self.subset([self.job('native:Abs'), self.job('native:Cos')])
        with tempfile.TemporaryDirectory() as directory:
            result = SUITE.run_plan(sender, plan, Path(directory) / 'run.jsonl')
        self.assertEqual(result['status'], 'uncertain')
        self.assertEqual(result['native_functions_passed'], [])
        sender.assert_called_once()

    def test_claimed_transport_responses_remain_unknown_and_preserve_raw_evidence(self):
        plan = self.subset([self.job('native:UprString'), self.job('native:Cos')])
        for code in ('VW_DISPATCH_UNCONFIRMED', 'VW_DISPATCH_STUCK', 'VW_UNKNOWN'):
            for wrapped in (False, True):
                with self.subTest(code=code, wrapped=wrapped), tempfile.TemporaryDirectory() as directory:
                    response = {'error': 'Native outcome is not confirmed', 'code': code, 'cid': 'claimed-123'}
                    sender = Mock(return_value={'output': '', 'result': response} if wrapped else response)
                    journal = Path(directory) / 'run.jsonl'
                    with patch.object(SUITE, 'evaluate_native', side_effect=AssertionError('must not evaluate unknown outcome')):
                        result = SUITE.run_plan(sender, plan, journal)
                    self.assertEqual(result['status'], 'uncertain')
                    self.assertEqual(result['uncertain_job'], 'native:UprString')
                    self.assertNotIn('failed_job', result)
                    self.assertEqual(result['native_functions_passed'], [])
                    record = result['records'][0]
                    self.assertIsNone(record['passed'])
                    self.assertIsNone(record['native_api_executed'])
                    self.assertEqual(record['result'], response)
                    self.assertEqual(record['input'], {'str': 'Vectorworks'})
                    events = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
                    measured = next(event for event in events if event['event'] == 'case_result')
                    self.assertEqual(measured['result'], response)
                    self.assertEqual(events[-2]['status'], 'uncertain')
                    sender.assert_called_once()

    def test_outer_transport_error_preserves_cid_instead_of_becoming_script_error(self):
        response = {'output': '', 'result': None, 'error': 'Unconfirmed',
                    'code': 'VW_DISPATCH_UNCONFIRMED', 'cid': 'unknown-456'}
        self.assertEqual(SUITE._unwrap(response), response)

    def test_unclaimed_transport_error_is_a_known_nonexecution_failure(self):
        sender = Mock(return_value={'error': 'Job never dispatched', 'code': 'VW_JOB_UNCLAIMED', 'cid': 'unclaimed-789'})
        plan = self.subset([self.job('native:Abs'), self.job('native:Cos')])
        with tempfile.TemporaryDirectory() as directory:
            result = SUITE.run_plan(sender, plan, Path(directory) / 'run.jsonl')
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['records'][0]['passed'])
        self.assertEqual(result['native_functions_passed'], [])
        sender.assert_called_once()

    def test_failed_assertion_stops_without_counting_a_native_pass(self):
        sender = Mock(return_value={'status': 'ok', 'function': 'Abs', 'result': -12.5})
        plan = self.subset([self.job('native:Abs'), self.job('native:Cos')])
        with tempfile.TemporaryDirectory() as directory:
            result = SUITE.run_plan(sender, plan, Path(directory) / 'run.jsonl')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['native_functions_passed'], [])
        self.assertFalse(result['records'][0]['assertions'][0]['passed'])
        sender.assert_called_once()

    def test_partial_contract_results_do_not_claim_all_tests_for_a_function_passed(self):
        good = self.case('Abs:generated_envelope')
        bad = self.case('Abs:invalid:v:0')
        job = {'id': 'partial', 'kind': 'adapter_contract', 'cases': [good, bad]}
        response = {'status': 'ok', 'records': [
            {'id': good['id'], 'function': 'Abs', 'passed': True},
            {'id': bad['id'], 'function': 'Abs', 'passed': False},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            result = SUITE.run_plan(Mock(return_value=response), self.subset([job]), Path(directory) / 'run.jsonl')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['adapter_functions_passed'], [])
        self.assertEqual(result['native_functions_passed'], [])

    def test_native_capture_is_substituted_into_a_later_request(self):
        jobs = [self.job('native:Area2Str'), self.job('native:Str2Area_roundtrip_Area2Str')]
        values = iter([{'status': 'ok', 'function': 'Area2Str', 'result': '0 sq ft'},
                       {'status': 'ok', 'function': 'Str2Area', 'result': 0.0}])
        sent = []

        def send(request):
            sent.append(request)
            return next(values)

        with tempfile.TemporaryDirectory() as directory:
            result = SUITE.run_plan(send, self.subset(jobs), Path(directory) / 'run.jsonl')
        self.assertEqual(result['status'], 'passed')
        self.assertIn('0 sq ft', sent[1]['params']['code'])
        self.assertNotIn('$capture', sent[1]['params']['code'])

    def test_surface_probe_inspects_only_catalog_symbols_and_never_invokes_targets(self):
        calls, inspected = [], []
        allowed = set(CATALOG['functions'])

        class Host:
            def GetFPathName(self):
                return DOCUMENT
            def GetVersion(self):
                return (32, 0, 0, 2)
            def GetVersionEx(self):
                return (32, 0, 0, 2, 882075)
            def __getattr__(self, name):
                self_allowed = name in allowed
                if not self_allowed:
                    raise AssertionError('Unexpected attribute inspection: ' + name)
                inspected.append(name)
                if name == 'Abs':
                    raise AttributeError(name)
                if name == 'Cos':
                    return None
                if name == 'Sin':
                    raise RuntimeError('Symbol inspection failed')
                return lambda *args: calls.append((name, args))

        result = execute(SUITE.render_surface_probe(self.plan), vs_module=Host())
        self.assertEqual(result['kind'], 'native_surface_presence')
        self.assertEqual(result['missing'], ['Abs'])
        self.assertEqual(result['noncallable'], ['Cos'])
        self.assertEqual(set(result['inspection_errors']), {'Sin'})
        self.assertEqual(len(result['present']), 3095)
        self.assertEqual(result['host']['GetVersionEx'], [32, 0, 0, 2, 882075])
        self.assertEqual(result['sdk']['sdk_build'], 882699)
        self.assertEqual(result['source_sha256'], self.plan['source_sha256'])
        self.assertEqual(result['tested_functions_invoked'], [])
        self.assertFalse(result['semantic_verification'])
        self.assertEqual(calls, [])
        self.assertTrue(set(inspected) <= allowed)

    def test_surface_probe_rejects_non_catalog_name_instead_of_inspecting_it(self):
        plan = dict(self.plan, functions=dict(self.plan['functions'], invented_native_symbol={}))
        with self.assertRaisesRegex(ValueError, 'exact SDK catalog'):
            execute(SUITE.render_surface_probe(plan))

    def test_compatibility_result_is_not_awarded_native_api_coverage(self):
        response = {'status': 'ok', 'function': 'UprString', 'result': 'VECTORWORKS', 'native_dispatched': False,
                    'compatibility': {'replacement_function': 'python.str.upper'}}
        with tempfile.TemporaryDirectory() as directory:
            result = SUITE.run_plan(Mock(return_value=response), self.subset([self.job('native:UprString')]),
                                    Path(directory) / 'run.jsonl')
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['native_functions_passed'], [])
        self.assertEqual(result['compatibility_functions_passed'], ['UprString'])
        self.assertEqual(result['records'][0]['execution_kind'], 'compatibility')

    def test_sequence_compatibility_credit_is_separate_for_local_only_and_mixed_results(self):
        for mixed in (False, True):
            with self.subTest(mixed=mixed):
                calls = [{'name': 'UprString', 'arguments': {'str': 'ascii'}}]
                returned = [{'status': 'ok', 'function': 'UprString', 'result': 'ASCII',
                             'native_dispatched': False}]
                if mixed:
                    calls.append({'name': 'Abs', 'arguments': {'v': -1}})
                    returned.append({'status': 'ok', 'function': 'Abs', 'result': 1})
                job = {'id': 'mixed', 'kind': 'native', 'calls': calls,
                       'assertions': [{'path': ['results', 0, 'result'], 'equals': 'ASCII'}]}
                response = {'status': 'ok', 'count': len(returned), 'results': returned}
                with tempfile.TemporaryDirectory() as directory:
                    result = SUITE.run_plan(Mock(return_value=response), self.subset([job]), Path(directory) / 'run.jsonl')
                self.assertEqual(result['status'], 'passed')
                self.assertEqual(result['native_functions_passed'], ['Abs'] if mixed else [])
                self.assertEqual(result['compatibility_functions_passed'], ['UprString'])
                self.assertEqual(result['records'][0]['execution_kind'], 'compatibility')
                self.assertEqual(result['records'][0]['function_executions'][0]['execution_kind'], 'compatibility')

    def test_sequence_missing_failed_or_misidentified_steps_cannot_earn_pass_credit(self):
        job = {'calls': [{'name': 'Abs'}, {'name': 'Cos'}],
               'assertions': [{'path': ['results', 0, 'result'], 'equals': 1}]}
        first = {'status': 'ok', 'function': 'Abs', 'result': 1}
        for results in ([first], [first, {'error': 'failed'}],
                        [first, {'status': 'ok', 'function': 'Sin', 'result': 1}]):
            self.assertFalse(SUITE.evaluate_native(job, {'status': 'ok', 'count': len(results), 'results': results})[0])

    def test_planned_mixed_sequence_never_lists_local_replacement_as_native_fixture(self):
        mixed = {'id': 'mixed', 'kind': 'native',
                 'calls': [{'name': 'UprString', 'arguments': {'str': 'ascii'}},
                           {'name': 'Abs', 'arguments': {'v': 1}}],
                 'assertions': [{'path': ['results', 0, 'result'], 'equals': 'ASCII'}]}
        with patch.object(SUITE, 'native_fixtures', return_value=[mixed]):
            plan = SUITE.build_plan(DOCUMENT, run_id='planned_mixed', include_contracts=False)
        self.assertEqual(plan['functions']['UprString']['native_case_ids'], [])
        self.assertEqual(plan['functions']['UprString']['compatibility_case_ids'], ['mixed'])
        self.assertEqual(plan['functions']['Abs']['native_case_ids'], ['mixed'])


if __name__ == '__main__':
    unittest.main()
