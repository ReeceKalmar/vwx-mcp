"""Adversarial native-evidence import checks; no Vectorworks connection."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


IMPORTER = load('sdk_regression_import_test', ROOT / 'tools/import_sdk_regression.py')
HOST = load('sdk_regression_import_host_test', ROOT / 'tools/sdk_host_suite.py')
HOST_PROVENANCE = {'vectorworks_year': 2027, 'build': 882075, 'version_tuple': [32, 0, 0, 2]}
SDK_PROVENANCE = {'vectorworks_year': 2027, 'sdk_version': 3200, 'sdk_build': 882699}
SOURCES = {name: hashlib.sha256((ROOT / 'vwx-plugin' / name).read_bytes()).hexdigest()
           for name in HOST.MODULE_FILES}
SOURCE = {'source_name': 'fixture-run/result.json', 'source_sha256': 'a' * 64}


def response(name='Abs', value=12.5):
    return {'status': 'ok', 'function': name, 'result': value}


def assertion(value=12.5, *, path=None, actual=None, passed=True):
    return {'expected': {'path': ['result'] if path is None else path, 'equals': value},
            'actual': value if actual is None else actual, 'passed': passed}


def row(name='Abs', arguments=None, value=12.5, *, label='scalar'):
    return {'kind': 'native', 'id': label, 'phase': 'readback', 'verifies_jobs': [],
            'functions': [name], 'input': {'name': name, 'arguments': {'v': -12.5} if arguments is None else arguments},
            'result': response(name, value), 'passed': True, 'status': 'passed',
            'assertions': [assertion(value)]}


def run(rows=None, *, status='passed', run_id='import-test'):
    value = {'schema_version': 1, 'execution_path': 'typed_mcp_tools', 'run_id': run_id,
            'document_path': r'C:\SDK-tests\VWX-MCP-SDK-TEST-import.vwx',
            'status': status, 'host': copy.deepcopy(HOST_PROVENANCE), 'sdk': copy.deepcopy(SDK_PROVENANCE),
            'source_sha256': copy.deepcopy(SOURCES), 'fixture_source_sha256': {'sdk_data_fixtures.py': 'b' * 64},
            'records': [row()] if rows is None else rows, 'captures': {},
            # Advisory aggregate claims must never substitute for record evidence.
            'native_functions_passed': ['Abs'], 'compatibility_functions_passed': []}
    # Snapshot the independent plan before a test mutates the returned result.
    # The importer receives this separately and never reads this test-only key.
    value['_saved_plan'] = {key: copy.deepcopy(value[key]) for key in
                            ('schema_version', 'run_id', 'document_path', 'sdk', 'source_sha256', 'fixture_source_sha256')}
    value['_saved_plan']['jobs'] = [dict(copy.deepcopy(item['input']), id=item['id'], kind=item['kind'],
                                        phase=item.get('phase'), verifies_jobs=copy.deepcopy(item.get('verifies_jobs', [])),
                                        assertions=[copy.deepcopy(a['expected']) for a in item.get('assertions', [])
                                                    if 'expected' in a] or [{'path': ['status'], 'equals': 'ok'}])
                                    for item in value['records']]
    return value


def evidence():
    return {'schema_version': 1, 'host': copy.deepcopy(HOST_PROVENANCE),
            'sdk': {'sdk_version': 3200, 'sdk_build': 882699}, 'date': '2026-09-26',
            'records': [], 'adapter_edge_cases': []}


def sequence_row():
    return {'kind': 'native', 'id': 'sequence', 'phase': 'readback', 'verifies_jobs': [],
            'functions': ['Abs', 'Sqrt'],
            'input': {'calls': [{'name': 'Abs', 'arguments': {'v': -12.5}},
                                {'name': 'Sqrt', 'arguments': {'v': 81}}]},
            'result': {'status': 'ok', 'count': 2, 'results': [response(), response('Sqrt', 9)]},
            'passed': True, 'status': 'passed',
            'assertions': [assertion(12.5, path=['results', 0, 'result']),
                           assertion(9, path=['results', 1, 'result'])]}


def native_passes(normalized):
    return {entry['function'] for entry in normalized['records']
            if entry['status'] == 'passed' and entry.get('execution_kind', 'native') == 'native'}


class SDKRegressionImportTests(unittest.TestCase):
    def normalize(self, value):
        return IMPORTER.normalize_run(value, plan=value['_saved_plan'], **SOURCE)

    def merge(self, existing, value):
        return IMPORTER.merge_run(existing, value, plan=value['_saved_plan'], **SOURCE)

    def test_old_and_new_unclaimed_rows_preserve_successful_prefix_but_earn_no_api_outcome(self):
        for code in HOST.UNCLAIMED_TRANSPORT_CODES:
            for modern in (False, True):
                for sequence in (False, True):
                    compatibility = row('GetTextLeading', {'textBlock': HOST.FIXTURE_UUID}, -1, label='leading')
                    compatibility['result']['compatibility'] = {'native_result': 0, 'replacement_function': 'GetTextSpace'}
                    blocked = sequence_row() if sequence else row('GetTextSpace', {'theText': HOST.FIXTURE_UUID}, 2, label='spacing')
                    value = run([row(), compatibility, blocked], status='blocked' if modern else 'failed')
                    blocked['result'] = {'error': 'Not claimed', 'code': code, 'cid': 'saved-unclaimed'}
                    blocked['assertions'] = []
                    if modern:
                        blocked.update(passed=None, status='blocked', native_api_executed=False)
                        blocked['result']['dispatched'] = False
                    else:
                        blocked.update(passed=False, status='failed')
                    before = copy.deepcopy(value)
                    with self.subTest(code=code, modern=modern, sequence=sequence):
                        normalized = self.normalize(value)
                        self.assertEqual(native_passes(normalized), {'Abs'})
                        self.assertEqual(len(normalized['records']), 2)
                        self.assertEqual(normalized['records'][1]['execution_kind'], 'compatibility')
                        self.assertEqual(normalized['adapter_edge_cases'], [])
                        self.assertEqual(len(normalized['uncredited_results']), 1)
                        uncredited = normalized['uncredited_results'][0]
                        self.assertEqual(uncredited['status'], 'blocked')
                        self.assertIs(uncredited['native_api_executed'], False)
                        self.assertEqual(uncredited['result'], blocked['result'])
                        self.assertEqual(value, before)

    def test_blocked_label_requires_actual_undispatched_evidence_and_no_later_rows(self):
        value = run(status='blocked')
        value['records'][0].update(status='blocked', passed=None, assertions=[])
        with self.assertRaises(ValueError):
            self.normalize(value)
        first, second = row(label='unclaimed'), row(label='later')
        value = run([first, second], status='blocked')
        first.update(status='blocked', passed=None, assertions=[], result={'error': 'Unclaimed', 'code': 'VW_JOB_UNCLAIMED'})
        with self.assertRaisesRegex(ValueError, 'after the runner stopped'):
            self.normalize(value)

    def test_claim_uncertainty_with_contradictory_undispatched_flag_is_not_rejected_or_failed(self):
        value = run(status='uncertain')
        value['records'][0].update(passed=None, status='uncertain', assertions=[],
                                   result={'error': 'Unknown claim', 'code': 'VW_DISPATCH_UNCONFIRMED', 'dispatched': False})
        normalized = self.normalize(value)
        self.assertEqual(normalized['adapter_edge_cases'], [])
        self.assertEqual(normalized['records'][0]['status'], 'uncertain')
        self.assertEqual(native_passes(normalized), set())

    def test_characterization_plan_or_record_cannot_be_imported_as_semantic_coverage(self):
        for location in ('plan', 'row'):
            for metadata in ({'coverage_kind': 'characterization'}, {'verification_dimension': 'characterization'}):
                value = run()
                target = value['_saved_plan']['jobs'][0] if location == 'plan' else value['records'][0]
                target.update(metadata)
                existing = evidence()
                before = copy.deepcopy(existing)
                with self.subTest(location=location, metadata=metadata), self.assertRaisesRegex(ValueError, 'Characterization'):
                    self.merge(existing, value)
                self.assertEqual(existing, before)

    def test_mixed_plan_is_refused_even_when_only_semantic_prefix_has_returned(self):
        value = run(status='failed')
        pending = copy.deepcopy(value['_saved_plan']['jobs'][0])
        pending.update(id='pending-observation', coverage_kind='characterization')
        value['_saved_plan']['jobs'].append(pending)
        with self.assertRaisesRegex(ValueError, 'Characterization'):
            self.normalize(value)
        self.assertEqual(native_passes(self.normalize(run())), {'Abs'}, 'Historical semantic plan stays compatible')

    def test_contradictory_or_invalid_coverage_metadata_cannot_promote_observations(self):
        for metadata in ({'coverage_kind': 'semantic', 'verification_dimension': 'characterization'},
                         {'coverage_kind': None}, {'coverage_kind': True}, {'coverage_kind': 'native'}):
            value = run()
            value['_saved_plan']['jobs'][0].update(metadata)
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                self.normalize(value)

    def captured_run(self):
        handle = HOST.FIXTURE_UUID
        creation = row('LNewObj', {}, handle, label='create')
        readback = row('HAreaN', {'h': handle}, 600, label='area')
        value = run([creation, readback])
        saved = value['_saved_plan']
        saved['jobs'][0]['capture'] = {'name': 'created', 'path': ['result']}
        saved['jobs'][1]['arguments']['h'] = {'$capture': 'created'}
        value['captures'] = {'created': handle}
        return value

    def test_original_saved_plan_is_required_and_never_inferred_from_result(self):
        value = run()
        with self.assertRaisesRegex(ValueError, 'original saved plan'):
            IMPORTER.normalize_run(value, **SOURCE)
        value['_saved_plan']['jobs'][0]['arguments']['v'] = -99
        with self.assertRaisesRegex(ValueError, 'request arguments'):
            self.normalize(value)

    def test_rewritten_expected_and_actual_values_cannot_turn_failure_into_pass(self):
        value = run()
        fixture = value['records'][0]
        fixture['result']['result'] = 7
        fixture['assertions'] = [assertion(7)]
        with self.assertRaisesRegex(ValueError, 'original saved plan oracle'):
            self.normalize(value)

    def test_exact_arguments_include_nested_values_options_and_boolean_types(self):
        mutations = [lambda r: r['input']['arguments'].update(v=-13),
                     lambda r: r['input'].update(options={'force': True}),
                     lambda r: r['input']['arguments'].update(v=True)]
        for mutate in mutations:
            value = run([row(arguments={'v': 1}, value=1)])
            mutate(value['records'][0])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.normalize(value)
        value = run([row('Concat', {'s': ['a', ['b', 'c']]}, 'abc')])
        value['records'][0]['input']['arguments']['s'][1][0] = 'wrong'
        with self.assertRaises(ValueError):
            self.normalize(value)

    def test_capture_binding_uses_prior_successful_response_not_recorded_capture_claim(self):
        value = self.captured_run()
        self.assertEqual(native_passes(self.normalize(value)), {'LNewObj', 'HAreaN'})
        for action in ('wrong_argument', 'unresolved_argument', 'forged_final', 'missing_final', 'missing_source', 'duplicate_name'):
            value = self.captured_run()
            if action == 'wrong_argument':
                value['records'][1]['input']['arguments']['h'] = '22222222-2222-4222-8222-222222222222'
            elif action == 'unresolved_argument':
                value['records'][1]['input']['arguments']['h'] = {'$capture': 'created'}
            elif action == 'forged_final':
                value['captures']['created'] = '22222222-2222-4222-8222-222222222222'
            elif action == 'missing_final':
                value.pop('captures')
            elif action == 'missing_source':
                value['_saved_plan']['jobs'][0].pop('capture')
            else:
                value['_saved_plan']['jobs'][1]['capture'] = {'name': 'created', 'path': ['result']}
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.normalize(value)

    def test_reordered_skipped_extra_and_truncated_passed_records_fail_closed(self):
        for action in ('reorder', 'skip_first', 'truncate', 'extra'):
            value = run([row(label='first'), row('Sqrt', {'v': 81}, 9, label='second')])
            if action == 'reorder':
                value['records'].reverse()
            elif action == 'skip_first':
                value['records'].pop(0)
            elif action == 'truncate':
                value['records'].pop()
            else:
                value['records'].append(row(label='extra'))
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.normalize(value)

    def test_every_plan_provenance_field_must_exist_and_match_the_result(self):
        for field in ('run_id', 'schema_version', 'document_path', 'sdk', 'source_sha256', 'fixture_source_sha256'):
            for side in ('plan', 'result'):
                value = run()
                target = value['_saved_plan'] if side == 'plan' else value
                target.pop(field)
                with self.subTest(field=field, side=side), self.assertRaises(ValueError):
                    self.normalize(value)
        value = run()
        value['document_path'] = r'C:\other-document.vwx'
        with self.assertRaises(ValueError):
            self.normalize(value)

    def test_recorded_phase_and_readback_links_cannot_be_reassigned(self):
        for field, changed in [('phase', 'mutation'), ('verifies_jobs', ['unrelated-creation'])]:
            value = run()
            value['records'][0][field] = changed
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.normalize(value)

    def test_original_angle_equals_failure_is_preserved_and_cannot_be_rewritten_modulo_360(self):
        fixture = row('GetSymRot', {'symHd': HOST.FIXTURE_UUID}, 270)
        fixture.update(passed=False, status='failed')
        fixture['result']['result'] = -90
        fixture['assertions'] = [assertion(270, actual=-90, passed=False)]
        value = run([fixture], status='failed')
        normalized = self.normalize(value)
        self.assertEqual(normalized['records'][0]['status'], 'failed')
        self.assertEqual(normalized['records'][0]['assertions'][0]['expected'], {'path': ['result'], 'equals': 270})
        fixture['assertions'] = [{'expected': {'path': ['result'], 'angle_degrees': 270}, 'actual': -90, 'passed': True}]
        fixture.update(passed=True, status='passed')
        value['status'] = 'passed'
        with self.assertRaisesRegex(ValueError, 'original saved plan oracle'):
            self.normalize(value)

    def test_legacy_valid_import_upgrade_preserves_case_records_and_is_idempotent(self):
        value = run()
        existing = self.merge(evidence(), value)
        existing['regression_runs']['import-test'].pop('plan_binding')
        before = copy.deepcopy(existing)
        upgraded = self.merge(existing, value)
        self.assertEqual(upgraded['records'], before['records'])
        self.assertEqual(existing, before)
        binding = upgraded['regression_runs']['import-test']['plan_binding']
        self.assertTrue(binding['requests_captures_oracles_provenance_verified'])
        self.assertEqual(binding['source_plan'], 'fixture-run/plan.json')
        self.assertEqual(upgraded, self.merge(upgraded, value))

    def test_complete_sequence_cannot_drop_or_replace_one_original_oracle(self):
        for action in ('drop', 'replace', 'duplicate', 'reorder'):
            value = run([sequence_row()])
            assertions = value['records'][0]['assertions']
            if action == 'drop':
                assertions.pop()
            elif action == 'replace':
                assertions[1]['expected'] = {'path': ['count'], 'equals': 2}
                assertions[1]['actual'] = 2
            elif action == 'duplicate':
                assertions.append(copy.deepcopy(assertions[0]))
            else:
                assertions.reverse()
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.normalize(value)

    def test_undisclosed_error_dispatch_is_uncredited_not_a_native_failure(self):
        fixture = row()
        fixture.update(passed=False, status='failed', assertions=[])
        fixture['result'] = {'error': 'unknown point of failure', 'code': 'SDK_EXECUTION', 'function': 'Abs'}
        normalized = self.normalize(run([fixture], status='failed'))
        self.assertEqual(normalized['records'], [])
        self.assertEqual(len(normalized['uncredited_results']), 1)

    def test_plan_per_function_compatibility_cannot_be_erased_by_recorded_native_label(self):
        value = run([sequence_row()])
        fixture = value['records'][0]
        value['_saved_plan']['jobs'][0]['function_execution_kinds'] = {'Sqrt': 'compatibility'}
        fixture['execution_kind'] = 'native'
        fixture['function_executions'] = [{'step': i, 'function': name, 'execution_kind': 'native'}
                                          for i, name in enumerate(fixture['functions'])]
        normalized = self.normalize(value)
        self.assertEqual(native_passes(normalized), {'Abs'})
        self.assertEqual(normalized['records'][1]['execution_kind'], 'compatibility')
        for wrong in (True, 0.0, '0'):
            bad = copy.deepcopy(value)
            bad['records'][0]['function_executions'][0]['step'] = wrong
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                self.normalize(bad)

    def test_valid_scalar_recomputes_and_preserves_request_response_and_provenance(self):
        value = run()
        before = copy.deepcopy(value)
        normalized = self.normalize(value)
        self.assertEqual(value, before)
        self.assertEqual(native_passes(normalized), {'Abs'})
        item = normalized['records'][0]
        self.assertEqual(item['input'], {'v': -12.5})
        self.assertEqual(item['result'], response())
        self.assertEqual(item['assertions'], [assertion()])
        self.assertEqual(item['runtime_source_sha256'], SOURCES)
        self.assertEqual(item['source_journal_sha256'], SOURCE['source_sha256'])
        self.assertEqual(item['assertion_scope'], 'result')

    def test_forged_success_flags_cannot_override_wrong_native_value(self):
        for wrong in (-12.5, '12.5', True, None, float('nan'), float('inf')):
            value = run()
            value['records'][0]['result']['result'] = wrong
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                self.normalize(value)

    def test_recorded_actual_value_and_pass_flag_must_match_recomputed_assertion(self):
        for key, wrong in [('actual', 999), ('passed', False), ('passed', 1), ('passed', 'true')]:
            value = run()
            value['records'][0]['assertions'][0][key] = wrong
            with self.subTest(key=key, wrong=wrong), self.assertRaises(ValueError):
                self.normalize(value)

    def test_bad_assertion_declarations_do_not_earn_native_credit(self):
        malformed = [None, {}, {'path': ['result']},
                     {'path': ['result'], 'equals': 12.5, 'valid_uuid': True},
                     {'path': ['result'], 'range_inclusive': [20, 10]},
                     {'path': ['result', -1], 'equals': 12.5},
                     {'path': ['result'], 'equals': 12.5, 'unknown': True}]
        for expected in malformed:
            value = run()
            value['records'][0]['assertions'][0]['expected'] = expected
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                self.normalize(value)

    def test_response_and_request_function_identity_are_mandatory(self):
        for action in ('missing', 'wrong', 'wrong_list'):
            value = run()
            fixture = value['records'][0]
            if action == 'missing':
                del fixture['result']['function']
            elif action == 'wrong':
                fixture['result']['function'] = 'Sqrt'
            else:
                fixture['functions'] = ['Sqrt']
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.normalize(value)

    def test_finished_run_and_row_status_must_not_contradict_results(self):
        for action in ('run_still_running', 'row_failed_but_true', 'row_passed_but_false', 'passed_run_failed_row'):
            value = run()
            fixture = value['records'][0]
            if action == 'run_still_running':
                value['status'] = 'running'
            elif action == 'row_failed_but_true':
                fixture['status'] = 'failed'
            elif action == 'row_passed_but_false':
                fixture['passed'] = False
            else:
                fixture['passed'], fixture['status'] = False, 'failed'
                fixture['result']['result'] = 7
                fixture['assertions'] = [assertion(actual=7, passed=False)]
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.normalize(value)

    def test_failed_scalar_remains_failure_and_advisory_summary_cannot_grant_pass(self):
        fixture = row()
        fixture.update(passed=False, status='failed')
        fixture['result']['result'] = 7
        fixture['assertions'] = [assertion(actual=7, passed=False)]
        value = run([fixture], status='failed')
        value['native_functions_passed'] = ['Abs', 'Sqrt', 'CreateWall']
        normalized = self.normalize(value)
        self.assertEqual(native_passes(normalized), set())
        self.assertEqual(normalized['records'][0]['status'], 'failed')
        self.assertEqual(normalized['records'][0]['function'], 'Abs')

    def test_complete_sequence_preserves_parent_scope_without_inventing_calls(self):
        value = run([sequence_row()])
        normalized = self.normalize(value)
        self.assertEqual(native_passes(normalized), {'Abs', 'Sqrt'})
        for item in normalized['records']:
            self.assertEqual(item['assertion_scope'], 'parent_job')
            self.assertEqual(item['assertion_parent_result'], value['records'][0]['result'])
        self.assertEqual(len({item['test_case'] for item in normalized['records']}), 2)

    def test_sequence_wrong_counts_or_extra_missing_reordered_steps_are_rejected(self):
        for action in ('count_true', 'count_wrong', 'count_missing', 'missing', 'extra', 'reordered'):
            fixture = sequence_row()
            result = fixture['result']
            if action == 'count_true':
                result['count'] = True
            elif action == 'count_wrong':
                result['count'] = 1
            elif action == 'count_missing':
                del result['count']
            elif action == 'missing':
                result['results'].pop()
            elif action == 'extra':
                result['results'].append(response('Sin', 0))
            else:
                result['results'].reverse()
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.normalize(run([fixture]))

    def test_sequence_assertion_flags_are_recomputed_against_parent_response(self):
        fixture = sequence_row()
        fixture['result']['results'][1]['result'] = -9
        with self.assertRaises(ValueError):
            self.normalize(run([fixture]))

    def test_partial_sequence_only_credits_returned_independently_asserted_steps(self):
        fixture = sequence_row()
        fixture.update(passed=False, status='failed')
        fixture['result'] = {'status': 'error', 'error': 'second step failed', 'code': 'SDK_SEQUENCE',
                             'results': [response()], 'count': 1, 'failed_index': 1}
        fixture['assertions'] = [assertion(12.5, path=['results', 0, 'result'])]
        normalized = self.normalize(run([fixture], status='failed'))
        self.assertLessEqual(native_passes(normalized), {'Abs'})
        self.assertNotIn('Sqrt', {item['function'] for item in normalized['records']})
        self.assertTrue(normalized['records'] or normalized['uncredited_results'])

    def test_partial_sequence_with_no_independent_step_assertion_is_uncredited(self):
        fixture = sequence_row()
        fixture.update(passed=False, status='failed')
        fixture['result'] = {'status': 'error', 'error': 'second step failed', 'code': 'SDK_SEQUENCE',
                             'results': [response()], 'count': 1, 'failed_index': 1}
        fixture['assertions'] = []
        normalized = self.normalize(run([fixture], status='failed'))
        self.assertEqual(native_passes(normalized), set())
        self.assertEqual(normalized['records'], [])
        self.assertTrue(normalized['uncredited_results'])

    def test_uncertain_sequence_never_attributes_progress_even_with_partial_results(self):
        for code in ('VW_DISPATCH_UNCONFIRMED', 'VW_DISPATCH_STUCK', 'VW_UNKNOWN'):
            fixture = sequence_row()
            fixture.update(passed=None, status='uncertain', assertions=[])
            fixture['result'] = {'error': 'lost response', 'code': code, 'results': [response()]}
            normalized = self.normalize(run([fixture], status='uncertain'))
            self.assertEqual(normalized['records'], [])
            self.assertTrue(normalized['uncredited_results'])
            self.assertEqual(native_passes(normalized), set())

    def test_uncertain_single_request_is_preserved_without_a_pass(self):
        fixture = row()
        fixture.update(passed=None, status='uncertain', assertions=[])
        fixture['result'] = {'error': 'lost response', 'code': 'VW_DISPATCH_UNCONFIRMED', '_cid': 'native-unknown'}
        normalized = self.normalize(run([fixture], status='uncertain'))
        self.assertEqual(native_passes(normalized), set())
        self.assertEqual(normalized['records'][0]['status'], 'uncertain')
        self.assertEqual(normalized['records'][0]['result']['_cid'], 'native-unknown')

    def test_undispatched_errors_are_adapter_evidence_only(self):
        fixture = row('UprString', {'str': 'ß'}, 'SS')
        fixture.update(passed=False, status='failed', assertions=[])
        fixture['result'] = {'status': 'error', 'function': 'UprString', 'error': 'ASCII only',
                             'code': 'SDK_UNSUPPORTED', 'dispatched': False}
        normalized = self.normalize(run([fixture], status='failed'))
        self.assertEqual(normalized['records'], [])
        self.assertEqual(len(normalized['adapter_edge_cases']), 1)
        self.assertEqual(normalized['adapter_edge_cases'][0]['name'], 'UprString')

    def test_local_area_and_guarded_getter_compatibility_never_receive_native_credit(self):
        for name, arguments, result, replacement in [('UprString', {'str': 'abc'}, 'ABC', 'str.upper'),
                ('HArea', {'h': HOST.FIXTURE_UUID}, 600, 'HAreaN'),
                ('GetTextLeading', {'theText': HOST.FIXTURE_UUID}, -1, 'GetTextSpace'),
                ('GetOpacityByClassN', {'h': HOST.FIXTURE_UUID}, [True, False], 'GetOpacityByClassN'),
                ('GetObjMaterialName', {'h': HOST.FIXTURE_UUID}, [True, 'Fixture material'], 'GetObjMaterialHandle')]:
            fixture = row(name, arguments, result)
            fixture['result']['compatibility'] = {'native_function': name, 'replacement_function': replacement}
            if name == 'UprString':
                fixture['result']['native_dispatched'] = False
            normalized = self.normalize(run([fixture]))
            self.assertEqual(native_passes(normalized), set())
            self.assertEqual(normalized['records'][0]['execution_kind'], 'compatibility')
            self.assertEqual(normalized['records'][0]['status'], 'passed')

    def test_mixed_sequence_keeps_per_step_compatibility_and_parent_marker_propagates(self):
        fixture = sequence_row()
        fixture['result']['results'][1]['compatibility'] = {'implementation': 'local fixture substitute'}
        fixture['result']['results'][1]['native_dispatched'] = False
        normalized = self.normalize(run([fixture]))
        self.assertEqual(native_passes(normalized), {'Abs'})
        fixture['result']['compatibility'] = {'scope': 'whole sequence'}
        normalized = self.normalize(run([fixture]))
        self.assertEqual(native_passes(normalized), set())
        self.assertTrue(all(item['execution_kind'] == 'compatibility' for item in normalized['records']))

    def test_missing_or_invalid_measured_host_sdk_provenance_is_rejected(self):
        variants = [('host', None), ('sdk', None), ('host', dict(HOST_PROVENANCE, vectorworks_year=2026)),
                    ('host', dict(HOST_PROVENANCE, build=0)),
                    ('host', dict(HOST_PROVENANCE, version_tuple=[32, 0, 0, 1])),
                    ('sdk', dict(SDK_PROVENANCE, sdk_version=3100)),
                    ('sdk', dict(SDK_PROVENANCE, sdk_build=True))]
        for key, value in variants:
            candidate = run()
            if value is None:
                candidate.pop(key)
            else:
                candidate[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.normalize(candidate)

    def test_complete_runtime_hash_provenance_is_required(self):
        variants = [None, {}, {name: 'bad-digest' for name in SOURCES},
                    {name: 'A' * 64 for name in SOURCES},
                    dict(SOURCES, unexpected_module='a' * 64),
                    {name: digest for index, (name, digest) in enumerate(SOURCES.items()) if index}]
        for hashes in variants:
            value = run()
            if hashes is None:
                value.pop('source_sha256')
            else:
                value['source_sha256'] = hashes
            with self.subTest(hashes=hashes), self.assertRaises(ValueError):
                self.normalize(value)

    def test_fixture_source_provenance_is_required(self):
        for hashes in (None, {}, {'sdk_data_fixtures.py': 'bad'}, {'sdk_data_fixtures.py': 'A' * 64}):
            value = run()
            if hashes is None:
                value.pop('fixture_source_sha256')
            else:
                value['fixture_source_sha256'] = hashes
            with self.subTest(hashes=hashes), self.assertRaises(ValueError):
                self.normalize(value)

    def test_source_journal_identity_and_sha_are_not_optional(self):
        for source_name, digest in [('', 'a' * 64), ('result.json', ''), ('result.json', 'x' * 64),
                                    ('result.json', 'a' * 63), (None, 'a' * 64)]:
            with self.subTest(source_name=source_name, digest=digest), self.assertRaises(ValueError):
                IMPORTER.normalize_run(run(), source_name=source_name, source_sha256=digest)

    def test_runner_cannot_produce_records_after_failed_or_uncertain_stop(self):
        for status in ('failed', 'uncertain'):
            stopped = row(label='stopped')
            if status == 'failed':
                stopped.update(passed=False, status='failed')
                stopped['result']['result'] = 7
                stopped['assertions'] = [assertion(actual=7, passed=False)]
            else:
                stopped.update(passed=None, status='uncertain', assertions=[])
                stopped['result'] = {'code': 'VW_DISPATCH_UNCONFIRMED', 'error': 'no response'}
            later = row('Sqrt', {'v': 81}, 9, label='impossible-later-row')
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.normalize(run([stopped, later], status=status))

    def test_recorded_compatibility_provenance_cannot_be_promoted_to_native(self):
        for location in ('row', 'function_executions'):
            fixture = row('UprString', {'str': 'abc'}, 'ABC')
            if location == 'row':
                fixture['execution_kind'] = 'compatibility'
            else:
                fixture['function_executions'] = [{'step': 0, 'function': 'UprString', 'execution_kind': 'compatibility'}]
            # A contradictory source can be rejected or conservatively retained,
            # but omission of a response field must never add native pass credit.
            try:
                normalized = self.normalize(run([fixture]))
            except ValueError:
                continue
            with self.subTest(location=location):
                self.assertEqual(native_passes(normalized), set())

    def test_schema_version_requires_integer_not_boolean(self):
        value = run()
        value['schema_version'] = True
        with self.assertRaises(ValueError):
            self.normalize(value)

    def test_merge_requires_exact_measured_host_and_sdk_version_build(self):
        for key, value in [('build', 882076), ('version_tuple', [32, 1, 0, 2])]:
            existing = evidence()
            existing['host'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.merge(existing, run())
        for key, value in [('sdk_version', 3201), ('sdk_build', 882700), ('vectorworks_year', 2026)]:
            existing = evidence()
            existing['sdk'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.merge(existing, run())

    def test_repeat_merge_is_idempotent_and_does_not_mutate_inputs(self):
        existing, value = evidence(), run()
        before_existing, before_run = copy.deepcopy(existing), copy.deepcopy(value)
        first = self.merge(existing, value)
        second = self.merge(first, value)
        self.assertEqual(first, second)
        self.assertEqual(existing, before_existing)
        self.assertEqual(value, before_run)
        self.assertEqual(len(first['records']), 1)
        self.assertFalse(first['regression_runs']['import-test']['full_semantics_verified'])

    def test_returned_evidence_does_not_alias_input_run_provenance(self):
        value = run()
        merged = self.merge(evidence(), value)
        before = copy.deepcopy(merged)
        value['source_sha256']['sdk_runtime.py'] = 'c' * 64
        value['fixture_source_sha256']['sdk_data_fixtures.py'] = 'd' * 64
        value['host']['version_tuple'][1] = 7
        value['records'][0]['input']['arguments']['v'] = -999
        value['records'][0]['assertions'][0]['actual'] = 999
        self.assertEqual(merged, before)

    def test_conflicting_case_or_run_ids_are_rejected_without_partial_mutation(self):
        first = self.merge(evidence(), run())
        before = copy.deepcopy(first)
        changed = run()
        changed['records'][0] = row(value=3)
        changed['records'][0]['input']['arguments'] = {'v': -3}
        with self.assertRaises(ValueError):
            self.merge(first, changed)
        self.assertEqual(first, before)
        with self.assertRaises(ValueError):
            IMPORTER.merge_run(first, run(), source_name='different/result.json', source_sha256='c' * 64)
        self.assertEqual(first, before)

    def test_preexisting_duplicate_evidence_ids_are_rejected(self):
        existing = self.merge(evidence(), run())
        existing['records'].append(copy.deepcopy(existing['records'][0]))
        other = run(run_id='another-run')
        with self.assertRaises(ValueError):
            self.merge(existing, other)

    def test_legacy_distinct_apis_can_share_one_fixture_identifier(self):
        existing = self.merge(evidence(), run())
        existing['records'][0]['test_case'] = 'legacy-shared-fixture'
        second = self.normalize(run([row('Sqrt', {'v': 81}, 9)]))['records'][0]
        second['test_case'] = 'legacy-shared-fixture'
        existing['records'].append(second)
        merged = self.merge(existing, run(run_id='fresh-run'))
        shared = [item for item in merged['records'] if item['test_case'] == 'legacy-shared-fixture']
        self.assertEqual({item['function'] for item in shared}, {'Abs', 'Sqrt'})
        self.assertEqual(len(shared), 2)

    def test_duplicate_job_ids_and_guard_records_are_rejected(self):
        for rows in ([row(), row()], [dict(row(), kind='guard')]):
            with self.assertRaises(ValueError):
                self.normalize(run(rows))

    def test_unicode_recorded_input_and_expected_output_survive_json_roundtrip(self):
        value = run([row('Concat', {'s': ['Grüße ', '東京']}, 'Grüße 東京')])
        restored = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8'))
        merged = self.merge(evidence(), restored)
        raw = json.dumps(merged, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.assertIn('Grüße 東京'.encode('utf-8'), raw)
        self.assertEqual(json.loads(raw)['records'][0]['result']['result'], 'Grüße 東京')

    def test_cli_writes_utf8_and_repeat_import_is_byte_stable(self):
        value = run([row('GetText', {'objectHd': HOST.FIXTURE_UUID}, 'Grüße 東京')])
        with tempfile.TemporaryDirectory() as directory:
            result_path, evidence_path = Path(directory) / 'result.json', Path(directory) / 'evidence.json'
            result_path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            result_path.with_name('plan.json').write_text(json.dumps(value['_saved_plan'], ensure_ascii=False), encoding='utf-8')
            evidence_path.write_text(json.dumps(evidence()), encoding='utf-8')
            with patch.object(sys, 'argv', ['import_sdk_regression.py', str(result_path), '--evidence', str(evidence_path)]), \
                    patch.object(sys, 'path', [str(ROOT / 'tools'), *sys.path]):
                self.assertEqual(IMPORTER.main(), 0)
                first = evidence_path.read_bytes()
                self.assertEqual(IMPORTER.main(), 0)
                self.assertEqual(evidence_path.read_bytes(), first)
            self.assertIn('Grüße 東京'.encode('utf-8'), first)
            self.assertFalse(evidence_path.with_suffix('.json.tmp').exists())


if __name__ == '__main__':
    unittest.main()
