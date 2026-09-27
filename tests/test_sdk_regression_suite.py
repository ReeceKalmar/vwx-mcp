"""Registry/live-CLI boundary tests with a fake MCP client, never a host call."""
import asyncio
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = r'C:\SDK-tests\VWX-MCP-SDK-TEST-registry-offline.vwx'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUITE = load('sdk_regression_suite_test_module', ROOT / 'tools/sdk_regression_suite.py')
with patch.dict(sys.modules, {'sdk_regression_suite': SUITE}):
    CLI = load('sdk_regression_cli_test_module', ROOT / 'tools/run_sdk_regression.py')


class SDKRegressionSuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.full = SUITE.build_plan(DOCUMENT, run_id='registry')
        cls.line = SUITE.build_plan(DOCUMENT, run_id='registry', selected=['design:line'])
        cls.scalar = SUITE.build_plan(DOCUMENT, run_id='registry', selected=['numeric:scalar_math'])

    def test_planned_counts_distinguish_native_local_and_conditional_compatibility(self):
        summary = self.full['summary']
        self.assertEqual(summary['fixture_jobs_total'], len(self.full['jobs']))
        self.assertEqual(sum(summary[key] for key in ('native_cases', 'compatibility_cases',
                                                      'conditional_compatibility_cases', 'mixed_execution_cases',
                                                      'characterization_cases')),
                         len(self.full['jobs']))
        self.assertEqual(summary['compatibility_cases'], 3)
        self.assertGreaterEqual(summary['conditional_compatibility_cases'], 5)
        self.assertEqual(self.full['functions']['UprString']['native_case_ids'], [])
        self.assertEqual(len(self.full['functions']['UprString']['compatibility_case_ids']), 3)
        self.assertEqual(self.full['functions']['HArea']['native_case_ids'], [])
        self.assertEqual(len(self.full['functions']['HArea']['conditional_compatibility_case_ids']), 5)
        for name in ('GetTextLeading', 'GetTextLength', 'GetOpacityByClassN', 'GetObjMaterialName', 'SetGradientOpacity', 'SetArc'):
            self.assertEqual(self.full['functions'][name]['native_case_ids'], [])
            self.assertTrue(self.full['functions'][name]['conditional_compatibility_case_ids'])
        for job in self.full['jobs']:
            self.assertEqual(job['native_status'], 'pending_not_executed')
            if job.get('name') == 'HArea':
                self.assertEqual(job['planned_execution_kind'], 'conditional_compatibility')
                self.assertNotIn('execution_kind', job)
        for entry in self.full['functions'].values():
            self.assertEqual(entry['native_status'], 'pending_not_executed')
            self.assertFalse(entry['semantic_verification'])

    def test_characterizations_do_not_design_semantic_native_or_compatibility_cases(self):
        plan = SUITE.build_plan(DOCUMENT, run_id='observations', selected=['geometry:geometry_arc_characterization'])
        summary = plan['summary']
        self.assertEqual(summary['characterization_cases'], len(plan['jobs']))
        self.assertEqual(summary['native_cases'], 0)
        self.assertEqual(summary['native_apis_with_designed_fixture'], 0)
        self.assertGreater(summary['characterization_apis_with_planned_observations'], 0)
        for job in plan['jobs']:
            self.assertEqual(job['coverage_kind'], 'characterization')
            expected_execution = 'conditional_compatibility' if job.get('name') == 'SetArc' else 'native'
            self.assertEqual(job['planned_execution_kind'], expected_execution)
        for entry in plan['functions'].values():
            self.assertFalse(entry['native_case_ids'])
            self.assertFalse(entry['compatibility_case_ids'])
            self.assertFalse(entry['conditional_compatibility_case_ids'])
            self.assertIn('native_fixture_not_yet_designed', entry['flags'])
        self.assertTrue(plan['functions']['SetArc']['characterization_case_ids'])
        for tamper in ({'coverage_kind': 'semantic'}, {'coverage_kind': None}, {'coverage_kind': 'unknown'},
                       {'verification_dimension': 'native semantic readback', 'coverage_kind': 'semantic'}):
            altered = copy.deepcopy(plan)
            altered['jobs'][0].update(tamper)
            with self.subTest(tamper=tamper), self.assertRaises(ValueError):
                SUITE.validate_plan(altered)
        altered = copy.deepcopy(plan)
        altered['jobs'][0].pop('coverage_kind')
        altered['jobs'][0].pop('verification_dimension')
        with self.assertRaisesRegex(ValueError, 'characterization'):
            SUITE.validate_plan(altered)

    def test_maximum_run_ids_keep_all_fixture_identity_names_bounded_and_distinct(self):
        def identities(value):
            if type(value) is dict:
                return set().union(*(identities(item) for item in value.values()))
            if type(value) is list:
                return set().union(*(identities(item) for item in value))
            return {value} if type(value) is str and value.startswith('SDK-') else set()
        def planned_identities(run_id):
            jobs = SUITE.build_plan(DOCUMENT, run_id=run_id)['jobs']
            return identities([[job.get('calls', job.get('arguments')), job['assertions']] for job in jobs])
        left = planned_identities('r' * 79 + 'a')
        right = planned_identities('r' * 79 + 'b')
        self.assertGreater(len(left), 100)
        self.assertTrue(all(len(name) <= 60 and name.isascii() for name in left | right))
        self.assertTrue(left.isdisjoint(right), 'Native truncation must not merge fixture names across runs')

    def test_selected_families_are_exact_namespaced_and_independent(self):
        selected = ['geometry:geometry_lines', 'design:line', 'data:data_records']
        plan = SUITE.build_plan(DOCUMENT, run_id='isolation', selected=selected)
        self.assertEqual(plan['summary']['fixture_families'], selected)
        self.assertEqual(set(job['fixture_family'] for job in plan['jobs']), set(selected))
        ids, captures = set(), set()
        for job in plan['jobs']:
            self.assertNotIn(job['id'], ids)
            ids.add(job['id'])
            if 'capture' in job:
                key = job['capture']['name']
                self.assertTrue(key.startswith(job['fixture_family'] + ':'))
                self.assertNotIn(key, captures)
                captures.add(key)
        for name in selected:
            isolated = SUITE.build_plan(DOCUMENT, run_id='isolation', selected=[name])
            self.assertEqual([job for job in plan['jobs'] if job['fixture_family'] == name], isolated['jobs'])
        for selected in ([], ['invalid:family'], ['design:line', 'design:line'], ['line']):
            with self.assertRaises(ValueError):
                SUITE.build_plan(DOCUMENT, selected=selected)

    def test_unknown_or_cross_family_captures_and_readbacks_are_rejected(self):
        plan = copy.deepcopy(self.line)
        plan['jobs'][1]['arguments']['h'] = {'$capture': 'missing'}
        with self.assertRaisesRegex(ValueError, 'Capture'):
            SUITE.validate_plan(plan)
        mixed = SUITE.build_plan(DOCUMENT, selected=['design:line', 'geometry:geometry_lines'])
        foreign_key = mixed['jobs'][0]['capture']['name']
        geometry_read = next(job for job in mixed['jobs'] if job['fixture_family'].startswith('geometry:') and job.get('name') == 'GetName')
        geometry_read['arguments']['h'] = {'$capture': foreign_key}
        with self.assertRaisesRegex(ValueError, 'family'):
            SUITE.validate_plan(mixed)
        plan = copy.deepcopy(self.line)
        plan['jobs'][1]['verifies_jobs'] = [plan['jobs'][-1]['id']]
        with self.assertRaisesRegex(ValueError, 'missing/later'):
            SUITE.validate_plan(plan)

    def test_capture_paths_types_duplicates_and_void_outputs_fail_offline(self):
        for path in ([], ['results', -1, 'result'], ['results', True, 'result'],
                     ['results', 0, 'result'], ['results', 999, 'result'], ['status']):
            plan = copy.deepcopy(self.line)
            plan['jobs'][0]['capture']['path'] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                SUITE.validate_plan(plan)
        plan = copy.deepcopy(self.line)
        plan['jobs'][1]['capture'] = copy.deepcopy(plan['jobs'][0]['capture'])
        with self.assertRaisesRegex(ValueError, 'Duplicate capture'):
            SUITE.validate_plan(plan)
        # A real-valued metric cannot be used as an object handle in a later job.
        plan = copy.deepcopy(self.line)
        metric = next(job for job in plan['jobs'] if job.get('name') == 'HLength')
        metric['capture'] = {'name': 'metric', 'path': ['result']}
        later = next(job for job in plan['jobs'][plan['jobs'].index(metric)+1:] if job.get('name') == 'SetSegPt1')
        later['arguments']['h'] = {'$capture': 'metric'}
        with self.assertRaisesRegex(ValueError, 'contract'):
            SUITE.validate_plan(plan)

    def test_malformed_assertions_fail_before_any_sender_is_needed(self):
        for assertion in ({'path': ['result'], 'unknown': True},
                          {'path': ['result'], 'equals': 1, 'valid_uuid': True},
                          {'path': [], 'equals': 1},
                          {'path': ['result'], 'range_inclusive': [2, 1]},
                          {'path': ['result'], 'range_inclusive': [True, 3]},
                          {'path': ['result'], 'range_inclusive': [0, float('inf')]},
                          {'path': ['result'], 'equals': float('nan')},
                          {'path': ['result'], 'valid_uuid': False},
                          {'path': ['result'], 'equals': True},
                          {'path': ['result'], 'equals': 1, 'abs_tol': -1},
                          {'path': ['result'], 'equals': 1, 'rel_tol': True},
                          {'path': ['result'], 'equals': 1, 'abs_tol': float('inf')},
                          {'path': ['result'], 'equals': 1, 'abs_tol': 10**1000},
                          {'path': ['result'], 'range_inclusive': [0, 2], 'abs_tol': 0}):
            plan = copy.deepcopy(self.scalar)
            plan['jobs'][0]['assertions'] = [assertion]
            with self.subTest(assertion=assertion), self.assertRaises(ValueError):
                SUITE.validate_plan(plan)

    def test_numeric_tolerance_options_match_the_shared_evaluator_without_weakening_type_checks(self):
        plan = copy.deepcopy(self.scalar)
        plan['jobs'][0]['assertions'][0].update(abs_tol=0, rel_tol=1e-12)
        self.assertTrue(SUITE.validate_plan(plan))
        plan = copy.deepcopy(self.line)
        position = next(job for job in plan['jobs'] if job.get('name') == 'GetSegPt1')
        position['assertions'][0]['equals'] = [True, 0]
        with self.assertRaisesRegex(ValueError, 'shape/types'):
            SUITE.validate_plan(plan)

    def test_sequence_references_require_correct_earlier_result_types(self):
        base = SUITE.build_plan(DOCUMENT, selected=['geometry:geometry_loci'])
        for reference in ({'$ref': 2}, {'$ref': True}, {'$ref': -1}, {'$ref': 0},
                          {'$ref': 1, 'path': ['result', 0]}, {'$ref': 1, 'extra': 0}):
            plan = copy.deepcopy(base)
            plan['jobs'][0]['calls'][-1]['arguments']['h'] = reference
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                SUITE.validate_plan(plan)
        plan = copy.deepcopy(base)
        plan['jobs'][0]['calls'].insert(0, {'name': 'BeginPoly', 'arguments': {}})
        with self.assertRaises(ValueError):
            SUITE.validate_plan(plan)

    def test_all_jobs_are_background_preflighted_before_any_mcp_client_can_start(self):
        plan = copy.deepcopy(self.scalar)
        plan['jobs'][-1].update(name='AlrtDialog', arguments={'s': 'must never appear'})
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(sys.modules, {'fastmcp': None}):
                with self.assertRaisesRegex(ValueError, 'Background fixture blocked'):
                    asyncio.run(CLI.execute(plan, directory, Path(directory) / 'no-host'))
            self.assertFalse((Path(directory) / 'no-host').exists())

    def test_source_provenance_rejects_missing_extra_or_malformed_hashes(self):
        for mutate in (lambda p: p['source_sha256'].pop('sdk_runtime.py'),
                       lambda p: p['source_sha256'].update({'../outside': '0'*64}),
                       lambda p: p['source_sha256'].update({'sdk_runtime.py': 'invalid'})):
            plan = copy.deepcopy(self.scalar)
            mutate(plan)
            with self.assertRaisesRegex(ValueError, 'provenance'):
                SUITE.validate_plan(plan)
        plan = copy.deepcopy(self.scalar)
        plan['fixture_source_sha256']['sdk_numeric_fixtures.py'] = '0' * 64
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {'fastmcp': None}):
            with self.assertRaisesRegex(ValueError, 'Fixture sources differ'):
                asyncio.run(CLI.execute(plan, directory, Path(directory) / 'stale'))
            self.assertFalse((Path(directory) / 'stale').exists())

    def test_deployed_hash_mismatch_stops_before_mcp_import_and_reserves_run_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin, output = Path(directory) / 'plugin', Path(directory) / 'run'
            plugin.mkdir()
            for name in self.scalar['source_sha256']:
                (plugin / name).write_text('different deployed bytes', encoding='utf-8')
            with patch.dict(sys.modules, {'fastmcp': None}):
                with self.assertRaisesRegex(ValueError, 'Deployed SDK files'):
                    asyncio.run(CLI.execute(self.scalar, plugin, output))
                self.assertTrue((output / 'plan.json').exists())
                with self.assertRaises(FileExistsError):
                    asyncio.run(CLI.execute(self.scalar, plugin, output))

    def test_cli_defaults_to_offline_plan_and_never_reads_plugin_or_calls_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'offline'
            argv = ['run_sdk_regression.py', '--document', DOCUMENT, '--plugin-dir', str(Path(directory) / 'does-not-exist'),
                    '--output-dir', str(output), '--family', 'design:line', '--run-id', 'offline']
            with patch.object(sys, 'argv', argv), patch.object(CLI, 'execute', new_callable=AsyncMock) as execute:
                with contextlib.redirect_stdout(io.StringIO()) as stdout:
                    self.assertEqual(CLI.main(), 0)
                execute.assert_not_awaited()
                self.assertIn('planned_not_executed', stdout.getvalue())
                plan = json.loads((output / 'plan.json').read_text(encoding='utf-8'))
                self.assertEqual(plan['summary']['fixture_families'], ['design:line'])
                with self.assertRaises(FileExistsError):
                    CLI.main()

    def test_host_identity_requires_measured_windows_2027_build_and_exact_function(self):
        valid = {'status': 'ok', 'function': 'GetVersionEx', 'result': [32, 0, 1, 2, 999999]}
        self.assertEqual(CLI.host_provenance(valid), {'vectorworks_year': 2027, 'build': 999999, 'version_tuple': [32, 0, 1, 2]})
        for mutation in ({'function': 'GetVersion'}, {'result': [31, 0, 0, 2, 999999]},
                         {'result': [32, 0, 0, 1, 999999]}, {'result': [32, 0, 0, 2, 0]},
                         {'result': [32, 0, 0, 2, True]}, {'result': [32, 0, 0, 2]},
                         {'error': 'uncertain', 'code': 'VW_DISPATCH_UNCONFIRMED'},
                         {'native_dispatched': False}, {'compatibility': {'replacement': 'mock'}}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                CLI.host_provenance(dict(valid, **mutation))

    def test_host_identity_rejects_present_contradictory_or_malformed_dispatch_metadata(self):
        valid = {'status': 'ok', 'function': 'GetVersionEx', 'result': [32, 0, 0, 2, 882075]}
        expected = {'vectorworks_year': 2027, 'build': 882075, 'version_tuple': [32, 0, 0, 2]}
        for metadata in ({}, {'dispatched': True}, {'native_dispatched': True},
                         {'dispatched': True, 'native_dispatched': True}):
            with self.subTest(metadata=metadata):
                self.assertEqual(CLI.host_provenance(dict(valid, **metadata)), expected)
        for field in ('dispatched', 'native_dispatched'):
            for value in (False, None, 0, 1, 'true', [], {}):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    CLI.host_provenance(dict(valid, **{field: value}))
        for field in ('error', 'compatibility'):
            for value in (None, '', False, {}, []):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    CLI.host_provenance(dict(valid, **{field: value}))

    def test_prelude_transport_classification_matches_shared_dispatch_evidence(self):
        cases = []
        for code in CLI.HOST.UNCLAIMED_TRANSPORT_CODES:
            base = {'error': 'Unclaimed', 'code': code, 'cid': 'preserved'}
            cases += [(base, 'blocked'), (dict(base, dispatched=False), 'blocked')]
            cases += [(dict(base, **conflict), 'uncertain') for conflict in
                      ({'dispatched': True}, {'native_dispatched': True}, {'results': [{'status': 'ok'}]})]
        for code in CLI.HOST.UNCERTAIN_TRANSPORT_CODES:
            cases.append(({'error': 'Unknown claim', 'code': code, 'dispatched': False}, 'uncertain'))
        cases.append(({'error': 'Policy rejected', 'code': 'VWX_BACKGROUND_INTERACTION_REQUIRED', 'dispatched': False}, 'blocked'))
        for response, expected in cases:
            with self.subTest(response=response):
                result = CLI.provenance_failure(response)
                self.assertEqual(result['status'], expected)
                self.assertEqual(result['error_code'], response['code'])
                self.assertEqual(result['provenance_response'], response)
                self.assertEqual(result['records'], [])
                self.assertEqual(result['native_functions_passed'], [])
                self.assertEqual(result['compatibility_functions_passed'], [])
                self.assertIsNone(result['host'])

    def test_host_prelude_preserves_unknown_outcomes_and_never_credits_fixtures(self):
        for code in ('VW_BRIDGE_DOWN', 'VW_BRIDGE_PAUSED', 'VW_JOB_UNCLAIMED',
                     'VW_DISPATCH_UNCONFIRMED', 'VW_DISPATCH_STUCK', 'VW_UNKNOWN', 'unexpected'):
            raw = {'error': 'test', 'code': code, 'cid': 'kept'}
            result = CLI.provenance_failure(raw)
            self.assertEqual(result['status'], 'blocked' if code in {'VW_BRIDGE_DOWN', 'VW_BRIDGE_PAUSED', 'VW_JOB_UNCLAIMED'} else 'uncertain')
            self.assertIsNone(result['host'])
            self.assertEqual(result['records'], [])
            self.assertEqual(result['native_functions_passed'], [])
            self.assertEqual(result['provenance_response'], raw)
        for raw in (None, [], {'status': 'ok'}, {'code': 'VW_BRIDGE_DOWN'},
                    {'status': 'ok', 'function': 'GetVersionEx', 'result': [31, 0, 0, 2, 1]}):
            self.assertEqual(CLI.provenance_failure(raw)['status'], 'uncertain')

    def test_explicit_execution_measures_build_without_giving_provenance_fixture_credit(self):
        plan = copy.deepcopy(self.scalar)
        plan['jobs'] = plan['jobs'][:1]
        requests, transports = [], []

        class FakeClient:
            provenance_override = None
            def __init__(self, transport, **kwargs):
                self.transport = transport

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def call_tool(self, name, params):
                requests.append((name, copy.deepcopy(params)))
                if name == 'sdk_sequence':
                    result = {'status': 'ok', 'results': [
                        {'status': 'ok', 'function': 'GetFPathName', 'result': DOCUMENT},
                        {'status': 'ok', 'function': 'GetVersion', 'result': [32, 0, 0, 2]}], 'count': 2}
                elif params['name'] == 'GetVersionEx':
                    result = self.provenance_override or {'status': 'ok', 'function': 'GetVersionEx', 'result': [32, 0, 0, 2, 999999]}
                else:
                    self_outer.assertEqual(params['name'], 'Abs')
                    result = {'status': 'ok', 'function': 'Abs', 'result': abs(params['arguments']['v'])}
                return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(result))])

        self_outer = self
        fastmcp, client, transport = ModuleType('fastmcp'), ModuleType('fastmcp.client'), ModuleType('fastmcp.client.transports')
        fastmcp.Client = FakeClient
        transport.StdioTransport = lambda *a, **kw: transports.append((a, kw)) or object()
        fake_modules = {'fastmcp': fastmcp, 'fastmcp.client': client, 'fastmcp.client.transports': transport}
        with tempfile.TemporaryDirectory() as directory:
            plugin, output = Path(directory) / 'plugin', Path(directory) / 'run'
            plugin.mkdir()
            for name in plan['source_sha256']:
                (plugin / name).write_bytes((ROOT / 'vwx-plugin' / name).read_bytes())
            with patch.dict(sys.modules, fake_modules), contextlib.redirect_stdout(io.StringIO()):
                result = asyncio.run(CLI.execute(plan, plugin, output))
            self.assertEqual(result['status'], 'passed', result)
            self.assertEqual(result['host']['build'], 999999)
            self.assertEqual(result['sdk']['sdk_version'], 3200)
            self.assertEqual(result['native_functions_passed'], ['Abs'])
            self.assertEqual(len(result['records']), 1)
            self.assertEqual(requests[0], ('sdk_call', {'name': 'GetVersionEx', 'arguments': {}}))
            self.assertTrue((output / 'provenance-intent.json').exists())
            self.assertTrue((output / 'provenance-response.json').exists())
            self.assertTrue((output / 'result.json').exists())
            env = transports[0][1]['env']
            self.assertEqual(env['VWX_BACKGROUND_MODE'], '1')
            self.assertEqual(env['VWX_CACHE_TTL'], '0')
            before = len(requests)
            with patch.dict(sys.modules, fake_modules), self.assertRaises(FileExistsError):
                asyncio.run(CLI.execute(plan, plugin, output))
            self.assertEqual(len(requests), before, 'An old run must never replay even a read-only request')
            for code, status in [('VW_BRIDGE_DOWN', 'blocked'), ('VW_DISPATCH_UNCONFIRMED', 'uncertain')]:
                FakeClient.provenance_override = {'code': code, 'error': 'test prelude failure'}
                failed_output = Path(directory) / code
                before = len(requests)
                with patch.dict(sys.modules, fake_modules), contextlib.redirect_stdout(io.StringIO()):
                    failed = asyncio.run(CLI.execute(plan, plugin, failed_output))
                self.assertEqual(failed['status'], status)
                self.assertEqual(failed['records'], [])
                self.assertFalse(failed['fixture_execution_started'])
                self.assertIsNone(failed['host'])
                self.assertEqual(len(requests), before + 1)
                self.assertFalse((failed_output / 'journal.jsonl').exists())
                self.assertTrue((failed_output / 'result.json').exists())


if __name__ == '__main__':
    unittest.main()
