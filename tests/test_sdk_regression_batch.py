"""Independent-family scheduling tests; no desktop or Vectorworks calls."""
import asyncio
import contextlib
import copy
import importlib.util
import io
import json
import math
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = r'C:\SDK-tests\VWX-MCP-SDK-TEST-batch.vwx'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUITE = load('batch_suite_tests', 'sdk_regression_suite.py')
with patch.dict(sys.modules, {'sdk_regression_suite': SUITE}):
    CLI = load('batch_runner_tests', 'run_sdk_regression.py')
    with patch.dict(sys.modules, {'run_sdk_regression': CLI}):
        BATCH = load('batch_tests', 'run_sdk_regression_batch.py')


def failed_readback():
    return {'status': 'failed', 'error_code': 'SDK_DESIGN_ASSERTION', 'stopped_job': 'metric',
            'records': [{'id': 'metric', 'passed': False, 'input': {'name': 'Abs', 'arguments': {'v': -5}},
                         'result': {'status': 'ok', 'function': 'Abs', 'result': 4},
                         'assertions': [{'expected': {'path': ['result'], 'equals': 5}, 'actual': 4, 'passed': False}]}]}


def tiny_plans(plans):
    """Keep one real reviewed analytic case per family for scheduler tests."""
    plans = copy.deepcopy(plans)
    for plan in plans:
        plan['jobs'] = plan['jobs'][:1]
        plan['summary'].update(fixture_jobs_total=1, native_cases=1, assertion_count=1)
    return plans


def measured(plan, *, wrong=False):
    job = plan['jobs'][0]
    arguments = job['arguments']
    value = abs(arguments['v']) if job['name'] == 'Abs' else math.sqrt(sum(x * x for x in arguments['Vec']))
    response = {'status': 'ok', 'function': job['name'], 'result': value + int(wrong)}
    passed, assertions = BATCH.HOST.evaluate_native(job, response)
    result = {key: copy.deepcopy(plan[key]) for key in
              ('run_id', 'document_path', 'sdk', 'source_sha256', 'fixture_source_sha256')}
    result.update(status='passed' if passed else 'failed', captures={}, execution_path='typed_mcp_tools',
                  host={'vectorworks_year': 2027, 'build': 882075, 'version_tuple': [32, 0, 0, 2]},
                  records=[{'id': job['id'], 'kind': 'native', 'functions': [job['name']], 'passed': passed,
                            'input': {'name': job['name'], 'arguments': copy.deepcopy(arguments)},
                            'result': response, 'assertions': assertions}])
    if not passed:
        result.update(error_code='SDK_DESIGN_ASSERTION', stopped_job=job['id'])
    return result


class BatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plans = tiny_plans(BATCH.make_plans(DOCUMENT, 'batch-tests', ['numeric:scalar_math', 'numeric:vector_math']))

    def test_families_and_run_ids_are_independent_deterministic_and_single_document(self):
        again = tiny_plans(BATCH.make_plans(DOCUMENT, 'batch-tests', ['numeric:scalar_math', 'numeric:vector_math']))
        self.assertEqual(self.plans, again)
        self.assertEqual(len({p['run_id'] for p in again}), 2)
        self.assertEqual([p['summary']['fixture_families'] for p in again],
                         [['numeric:scalar_math'], ['numeric:vector_math']])
        for bad in ('../outside', '', 'x'*61, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                BATCH.make_plans(DOCUMENT, bad)
        for invalid in ([], self.plans + self.plans[:1]):
            with self.assertRaises(ValueError):
                BATCH.validate_batch(invalid)
        mixed = copy.deepcopy(self.plans)
        mixed[1]['document_path'] = r'C:\SDK-tests\VWX-MCP-SDK-TEST-other.vwx'
        with self.assertRaisesRegex(ValueError, 'one exact'):
            BATCH.validate_batch(mixed)

    def test_whole_batch_validation_precedes_first_execution_and_output_creation(self):
        invalid = copy.deepcopy(self.plans)
        invalid[-1]['jobs'][-1].update(name='AlrtDialog', arguments={'s': 'do not dispatch'})
        executor = AsyncMock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'batch'
            with self.assertRaises(ValueError):
                asyncio.run(BATCH.execute_batch(invalid, directory, output, executor=executor))
            self.assertFalse(output.exists())
        executor.assert_not_awaited()

    def test_native_assertion_failure_continues_only_to_an_independent_family(self):
        executor = AsyncMock(side_effect=[measured(self.plans[0], wrong=True), measured(self.plans[1])])
        with tempfile.TemporaryDirectory() as directory:
            result = asyncio.run(BATCH.execute_batch(self.plans, directory, Path(directory) / 'run',
                                 executor=executor, readiness=lambda _: {'ready': True}))
            self.assertEqual(result['status'], 'completed_with_failures')
            self.assertEqual(result['pending_families'], [])
            self.assertEqual(len(result['families']), 2)
            self.assertTrue((Path(directory) / 'run/batch-result.json').exists())
            self.assertEqual(len(list((Path(directory) / 'run/plans').glob('*.json'))), 2)
        self.assertEqual(executor.await_count, 2)
        self.assertNotEqual(executor.await_args_list[0].args[0]['run_id'], executor.await_args_list[1].args[0]['run_id'])

    def test_guard_error_native_error_uncertainty_and_exception_stop_without_retry(self):
        outcomes = [
            {'status': 'failed', 'error_code': 'SDK_SUITE_DOCUMENT', 'records': []},
            {'status': 'blocked', 'error_code': 'VW_JOB_UNCLAIMED', 'records': []},
            {'status': 'uncertain', 'error_code': 'VW_DISPATCH_UNCONFIRMED', 'records': []},
            dict(failed_readback(), records=[dict(failed_readback()['records'][0],
                 result={'error': 'native exception', 'code': 'SDK_EXECUTION', 'function': 'Abs'})]),
            dict(failed_readback(), records=[dict(failed_readback()['records'][0], assertions=[],
                 result={'error': 'historical unclaimed request', 'code': 'VW_JOB_UNCLAIMED'})]),
            RuntimeError('connection dropped after send')]
        for outcome in outcomes:
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                executor = AsyncMock(side_effect=[outcome])
                result = asyncio.run(BATCH.execute_batch(self.plans, directory, Path(directory) / 'run',
                                     executor=executor, readiness=lambda _: {'ready': True}))
                self.assertEqual(executor.await_count, 1)
                self.assertNotEqual(result['status'], 'passed')
                self.assertIn('numeric:vector_math', result['pending_families'])

    def test_busy_or_stale_bridge_stops_without_executing_or_clearing_state(self):
        executor = AsyncMock()
        with tempfile.TemporaryDirectory() as directory:
            result = asyncio.run(BATCH.execute_batch(self.plans, directory, Path(directory) / 'run',
                                 executor=executor, readiness=lambda _: {'ready': False, 'error': 'busy'}))
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(result['families'], [])
            self.assertEqual(len(result['pending_families']), 2)
        executor.assert_not_awaited()

    def test_reused_directory_is_never_resumed_even_after_a_preflight_block(self):
        executor = AsyncMock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'run'
            asyncio.run(BATCH.execute_batch(self.plans, directory, output, executor=executor,
                        readiness=lambda _: {'ready': False}))
            with self.assertRaises(FileExistsError):
                asyncio.run(BATCH.execute_batch(self.plans, directory, output, executor=executor))
        executor.assert_not_awaited()

    def test_completion_wait_is_read_only_bounded_and_stops_on_new_block(self):
        pending = {'ready': False, 'code': 'VW_BRIDGE_SETTLING'}
        for states, expected, waits in (
                ([pending, {'ready': True}], True, 1),
                ([pending] * 31, False, 30),
                ([pending, {'ready': False, 'error': 'stale'}], False, 1),
                ([{'ready': False, 'error': 'queued'}], False, 0)):
            with self.subTest(states=states):
                reader, sleep = Mock(side_effect=states), AsyncMock()
                result = asyncio.run(BATCH.settle_readiness('unused', reader, sleep=sleep))
                self.assertIs(result['ready'], expected)
                self.assertEqual(sleep.await_count, waits)
                self.assertEqual(reader.call_count, waits + 1)
                if waits:
                    self.assertEqual(len(result['completion_wait_observations']),
                                     31 if waits == 30 else 1)

    def test_source_changes_between_families_stop_the_batch(self):
        executor = AsyncMock(return_value=measured(self.plans[0]))
        calls = 0
        original = BATCH.verify_fixture_sources
        def verify(plan):
            nonlocal calls
            calls += 1
            if calls == 4:  # Whole batch checks both, then first family, then second.
                raise ValueError('Sources changed')
            return original(plan)
        with tempfile.TemporaryDirectory() as directory, patch.object(BATCH, 'verify_fixture_sources', side_effect=verify):
            result = asyncio.run(BATCH.execute_batch(self.plans, directory, Path(directory) / 'run',
                                 executor=executor, readiness=lambda _: {'ready': True}))
        self.assertEqual(executor.await_count, 1)
        self.assertNotEqual(result['status'], 'passed')

    def test_malformed_assertion_failure_does_not_allow_continuation(self):
        base = failed_readback()
        self.assertTrue(BATCH.assertion_failure_only(base))
        for change in ({'assertions': []}, {'assertions': [{'passed': False, 'error': 'missing path'}]},
                       {'passed': True}, {'input': None}, {'result': None},
                       {'result': {'status': 'ok', 'function': 'Other', 'result': 4}}):
            value = copy.deepcopy(base)
            value['records'][-1].update(change)
            with self.subTest(change=change):
                self.assertFalse(BATCH.assertion_failure_only(value))
        for value in (None, [], {}, {'status': 'failed', 'records': []}):
            self.assertFalse(BATCH.assertion_failure_only(value))

    def test_sequence_requires_all_attributed_successes_before_semantic_continuation(self):
        value = failed_readback()
        row = value['records'][0]
        row['input'] = {'calls': [{'name': 'Abs', 'arguments': {'v': -5}}, {'name': 'Abs', 'arguments': {'v': -6}}]}
        row['result'] = {'status': 'ok', 'count': 2, 'results': [
            {'status': 'ok', 'function': 'Abs', 'result': 4}, {'status': 'ok', 'function': 'Abs', 'result': 6}]}
        row['assertions'][0]['expected']['path'] = ['results', 0, 'result']
        self.assertTrue(BATCH.assertion_failure_only(value))
        for change in ({'count': True}, {'count': 1}, {'results': []}, {'error': 'partial'}):
            invalid = copy.deepcopy(value)
            invalid['records'][0]['result'].update(change)
            self.assertFalse(BATCH.assertion_failure_only(invalid))

    def test_cli_defaults_to_planning_and_ignores_missing_plugin_path(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = ['run_sdk_regression_batch.py', '--document', DOCUMENT, '--run-id', 'offline',
                    '--plugin-dir', str(Path(directory) / 'missing'), '--output-dir', str(Path(directory) / 'batch'),
                    '--family', 'numeric:scalar_math']
            with patch.object(sys, 'argv', argv), patch.object(BATCH, 'execute_batch', new_callable=AsyncMock) as execute:
                with contextlib.redirect_stdout(io.StringIO()) as stdout:
                    self.assertEqual(BATCH.main(), 0)
                execute.assert_not_awaited()
                self.assertIn('planned_not_executed', stdout.getvalue())

    def test_readiness_uses_fresh_idle_flags_not_the_historical_modal_label(self):
        state = {'schema_version': 1, 'sdk_version': 3200, 'updated_epoch': 1000, 'timer_active': True,
                 'paused': False, 'pending': False, 'queued_jobs': 0, 'process_id': 123,
                 'modifiers_pending_restore': False, 'last_trigger_state': 'modal_dialog_open'}
        with tempfile.TemporaryDirectory() as directory:
            ipc = Path(directory) / 'ipc'
            (ipc / 'jobs').mkdir(parents=True)
            def write(value, alive='1000 0'):
                (ipc / 'native.scheduler.json').write_text(json.dumps(value), encoding='utf-8')
                (ipc / 'native.alive').write_text(alive, encoding='utf-8')
            write(state)
            self.assertTrue(BATCH.bridge_readiness(directory, now=1001)['ready'])
            before = (ipc / 'native.scheduler.json').read_bytes()
            self.assertFalse(BATCH.bridge_readiness(directory, now=1010)['ready'])
            self.assertFalse(BATCH.bridge_readiness(directory, now=995)['ready'])
            for changes in ({'paused': True}, {'pending': True}, {'queued_jobs': 1}, {'queued_jobs': False},
                            {'timer_active': False}, {'process_id': True}, {'modifiers_pending_restore': True}):
                write(dict(state, **changes))
                self.assertFalse(BATCH.bridge_readiness(directory, now=1001)['ready'])
            write(state, '1000 1')
            self.assertFalse(BATCH.bridge_readiness(directory, now=1001)['ready'])
            write(state)
            (ipc / 'jobs/unclaimed.json').write_text('{}', encoding='utf-8')
            self.assertFalse(BATCH.bridge_readiness(directory, now=1001)['ready'])
            self.assertEqual((ipc / 'native.scheduler.json').read_bytes(), before)
            self.assertTrue((ipc / 'jobs/unclaimed.json').exists())

    def test_unavailable_or_malformed_diagnostics_are_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(BATCH.bridge_readiness(directory, now=1001)['ready'])
            ipc = Path(directory) / 'ipc'
            (ipc / 'jobs').mkdir(parents=True)
            for raw in ('not-json', 'null', '[]', 'true'):
                (ipc / 'native.scheduler.json').write_text(raw, encoding='utf-8')
                (ipc / 'native.alive').write_text('1000 0', encoding='utf-8')
                self.assertFalse(BATCH.bridge_readiness(directory, now=1001)['ready'])

    def test_claimed_pass_requires_complete_attributed_plan_evidence(self):
        base = measured(self.plans[0])
        self.assertTrue(BATCH._passed_family(self.plans[0], base))
        mutations = [
            lambda r: r.update(records=[]),
            lambda r: r.update(error='unreported failure'),
            lambda r: r.update(stopped_job='unknown'),
            lambda r: r.update(run_id='different-run'),
            lambda r: r.update(document_path='different-document'),
            lambda r: r.update(fixture_source_sha256={}),
            lambda r: r['sdk'].update(sdk_build=True),
            lambda r: r['host'].update(build=True),
            lambda r: r['host'].update(version_tuple=[32, 0, 0, 1]),
            lambda r: r['records'][0].update(id='unplanned'),
            lambda r: r['records'][0].update(functions=['Other']),
            lambda r: r['records'][0].update(passed=1),
            lambda r: r['records'][0]['input']['arguments'].update(v=100),
            lambda r: r['records'][0]['result'].update(result=0),
            lambda r: r['records'][0]['result'].pop('function'),
            lambda r: r['records'][0]['assertions'][0].update(actual=999),
        ]
        for i, mutate in enumerate(mutations):
            changed = copy.deepcopy(base)
            mutate(changed)
            with self.subTest(mutation=i):
                self.assertFalse(BATCH._passed_family(self.plans[0], changed))
        executor = AsyncMock(return_value={'status': 'passed', 'records': []})
        with tempfile.TemporaryDirectory() as directory:
            result = asyncio.run(BATCH.execute_batch(self.plans, directory, Path(directory) / 'run',
                                 executor=executor, readiness=lambda _: {'ready': True}))
        self.assertEqual(result['status'], 'uncertain')
        self.assertEqual(executor.await_count, 1)
        self.assertEqual(len(result['pending_families']), 2)

    def test_semantic_continuation_recomputes_assertions_and_rejects_unbound_rows(self):
        base = measured(self.plans[0], wrong=True)
        self.assertTrue(BATCH.assertion_failure_only(base, self.plans[0]))
        mutations = [
            lambda r: r['records'][0]['assertions'][0].update(actual=99),
            lambda r: r['records'][0]['assertions'][0]['expected'].update(equals=99),
            lambda r: r['records'][0]['assertions'][0]['expected'].update(abs_tol=True),
            lambda r: r['records'][0]['assertions'][0]['expected'].update(path=['missing']),
            lambda r: r['records'][0]['result'].update(result=100),
            lambda r: r['records'][0]['input']['arguments'].update(v=-99),
            lambda r: r.update(source_sha256={}),
            lambda r: r.update(stopped_job='unrelated'),
        ]
        for i, mutate in enumerate(mutations):
            changed = copy.deepcopy(base)
            mutate(changed)
            with self.subTest(mutation=i):
                self.assertFalse(BATCH.assertion_failure_only(changed, self.plans[0]))
        changed = failed_readback()
        changed['records'][0]['input'].pop('name')
        changed['records'][0]['result'].pop('function')
        self.assertFalse(BATCH.assertion_failure_only(changed))

    def test_record_order_capture_identity_and_complete_prefix_are_required(self):
        plan = copy.deepcopy(self.plans[0])
        identifier = '11111111-1111-4111-8111-111111111111'
        plan['jobs'] = [
            {'id': 'create', 'name': 'CreateMaterial', 'arguments': {'name': 'fresh', 'isSimpleMaterial': True},
             'assertions': [{'path': ['result'], 'valid_uuid': True}], 'capture': {'name': 'resource', 'path': ['result']}},
            {'id': 'read', 'name': 'GetName', 'arguments': {'h': {'$capture': 'resource'}},
             'assertions': [{'path': ['result'], 'equals': 'fresh'}]},
        ]
        for job in plan['jobs']: job['kind'] = 'native'
        base = measured(self.plans[0])
        base.update(records=[], captures={'resource': identifier})
        for job, value, arguments in zip(plan['jobs'], (identifier, 'fresh'),
                                         ({'name': 'fresh', 'isSimpleMaterial': True}, {'h': identifier})):
            response = {'status': 'ok', 'function': job['name'], 'result': value}
            passed, assertions = BATCH.HOST.evaluate_native(job, response)
            base['records'].append({'id': job['id'], 'kind': 'native', 'functions': [job['name']],
                                   'input': {'name': job['name'], 'arguments': arguments},
                                   'passed': passed, 'assertions': assertions, 'result': response})
        self.assertTrue(BATCH._passed_family(plan, base))
        mutations = [lambda r: r['records'].reverse(), lambda r: r['records'].pop(),
                     lambda r: r['records'].append(copy.deepcopy(r['records'][-1])),
                     lambda r: r['records'][1].update(id='create'), lambda r: r.update(captures={}),
                     lambda r: r['captures'].update(extra=identifier),
                     lambda r: r['records'][1]['input']['arguments'].update(h='22222222-2222-4222-8222-222222222222')]
        for index, mutate in enumerate(mutations):
            changed = copy.deepcopy(base)
            mutate(changed)
            with self.subTest(mutation=index): self.assertFalse(BATCH._passed_family(plan, changed))

    def test_pre_executor_errors_are_blocked_and_cancelled_executor_is_not_replayed(self):
        for state in (None, [], {'ready': 1}):
            executor = AsyncMock()
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                result = asyncio.run(BATCH.execute_batch(self.plans, directory, Path(directory) / 'run',
                                     executor=executor, readiness=lambda _: state))
                self.assertEqual(result['status'], 'blocked')
                self.assertNotIn('uncertain_family', result)
            executor.assert_not_awaited()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'cancelled'
            executor = AsyncMock(side_effect=asyncio.CancelledError())
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(BATCH.execute_batch(self.plans, directory, output,
                            executor=executor, readiness=lambda _: {'ready': True}))
            saved = json.loads((output / 'batch-result.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['status'], 'uncertain')
            self.assertEqual(saved['pending_families'], ['numeric:scalar_math', 'numeric:vector_math'])
            self.assertEqual(executor.await_count, 1)
            with self.assertRaises(FileExistsError):
                asyncio.run(BATCH.execute_batch(self.plans, directory, output, executor=executor))
            self.assertEqual(executor.await_count, 1)

    def test_never_enqueued_prelude_stays_blocked_and_does_not_continue(self):
        executor = AsyncMock(return_value={'status': 'blocked', 'records': [], 'host': None,
                             'error_code': 'VW_BRIDGE_DOWN', 'fixture_execution_started': False})
        with tempfile.TemporaryDirectory() as directory:
            result = asyncio.run(BATCH.execute_batch(self.plans, directory, Path(directory) / 'run',
                                 executor=executor, readiness=lambda _: {'ready': True}))
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['error_code'], 'VW_BRIDGE_DOWN')
        self.assertEqual(executor.await_count, 1)
        self.assertNotIn('uncertain_family', result)

    def test_strict_clock_timeout_and_family_metadata_inputs_fail_before_execution(self):
        for value in (True, math.nan, math.inf, -1, 10 ** 1000):
            with self.subTest(age=value), self.assertRaises(ValueError):
                BATCH.bridge_readiness('not-read', now=1000, max_age=value)
        for value in (True, math.nan, math.inf, 10 ** 1000):
            with self.subTest(clock=value), self.assertRaises(ValueError):
                BATCH.bridge_readiness('not-read', now=value)
        for value in (True, math.nan, math.inf, 0, 9.99, 901):
            with self.subTest(timeout=value), self.assertRaises(ValueError):
                asyncio.run(BATCH.execute_batch(self.plans, 'unused', 'unused', timeout=value))
        for summary in (None, {}, {'fixture_families': 'numeric:scalar_math'},
                        {'fixture_families': [None]}, {'fixture_families': ['other']}):
            changed = copy.deepcopy(self.plans)
            changed[0]['summary'] = summary
            with self.subTest(summary=summary), self.assertRaises(ValueError): BATCH.validate_batch(changed)

    def test_default_batch_excludes_diagnostics_but_explicit_selection_and_flag_opt_in(self):
        provider = SimpleNamespace(FAMILIES=('safe', 'diagnostic', 'measurement'), DIAGNOSTIC_FAMILIES=('diagnostic',),
                                   CHARACTERIZATION_FAMILIES=('measurement',))
        def builder(document, *, run_id, selected):
            return {'summary': {'fixture_families': selected}, 'run_id': run_id}
        with patch.object(BATCH, 'providers', return_value={'example': (provider, 'unused')}), \
                patch.object(BATCH, 'build_plan', side_effect=builder):
            default = BATCH.make_plans(DOCUMENT, 'default')
            included = BATCH.make_plans(DOCUMENT, 'included', include_diagnostics=True)
            explicit = BATCH.make_plans(DOCUMENT, 'explicit', ['example:diagnostic'])
            characterization = BATCH.make_plans(DOCUMENT, 'characterization', ['example:measurement'])
        self.assertEqual([p['summary']['fixture_families'] for p in default], [['example:safe']])
        self.assertEqual([p['summary']['fixture_families'] for p in included], [['example:safe'], ['example:diagnostic']])
        self.assertEqual(explicit[0]['summary']['fixture_families'], ['example:diagnostic'])
        self.assertEqual(characterization[0]['summary']['fixture_families'], ['example:measurement'])
        with self.assertRaises(ValueError): BATCH.make_plans(DOCUMENT, 'invalid', include_diagnostics=1)

    def test_complete_independent_results_pass_and_cli_forwards_diagnostic_opt_in(self):
        executor = AsyncMock(side_effect=[measured(plan) for plan in self.plans])
        with tempfile.TemporaryDirectory() as directory:
            result = asyncio.run(BATCH.execute_batch(self.plans, directory, Path(directory) / 'run',
                                 executor=executor, readiness=lambda _: {'ready': True}))
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['pending_families'], [])
        self.assertEqual(executor.await_count, 2)
        argv = ['batch', '--document', DOCUMENT, '--run-id', 'cli', '--plugin-dir', 'unused',
                '--output-dir', 'unused', '--include-diagnostics']
        with patch.object(sys, 'argv', argv), patch.object(BATCH, 'make_plans', return_value=self.plans) as builder, \
                patch.object(BATCH, 'reserve_batch', return_value=(None, {'families': []})), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(BATCH.main(), 0)
        builder.assert_called_once_with(DOCUMENT, 'cli', None, include_diagnostics=True)


if __name__ == '__main__':
    unittest.main()
