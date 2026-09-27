"""Saved-data report regressions; every example is offline and synthetic."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('sdk_regression_report_test', ROOT / 'tools/sdk_regression_report.py')
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)
HANDLE = '11111111-1111-4111-8111-111111111111'
PROVENANCE = {'schema_version': 1, 'document_path': r'C:\SDK-tests\VWX-MCP-SDK-TEST-report.vwx',
              'sdk': {'vectorworks_year': 2027, 'sdk_version': 3200, 'sdk_build': 882699},
              'source_sha256': {name: 'a' * 64 for name in REPORT.HOST.MODULE_FILES},
              'fixture_source_sha256': {'fixture.py': 'b' * 64}}


def job(identifier, name, arguments, expected, *, phase='readback', verifies=()):
    return {'id': identifier, 'kind': 'native', 'phase': phase, 'fixture_family': 'synthetic_geometry',
            'name': name, 'arguments': arguments, 'native_status': 'pending_not_executed',
            'assertions': [{'path': ['result'], 'equals': expected}], 'verifies_jobs': list(verifies)}


def plan(jobs, run_id='report-test'):
    return {**copy.deepcopy(PROVENANCE), 'run_id': run_id, 'jobs': jobs, 'functions': {'NeverExecuted': {'native_status': 'passed'}},
            'summary': {'native_cases': len(jobs), 'native_apis_with_designed_fixture': 3098}}


def row(fixture, value=None, *, passed=True, response=None):
    envelope = {'calls': fixture['calls']} if 'calls' in fixture else {key: fixture[key] for key in ('name', 'arguments')}
    calls = envelope.get('calls', [envelope])
    if response is None:
        response = {'status': 'ok', 'function': fixture['name'], 'result': value}
    return {'id': fixture['id'], 'kind': 'native', 'phase': fixture.get('phase'),
            'input': copy.deepcopy(envelope), 'functions': [call['name'] for call in calls],
            'result': copy.deepcopy(response), 'passed': passed, 'assertions': copy.deepcopy(REPORT.HOST.evaluate_native(fixture, response)[1]),
            'verifies_jobs': fixture.get('verifies_jobs', [])}


def result(records, *, status='passed', run_id='report-test'):
    return {**copy.deepcopy(PROVENANCE), 'run_id': run_id, 'records': records, 'status': status,
            'captures': {}, 'execution_path': 'typed_mcp_tools',
            'host': {'vectorworks_year': 2027, 'build': 882075, 'version_tuple': [32, 0, 0, 2]},
            'sdk': {'vectorworks_year': 2027, 'sdk_version': 3200, 'sdk_build': 882699}}


class SDKRegressionReportTests(unittest.TestCase):
    def setUp(self):
        self.setter = job('move', 'HMove', {'h': HANDLE, 'xOffset': 5, 'yOffset': 10}, None, phase='mutation')
        self.getter = job('center', 'HCenter', {'h': HANDLE}, [5, 10], verifies=['move'])
        self.area = job('area', 'HAreaN', {'ObjectHandle': HANDLE}, 600)
        self.plan = plan([self.setter, self.getter, self.area])

    def test_characterization_response_success_is_observed_not_semantically_passed(self):
        fixtures = copy.deepcopy(self.plan['jobs'])
        for fixture in fixtures:
            fixture['verification_dimension'] = 'characterization'
        summary = REPORT.summarize_run(plan(fixtures), result([row(fixtures[0]), row(fixtures[1], [5, 10]), row(fixtures[2], 600)]))
        self.assertEqual(summary['counts']['passed'], 0)
        self.assertEqual(summary['counts']['observed'], 3)
        self.assertEqual(summary['characterization_counts']['observed'], 3)
        self.assertEqual(summary['functions']['native']['returned'], [])
        self.assertEqual(summary['characterization_functions']['native']['passing_assertions'], ['HAreaN', 'HCenter', 'HMove'])
        self.assertEqual(set(summary['job_outcomes'].values()), {'observed'})
        self.assertFalse(summary['issues'])

    def test_characterization_readback_failure_does_not_implicate_semantic_api_results(self):
        fixtures = copy.deepcopy(self.plan['jobs'])
        for fixture in fixtures:
            fixture['coverage_kind'] = 'characterization'
        summary = REPORT.summarize_run(plan(fixtures), result([row(fixtures[0]), row(fixtures[1], [0, 0], passed=False)], status='failed'))
        self.assertEqual(summary['counts']['observed'], 1)
        self.assertEqual(summary['characterization_counts']['failed'], 1)
        self.assertEqual(summary['characterization_counts']['remaining'], 1)
        self.assertEqual(summary['semantic_readback_failures'], [])
        self.assertEqual(summary['functions_implicated_by_failed_readback'], [])
        self.assertEqual(summary['functions']['native']['returned'], [])

    def test_mixed_characterization_and_semantic_same_api_are_accounted_independently(self):
        first = job('observed', 'Abs', {'v': -3}, 3)
        first['coverage_kind'] = 'characterization'
        second = job('semantic', 'Abs', {'v': -4}, 4)
        summary = REPORT.summarize_run(plan([first, second]), result([row(first, 3), row(second, 4)]))
        self.assertEqual(summary['counts']['observed'], 1)
        self.assertEqual(summary['counts']['passed'], 1)
        self.assertEqual(summary['functions']['native']['passing_assertions'], ['Abs'])
        self.assertEqual(summary['characterization_functions']['native']['passing_assertions'], ['Abs'])
        second_row = row(second, 4)
        second_row['coverage_kind'] = 'characterization'
        tampered = REPORT.summarize_run(plan([first, second]), result([row(first, 3), second_row]))
        self.assertEqual(tampered['counts']['invalid'], 1)
        self.assertEqual(tampered['functions']['native']['returned'], [])

    def test_pending_and_compatibility_characterizations_never_enter_semantic_api_lists(self):
        fixture = job('uppercase-observation', 'UprString', {'str': 'ascii'}, 'ASCII')
        fixture['coverage_kind'] = 'characterization'
        saved = plan([fixture])
        pending = REPORT.summarize_run(saved)
        self.assertEqual(pending['characterization_counts']['planned'], 1)
        self.assertEqual(pending['characterization_counts']['remaining'], 1)
        self.assertEqual(pending['characterization_counts']['observed'], 0)
        response = {'status': 'ok', 'function': 'UprString', 'result': 'ASCII',
                    'compatibility': {'replacement_function': 'python.str.upper'}}
        measured = result([row(fixture, response=response)])
        summary = REPORT.summarize_run(saved, measured)
        self.assertEqual(summary['counts']['passed'], 0)
        self.assertEqual(summary['characterization_functions']['compatibility']['returned'], ['UprString'])
        for category in ('native', 'compatibility'):
            self.assertEqual(summary['functions'][category]['returned'], [])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path/'plan.json').write_text(json.dumps(saved), encoding='utf-8')
            (path/'result.json').write_text(json.dumps(measured), encoding='utf-8')
            report = REPORT.build_report([path])
        self.assertEqual(report['totals']['observed'], 1)
        self.assertEqual(report['totals']['passed'], 0)
        self.assertEqual(report['characterization_totals']['observed'], 1)
        self.assertEqual(report['characterization_functions']['compatibility']['returned'], ['UprString'])
        self.assertEqual(report['functions']['compatibility']['returned'], [])

    def test_changed_arguments_and_rewritten_original_oracles_have_no_credit(self):
        for action in ('argument', 'extra_option', 'oracle', 'tolerance', 'bool_for_number'):
            fixture = job('abs', 'Abs', {'v': 1}, 1)
            observation = row(fixture, 1)
            if action == 'argument':
                observation['input']['arguments']['v'] = -2
            elif action == 'extra_option':
                observation['input']['options'] = {'force': True}
            elif action == 'bool_for_number':
                observation['input']['arguments']['v'] = True
            elif action == 'oracle':
                observation['assertions'][0]['expected']['equals'] = 999
            else:
                observation['assertions'][0]['expected']['abs_tol'] = 1000
            summary = REPORT.summarize_run(plan([fixture]), result([observation]))
            with self.subTest(action=action):
                self.assertEqual(summary['counts']['invalid'], 1)
                self.assertEqual(summary['functions']['native']['returned'], [])
                self.assertTrue(summary['invalid_observations'])

    def test_missing_provenance_is_invalid_even_when_values_and_assertions_pass(self):
        for field in ('document_path', 'sdk', 'source_sha256', 'fixture_source_sha256', 'host', 'execution_path', 'schema_version'):
            candidate = result([row(self.setter)])
            candidate.pop(field)
            summary = REPORT.summarize_run(self.plan, candidate)
            with self.subTest(field=field):
                self.assertEqual(summary['counts']['invalid'], 1)
                self.assertEqual(summary['functions']['native']['passing_assertions'], [])
                self.assertIn('plan_result_provenance_mismatch', [entry['code'] for entry in summary['issues']])

    def test_ordered_prefix_disallows_skipped_and_reordered_jobs(self):
        for records in ([row(self.getter, [5, 10])],
                        [row(self.setter), row(self.area, 600), row(self.getter, [5, 10])]):
            summary = REPORT.summarize_run(self.plan, result(records))
            self.assertNotIn('HCenter', summary['functions']['native']['passing_assertions'])
            self.assertNotIn('HAreaN', summary['functions']['native']['passing_assertions'])
            self.assertGreater(summary['counts']['invalid'], 0)

    def test_captures_are_resolved_from_actual_previous_response_and_checked_at_finish(self):
        create = job('create', 'LNewObj', {}, HANDLE, phase='creation')
        create['capture'] = {'name': 'created', 'path': ['result']}
        getter = job('area', 'HAreaN', {'ObjectHandle': {'$capture': 'created'}}, 600)
        saved = plan([create, getter])
        observed = row(getter, 600)
        observed['input']['arguments']['ObjectHandle'] = HANDLE
        candidate = result([row(create, HANDLE), observed])
        candidate['captures'] = {'created': HANDLE}
        self.assertEqual(REPORT.summarize_run(saved, candidate)['counts']['passed'], 2)
        wrong_request = copy.deepcopy(candidate)
        wrong_request['records'][1]['input']['arguments']['ObjectHandle'] = '22222222-2222-4222-8222-222222222222'
        summary = REPORT.summarize_run(saved, wrong_request)
        self.assertEqual(summary['functions']['native']['returned'], ['LNewObj'])
        self.assertEqual(summary['counts']['invalid'], 1)
        for wrong in ({}, {'created': '22222222-2222-4222-8222-222222222222'}, None):
            altered = copy.deepcopy(candidate)
            altered['captures'] = wrong
            summary = REPORT.summarize_run(saved, altered)
            self.assertEqual(summary['functions']['native']['returned'], [])
            self.assertEqual(summary['counts']['invalid'], 2)
            self.assertIn('capture_provenance_mismatch', [entry['code'] for entry in summary['issues']])

    def test_successful_sequence_oracle_only_credits_the_targeted_step(self):
        fixture = {'id': 'seq', 'kind': 'native', 'calls': [
            {'name': 'Abs', 'arguments': {'v': -3}}, {'name': 'Sqr', 'arguments': {'v': 3}}],
            'assertions': [{'path': ['results', 1, 'result'], 'equals': 9}]}
        response = {'status': 'ok', 'count': 2, 'results': [
            {'function': 'Abs', 'status': 'ok', 'result': -999},
            {'function': 'Sqr', 'status': 'ok', 'result': 9}]}
        summary = REPORT.summarize_run(plan([fixture]), result([row(fixture, response=response)]))
        self.assertEqual(summary['counts']['passed'], 1)
        self.assertEqual(summary['functions']['native']['returned'], ['Abs', 'Sqr'])
        self.assertEqual(summary['functions']['native']['passing_assertions'], ['Sqr'])
        self.assertEqual(summary['functions']['native']['returned_without_assertion'], ['Abs'])

    def test_successful_sequence_malformed_count_and_attribution_grant_no_step_credit(self):
        fixture = {'id': 'seq', 'kind': 'native', 'calls': [
            {'name': 'Abs', 'arguments': {'v': -3}}, {'name': 'Sqr', 'arguments': {'v': 3}}],
            'assertions': [{'path': ['results', 0, 'result'], 'equals': 3}]}
        complete = {'status': 'ok', 'count': 2, 'results': [
            {'function': 'Abs', 'status': 'ok', 'result': 3},
            {'function': 'Sqr', 'status': 'ok', 'result': 9}]}
        for action in ('missing_count', 'bool_count', 'truncated', 'extra', 'wrong_second_name', 'reordered'):
            response = copy.deepcopy(complete)
            if action == 'missing_count':
                response.pop('count')
            elif action == 'bool_count':
                response['count'] = True
            elif action == 'truncated':
                response['results'].pop()
            elif action == 'extra':
                response['results'].append(copy.deepcopy(response['results'][0]))
            elif action == 'wrong_second_name':
                response['results'][1]['function'] = 'Sqrt'
            else:
                response['results'].reverse()
            summary = REPORT.summarize_run(plan([fixture]), result([row(fixture, passed=False, response=response)], status='failed'))
            with self.subTest(action=action):
                self.assertEqual(summary['functions']['native']['returned'], [])

    def test_historical_angle_oracle_failure_survives_new_equivalent_angle_predicate(self):
        fixture = job('angle', 'GetSymRot', {'symHd': HANDLE}, 270)
        observation = row(fixture, -90, passed=False)
        summary = REPORT.summarize_run(plan([fixture]), result([observation], status='failed'))
        self.assertEqual(summary['counts']['failed'], 1)
        self.assertEqual(summary['functions']['native']['failing_assertions'], ['GetSymRot'])
        observation['assertions'][0]['expected'] = {'path': ['result'], 'angle_degrees': 270}
        observation['assertions'][0]['passed'] = True
        observation['passed'] = True
        summary = REPORT.summarize_run(plan([fixture]), result([observation]))
        self.assertEqual(summary['counts']['invalid'], 1)
        self.assertEqual(summary['functions']['native']['passing_assertions'], [])

    def test_compatibility_metadata_is_conservative_and_per_step_attribution_is_checked(self):
        fixture = job('abs', 'Abs', {'v': -3}, 3)
        for where in ('row', 'plan', 'per_function_plan', 'step'):
            candidate = copy.deepcopy(fixture)
            observation = row(candidate, 3)
            if where == 'row':
                observation['execution_kind'] = 'compatibility'
            elif where == 'plan':
                candidate['execution_kind'] = 'compatibility'
            elif where == 'per_function_plan':
                candidate['function_execution_kinds'] = {'Abs': 'compatibility'}
                observation['function_executions'] = [{'step': 0, 'function': 'Abs', 'execution_kind': 'native'}]
            else:
                observation['function_executions'] = [{'step': 0, 'function': 'Abs', 'execution_kind': 'compatibility'}]
            summary = REPORT.summarize_run(plan([candidate]), result([observation]))
            with self.subTest(where=where):
                self.assertEqual(summary['functions']['native']['returned'], [])
                self.assertEqual(summary['functions']['compatibility']['returned'], ['Abs'])
        observation['function_executions'][0]['function'] = 'Sqrt'
        summary = REPORT.summarize_run(plan([fixture]), result([observation]))
        self.assertEqual(summary['counts']['invalid'], 1)
        self.assertEqual(summary['functions']['native']['returned'], [])

    def test_missing_result_keeps_every_job_unrecorded_and_never_credits_plan_metadata(self):
        summary = REPORT.summarize_run(self.plan)
        self.assertEqual(summary['counts'], {'planned': 3, 'executed': 0, 'passed': 0, 'failed': 0,
                                             'uncertain': 0, 'invalid': 0, 'remaining': 3})
        self.assertEqual(summary['result_availability'], 'missing')
        self.assertEqual(summary['functions']['native']['returned'], [])
        self.assertEqual(summary['remaining_job_ids'], ['move', 'center', 'area'])

    def test_passes_count_only_completed_fixtures_and_deduplicate_sdk_names(self):
        rows = [row(self.setter), row(self.getter, [5, 10]), row(self.area, 600)]
        before = copy.deepcopy((self.plan, rows))
        summary = REPORT.summarize_run(self.plan, result(rows))
        self.assertEqual(summary['counts']['passed'], 3)
        self.assertEqual(summary['counts']['remaining'], 0)
        self.assertEqual(summary['functions']['native']['returned'], ['HAreaN', 'HCenter', 'HMove'])
        self.assertEqual(summary['functions']['native']['passing_assertions'], ['HAreaN', 'HCenter', 'HMove'])
        self.assertEqual(summary['semantic_readback_failures'], [])
        self.assertEqual(before, (self.plan, rows), 'Reporting must not rewrite original evidence')

    def test_failed_readback_implicates_prior_mutation_and_getter_without_claiming_a_cause(self):
        summary = REPORT.summarize_run(self.plan, result([row(self.setter), row(self.getter, [0, 0], passed=False)], status='failed'))
        self.assertEqual(summary['counts']['passed'], 1)
        self.assertEqual(summary['counts']['failed'], 1)
        self.assertEqual(summary['counts']['remaining'], 1)
        self.assertEqual(summary['functions_implicated_by_failed_readback'], ['HCenter', 'HMove'])
        failure = summary['semantic_readback_failures'][0]
        self.assertEqual(failure['getter_functions'], ['HCenter'])
        self.assertEqual(failure['linked_mutations'], [{'job_id': 'move', 'functions': ['HMove'],
                                                       'recorded_outcome': 'passed', 'return_success_does_not_prove_effect': True}])
        self.assertIn('does not isolate', failure['attribution'])
        self.assertEqual(summary['functions']['native']['failing_assertions'], ['HCenter'])

    def test_unknown_later_and_cross_family_readback_links_are_not_guessed(self):
        bad = row(self.getter, [0, 0], passed=False)
        bad['verifies_jobs'] = ['missing-setter', 'area']
        summary = REPORT.summarize_run(self.plan, result([row(self.setter), bad], status='failed'))
        self.assertEqual(summary['counts']['invalid'], 1)
        self.assertEqual(summary['semantic_readback_failures'], [])
        altered_plan = copy.deepcopy(self.plan)
        altered_plan['jobs'][1]['verifies_jobs'] = ['missing-setter', 'area']
        summary = REPORT.summarize_run(altered_plan, result([row(self.setter), bad], status='failed'))
        failure = summary['semantic_readback_failures'][0]
        self.assertEqual(failure['linked_mutations'], [])
        self.assertEqual(failure['unresolved_verifies_jobs'], ['missing-setter', 'area'])
        self.assertEqual(summary['functions_implicated_by_failed_readback'], ['HCenter'])
        self.assertIn('unresolved_readback_links', [item['code'] for item in summary['issues']])
        crossed = copy.deepcopy(self.plan)
        crossed['jobs'][0]['fixture_family'] = 'other_family'
        summary = REPORT.summarize_run(crossed, result([row(self.setter), row(self.getter, [0, 0], passed=False)], status='failed'))
        self.assertEqual(summary['semantic_readback_failures'][0]['unresolved_verifies_jobs'], ['move'])

    def test_missing_legacy_result_is_uncertain_and_an_unattributed_error_has_no_api_credit(self):
        missing = row(self.setter, passed=False)
        del missing['result']
        summary = REPORT.summarize_run(self.plan, result([missing], status='failed'))
        self.assertEqual(summary['counts']['uncertain'], 1)
        self.assertEqual(summary['counts']['failed'], 0)
        self.assertEqual(summary['functions']['uncertain_requested'], ['HMove'])
        self.assertEqual(summary['functions']['native']['returned'], [])
        legacy = row(self.setter, passed=False, response={'error': 'host invocation failed', 'code': 'SDK_EXECUTION', 'dispatched': True})
        summary = REPORT.summarize_run(self.plan, result([legacy], status='failed'))
        self.assertEqual(summary['counts']['failed'], 1)
        self.assertEqual(summary['functions']['native']['returned'], [])
        self.assertIn('unattributed_response', [item['code'] for item in summary['issues']])

    def test_uncertain_transport_and_undispatched_validation_are_not_native_failures(self):
        for code in REPORT.UNCERTAIN_CODES:
            uncertain = row(self.setter, passed=None, response={'error': 'lost response', 'code': code})
            summary = REPORT.summarize_run(self.plan, result([uncertain], status='uncertain'))
            self.assertEqual(summary['counts']['uncertain'], 1)
            self.assertEqual(summary['functions']['native']['failing_assertions'], [])
        rejected = row(self.setter, passed=False, response={'function': 'HMove', 'error': 'bad argument',
                                                            'code': 'SDK_ARGUMENTS', 'dispatched': False})
        summary = REPORT.summarize_run(self.plan, result([rejected], status='failed'))
        self.assertEqual(summary['functions']['rejected_before_dispatch'], ['HMove'])
        self.assertEqual(summary['functions']['native']['returned'], [])

    def test_legacy_unclaimed_getter_is_blocked_and_does_not_implicate_its_setter(self):
        for code in REPORT.HOST.UNCLAIMED_TRANSPORT_CODES:
            for modern in (False, True):
                response = {'error': 'Queued job never claimed', 'code': code, 'cid': 'unclaimed'}
                if modern:
                    response['dispatched'] = False
                blocked = row(self.getter, passed=None if modern else False, response=response)
                if modern:
                    blocked.update(status='blocked', native_api_executed=False)
                value = result([row(self.setter), blocked], status='blocked' if modern else 'failed')
                before = copy.deepcopy(value)
                with self.subTest(code=code, modern=modern):
                    summary = REPORT.summarize_run(self.plan, value)
                    self.assertEqual(summary['counts']['passed'], 1)
                    self.assertEqual(summary['counts']['blocked'], 1)
                    self.assertEqual(summary['counts']['executed'], 1)
                    self.assertEqual(summary['counts']['failed'], 0)
                    self.assertEqual(summary['counts']['uncertain'], 0)
                    self.assertEqual(summary['counts']['remaining'], 1)
                    self.assertEqual(summary['semantic_readback_failures'], [])
                    self.assertEqual(summary['functions_implicated_by_failed_readback'], [])
                    self.assertEqual(summary['functions']['native']['failing_assertions'], [])
                    self.assertEqual(summary['blocked_jobs'][0]['response'], response)
                    self.assertEqual(value, before)

    def test_partial_sequence_only_credits_returned_identified_steps_with_their_own_assertions(self):
        fixture = {'id': 'partial', 'kind': 'native', 'phase': 'readback', 'fixture_family': 'math',
                   'calls': [{'name': 'Abs', 'arguments': {'v': -3}}, {'name': 'Sqr', 'arguments': {'v': 3}}],
                   'assertions': [{'path': ['results', 0, 'result'], 'equals': 3},
                                  {'path': ['results', 1, 'result'], 'equals': 9}]}
        response = {'error': 'step 1 failed', 'code': 'SDK_SEQUENCE', 'failed_step': 1,
                    'results': [{'status': 'ok', 'function': 'Abs', 'result': 3}], 'dispatched': True}
        summary = REPORT.summarize_run(plan([fixture]), result([row(fixture, passed=False, response=response)], status='failed'))
        self.assertEqual(summary['functions']['native']['returned'], ['Abs'])
        self.assertEqual(summary['functions']['native']['passing_assertions'], ['Abs'])
        self.assertEqual(summary['counts']['failed'], 1)
        fixture['assertions'] = fixture['assertions'][1:]
        summary = REPORT.summarize_run(plan([fixture]), result([row(fixture, passed=False, response=response)], status='failed'))
        self.assertEqual(summary['functions']['native']['passing_assertions'], [])
        self.assertEqual(summary['functions']['native']['returned_without_assertion'], ['Abs'])

    def test_confirmed_dispatched_error_is_retained_but_error_without_dispatch_is_not_attributed(self):
        failed = row(self.setter, passed=False, response={'function': 'HMove', 'error': 'native error',
                                                          'code': 'SDK_EXECUTION', 'dispatched': True})
        summary = REPORT.summarize_run(self.plan, result([failed], status='failed'))
        self.assertEqual(summary['functions']['native']['returned'], ['HMove'])
        self.assertEqual(summary['functions']['native']['failing_assertions'], ['HMove'])
        del failed['result']['dispatched']
        summary = REPORT.summarize_run(self.plan, result([failed], status='failed'))
        self.assertEqual(summary['functions']['native']['returned'], [])
        self.assertIn('error_dispatch_unconfirmed', [item['code'] for item in summary['issues']])

    def test_guards_duplicates_unplanned_rows_and_post_stop_rows_do_not_inflate_coverage(self):
        guard = {'id': 'guard', 'kind': 'guard', 'passed': True, 'result': {'function': 'GetVersionEx', 'status': 'ok', 'result': [32, 0, 0, 2, 882075]}}
        unplanned = row(job('other', 'Abs', {'v': -7}, 7), 7)
        records = [guard, row(self.setter), row(self.setter), unplanned, row(self.getter, [0, 0], passed=False), row(self.area, 600)]
        summary = REPORT.summarize_run(self.plan, result(records, status='failed'))
        self.assertEqual(summary['counts']['executed'], 3)
        self.assertEqual(summary['counts']['passed'], 1)
        self.assertEqual(summary['counts']['invalid'], 2)
        self.assertEqual(summary['functions']['native']['returned'], ['HMove'])
        codes = [item['code'] for item in summary['issues']]
        self.assertIn('duplicate_record', codes)
        self.assertIn('record_after_stop', codes)
        self.assertEqual(codes.count('unplanned_or_guard_record'), 2)

    def test_local_and_fallback_results_stay_separate_from_native_returns(self):
        upper = job('upper', 'UprString', {'str': 'abc'}, 'ABC')
        upper['execution_kind'] = 'compatibility'
        area = job('fallback', 'HArea', {'h': HANDLE}, 600)
        upper_response = {'status': 'ok', 'function': 'UprString', 'result': 'ABC', 'native_dispatched': False}
        area_response = {'status': 'ok', 'function': 'HArea', 'result': 600,
                         'compatibility': {'native_function': 'HArea', 'replacement_function': 'HAreaN'}}
        summary = REPORT.summarize_run(plan([upper, area]), result([row(upper, response=upper_response), row(area, response=area_response)]))
        self.assertEqual(summary['functions']['native']['returned'], [])
        self.assertEqual(summary['functions']['compatibility']['passing_assertions'], ['HArea', 'UprString'])
        self.assertEqual(summary['functions']['compatibility']['unique_returned_count'], 2)

    def test_report_rechecks_claimed_pass_and_never_equates_partial_run_status_with_completion(self):
        summary = REPORT.summarize_run(self.plan, result([row(self.setter), row(self.getter, [0, 0], passed=True)]))
        self.assertEqual(summary['counts']['failed'], 1)
        self.assertIn('pass_claim_not_supported', [item['code'] for item in summary['issues']])
        self.assertIn('incomplete_passed_run', [item['code'] for item in summary['issues']])
        summary = REPORT.summarize_run(self.plan, result([row(self.setter)]))
        self.assertEqual(summary['counts']['remaining'], 2)
        self.assertIn('incomplete_passed_run', [item['code'] for item in summary['issues']])

    def test_attribution_and_source_mismatches_are_uncredited(self):
        wrong = row(self.setter)
        wrong['input'] = {'name': 'GetVersion', 'arguments': {}}
        summary = REPORT.summarize_run(self.plan, result([wrong]))
        self.assertEqual(summary['counts']['invalid'], 1)
        self.assertEqual(summary['functions']['native']['returned'], [])
        altered_plan = dict(self.plan, source_sha256={'sdk_runtime.py': 'a' * 64})
        altered_result = dict(result([row(self.setter)]), source_sha256={'sdk_runtime.py': 'b' * 64})
        summary = REPORT.summarize_run(altered_plan, altered_result)
        self.assertEqual(summary['counts']['invalid'], 1)
        self.assertIn('plan_result_provenance_mismatch', [item['code'] for item in summary['issues']])
        with self.assertRaisesRegex(ValueError, 'different run IDs'):
            REPORT.summarize_run(self.plan, result([], run_id='different'))

    def test_explicit_file_inputs_hash_sources_ignore_other_directories_and_preserve_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second, ignored = [root / name for name in ('selected-1', 'selected-2', 'not-selected')]
            for path in (first, second, ignored):
                path.mkdir()
                (path / 'plan.json').write_text(json.dumps(self.plan), encoding='utf-8')
            first_result = result([row(self.setter), row(self.getter, [5, 10]), row(self.area, 600)])
            (first / 'result.json').write_text(json.dumps(first_result), encoding='utf-8')
            (ignored / 'result.json').write_text('invalid JSON, must never be read', encoding='utf-8')
            before = (first / 'result.json').read_bytes()
            report = REPORT.build_report([first, second])
            self.assertEqual(len(report['runs']), 2)
            self.assertEqual(report['totals']['planned'], 6)
            self.assertEqual(report['totals']['passed'], 3)
            self.assertEqual(report['totals']['remaining'], 3)
            self.assertEqual(report['functions']['native']['unique_returned_count'], 3)
            self.assertEqual(len(report['runs'][0]['sources']['result']['sha256']), 64)
            self.assertTrue(report['runs'][1]['sources']['result']['missing'])
            self.assertEqual(before, (first / 'result.json').read_bytes())
            output = root / 'report.json'
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(REPORT.main([str(first), str(second), '--output', str(output)]), 0)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8')), report)
            with self.assertRaises(ValueError):
                REPORT.build_report([first, first / '.'])
            with self.assertRaises(ValueError):
                REPORT.build_report([])


if __name__ == '__main__':
    unittest.main()
