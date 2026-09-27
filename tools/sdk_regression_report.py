"""Summarize explicit saved regression runs offline, without changing evidence.

Pass each run directory explicitly. This tool reads only its plan.json and
optional result.json; it never discovers runs, connects to MCP, reads a queue,
replays a job, or imports observations into the live-evidence file. Missing
results are unknown, not proof that no native execution happened.
"""
import argparse
from collections import Counter
import copy
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location('sdk_regression_report_host', ROOT / 'tools/sdk_host_suite.py')
HOST = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(HOST)
_BINDING_SPEC = importlib.util.spec_from_file_location('sdk_regression_report_binding', ROOT / 'tools/import_sdk_regression.py')
BINDING = importlib.util.module_from_spec(_BINDING_SPEC)
_BINDING_SPEC.loader.exec_module(BINDING)
SDK_NAMES = frozenset(json.loads((ROOT / 'vwx-plugin/vs_index.json').read_text(encoding='utf-8')))
UNCERTAIN_CODES = {'VW_DISPATCH_UNCONFIRMED', 'VW_DISPATCH_STUCK', 'VW_UNKNOWN'}
FUNCTION_FIELDS = ('returned', 'passing_assertions', 'failing_assertions', 'returned_without_assertion')


def _calls(value):
    if not isinstance(value, dict):
        return None
    if 'calls' in value:
        if 'name' in value or 'arguments' in value:
            return None
        calls = value['calls']
    else:
        calls = [{'name': value.get('name'), 'arguments': value.get('arguments')}]
    if (not isinstance(calls, list) or not calls
            or any(not isinstance(call, dict) or not isinstance(call.get('name'), str)
                   or call['name'] not in SDK_NAMES or not isinstance(call.get('arguments'), dict) for call in calls)):
        return None
    return calls


def _empty_functions():
    return {'native': {field: set() for field in FUNCTION_FIELDS},
            'compatibility': {field: set() for field in FUNCTION_FIELDS},
            'rejected_before_dispatch': set(), 'uncertain_requested': set()}


def _public_functions(functions):
    result = {}
    for kind, values in functions.items():
        if isinstance(values, set):
            result[kind] = sorted(values)
        else:
            result[kind] = {field: sorted(names) for field, names in values.items()}
            result[kind]['unique_returned_count'] = len(values['returned'])
    return result


def _uncertain(response):
    return HOST.transport_outcome(response) == 'uncertain'


def _check_declared_assertions(declarations, response):
    """Evaluate even partial-sequence paths without pretending the parent passed."""
    if not declarations:
        return None
    wrapped = []
    for original in declarations:
        if not isinstance(original, dict) or not isinstance(original.get('path'), list):
            return False
        declaration = copy.deepcopy(original)
        declaration['path'] = ['result'] + declaration['path']
        wrapped.append(declaration)
    return HOST.evaluate_native(
        {'name': '__regression_report__', 'assertions': wrapped},
        {'status': 'ok', 'function': '__regression_report__', 'result': response})[0]


def _record_outcome(job, row):
    response = row.get('result')
    if HOST.transport_outcome(response) == 'blocked':
        return 'blocked', None
    if not isinstance(response, dict) or _uncertain(response) or row.get('status') == 'uncertain':
        return 'uncertain', None
    evaluated = HOST.evaluate_native(job, response)[0]
    if row.get('passed') is True and evaluated:
        return 'passed', evaluated
    # A real error response confirms a failed request, but it does not by itself
    # establish which SDK function ran. API attribution is checked separately.
    if row.get('passed') is False or response.get('error') or evaluated is False:
        return 'failed', evaluated
    return 'invalid', evaluated


def _returned_functions(job, row, outcome, functions, issues):
    requested = _calls(row.get('input'))
    planned = _calls(job)
    if not requested or not planned or [c['name'] for c in requested] != [c['name'] for c in planned]:
        issues.append({'job_id': job['id'], 'code': 'request_attribution_mismatch',
                       'detail': 'Recorded request does not match the planned SDK function sequence; no API credit'})
        return
    if row.get('functions') is not None and row['functions'] != [c['name'] for c in requested]:
        issues.append({'job_id': job['id'], 'code': 'recorded_function_mismatch',
                       'detail': 'Recorded function list disagrees with the request; no API credit'})
        return
    response = row.get('result')
    if outcome == 'blocked':
        functions['rejected_before_dispatch'].update(call['name'] for call in requested)
        return
    if outcome == 'uncertain':
        functions['uncertain_requested'].update(call['name'] for call in requested)
        return
    if not isinstance(response, dict):
        return
    sequence = 'calls' in row['input']
    responses = response.get('results', []) if sequence else [response]
    if not isinstance(responses, list) or len(responses) > len(requested):
        issues.append({'job_id': job['id'], 'code': 'malformed_sequence_result', 'detail': 'Invalid response count; no API credit'})
        return
    if sequence and response.get('status') == 'ok' and (
            'error' in response or type(response.get('count')) is not int
            or response['count'] != len(requested) or len(responses) != len(requested)
            or any(type(item) is not dict or item.get('function') != call['name']
                   or item.get('status') != 'ok' or 'error' in item
                   for call, item in zip(requested, responses))):
        issues.append({'job_id': job['id'], 'code': 'malformed_sequence_result',
                       'detail': 'Successful sequence has incomplete or misattributed steps; no API credit'})
        return
    for index, (call, returned) in enumerate(zip(requested, responses)):
        name = call['name']
        if not isinstance(returned, dict) or returned.get('function') != name:
            issues.append({'job_id': job['id'], 'step': index, 'code': 'unattributed_response',
                           'detail': 'Missing or wrong returned function; no API credit'})
            continue
        if _uncertain(returned):
            functions['uncertain_requested'].add(name)
            continue
        if returned.get('error'):
            if returned.get('dispatched') is False or returned.get('native_dispatched') is False:
                functions['rejected_before_dispatch'].add(name)
                continue
            if returned.get('dispatched') is not True and returned.get('native_dispatched') is not True:
                issues.append({'job_id': job['id'], 'step': index, 'code': 'error_dispatch_unconfirmed',
                               'detail': 'Error response does not establish native dispatch; no API credit'})
                continue
        elif returned.get('status') != 'ok' or 'result' not in returned:
            issues.append({'job_id': job['id'], 'step': index, 'code': 'incomplete_return',
                           'detail': 'No successful SDK result or confirmed dispatched error; no API credit'})
            continue
        compatibility = BINDING.compatibility_result(job, row, response, returned, index)
        bucket = functions['compatibility' if compatibility else 'native']
        bucket['returned'].add(name)
        declarations = job.get('assertions', [])
        if sequence:
            declarations = [item for item in declarations
                            if isinstance(item, dict) and item.get('path', [])[:2] == ['results', index]]
        asserted = _check_declared_assertions(declarations, response)
        if returned.get('error') or asserted is False:
            bucket['failing_assertions'].add(name)
        elif asserted is True:
            bucket['passing_assertions'].add(name)
        else:
            bucket['returned_without_assertion'].add(name)


def summarize_run(plan, result=None):
    """Summarize one saved plan/result pair; input dictionaries are unchanged."""
    if not isinstance(plan, dict) or not isinstance(plan.get('jobs'), list):
        raise ValueError('A saved plan with a jobs list is required')
    jobs, order = {}, {}
    for index, job in enumerate(plan['jobs']):
        if (not isinstance(job, dict) or not isinstance(job.get('id'), str) or not job['id']
                or job['id'] in jobs or job.get('kind') != 'native' or not _calls(job)):
            raise ValueError('Plan jobs require unique IDs and concrete SDK fixture calls')
        jobs[job['id']], order[job['id']] = job, index
        BINDING.COVERAGE.coverage_kind(job)
    if result is not None and not isinstance(result, dict):
        raise ValueError('A result file must contain a JSON object')
    if result is not None and result.get('run_id') != plan.get('run_id'):
        raise ValueError('Saved plan and result have different run IDs')
    records = [] if result is None else result.get('records', [])
    if not isinstance(records, list):
        raise ValueError('Recorded fixture results must be a list')
    issues, outcomes, rows, functions, invalid_observations = [], {}, {}, _empty_functions(), []
    characterization_functions = _empty_functions()
    characterization_ids = {job_id for job_id, job in jobs.items()
                            if BINDING.COVERAGE.coverage_kind(job) == 'characterization'}
    counts = Counter(planned=len(jobs), executed=0, passed=0, failed=0, uncertain=0, invalid=0, remaining=len(jobs))
    if characterization_ids:
        counts['observed'] = 0
    stopped, next_index, captures = False, 0, {}
    provenance_mismatch = False
    if result is not None:
        try:
            BINDING.validate_plan_provenance(plan, result)
        except (ValueError, KeyError, TypeError) as error:
            provenance_mismatch = True
            issues.append({'code': 'plan_result_provenance_mismatch', 'detail': str(error) + '; no API credit'})
    if provenance_mismatch:
        invalid_observations.append({'reason': 'invalid_plan_result_provenance', 'records': copy.deepcopy(records)})
    for row in records:
        if not isinstance(row, dict) or row.get('kind') != 'native' or row.get('id') not in jobs:
            issues.append({'job_id': row.get('id') if isinstance(row, dict) else None, 'code': 'unplanned_or_guard_record',
                           'detail': 'Ignored record outside the saved fixture plan; no job or API credit'})
            if isinstance(row, dict) and row.get('kind') == 'native':
                stopped = True
                invalid_observations.append({'reason': 'unplanned_fixture', 'record': copy.deepcopy(row)})
            continue
        job_id, job = row['id'], jobs[row['id']]
        if job_id in outcomes:
            issues.append({'job_id': job_id, 'code': 'duplicate_record', 'detail': 'Duplicate record ignored; no additional credit'})
            stopped = True
            invalid_observations.append({'reason': 'duplicate_record', 'record': copy.deepcopy(row)})
            continue
        rows[job_id] = row
        binding_error = None
        if not provenance_mismatch and not stopped:
            try:
                if order[job_id] != next_index:
                    raise ValueError('Recorded jobs are not an exact ordered prefix of the saved plan')
                BINDING.bind_record(job, row, captures, require_pass_claim=False)
                next_index += 1
            except (ValueError, KeyError, TypeError) as error:
                binding_error = str(error)
        if provenance_mismatch or binding_error:
            outcome = 'invalid'
            issues.append({'job_id': job_id, 'code': 'invalid_fixture_attribution',
                           'detail': (binding_error or 'Invalid plan/result provenance') + '; no API credit'})
        elif stopped:
            outcome = 'invalid'
            issues.append({'job_id': job_id, 'code': 'record_after_stop', 'detail': 'Fixture recorded after a failure/uncertain stop; no API credit'})
        else:
            outcome, evaluated = _record_outcome(job, row)
            if row.get('passed') is True and outcome != 'passed':
                issues.append({'job_id': job_id, 'code': 'pass_claim_not_supported',
                               'detail': 'Saved result does not satisfy the plan assertions'})
            if (row.get('passed') is False and evaluated is True):
                issues.append({'job_id': job_id, 'code': 'failure_claim_despite_passing_result',
                               'detail': 'Reported failure retained; saved values satisfy the plan assertions'})
            _returned_functions(job, row, outcome,
                                characterization_functions if job_id in characterization_ids else functions, issues)
        if outcome == 'passed' and job_id in characterization_ids:
            outcome = 'observed'
        outcomes[job_id] = outcome
        counts['executed'] += outcome != 'blocked'
        counts[outcome] += 1
        counts['remaining'] -= 1
        stopped = stopped or outcome not in ('passed', 'observed')
        if outcome == 'invalid':
            invalid_observations.append({'job_id': job_id, 'reason': binding_error or 'invalid_or_post_stop_record',
                                         'record': copy.deepcopy(row)})

    if (result is not None and not provenance_mismatch and not counts['invalid']
            and not BINDING._same_json(result.get('captures'), captures)):
        issues.append({'code': 'capture_provenance_mismatch',
                       'detail': 'Final captures differ from successful planned responses; no API credit'})
        invalid_observations.append({'reason': 'capture_provenance_mismatch', 'records': copy.deepcopy(records)})
        functions = _empty_functions()
        characterization_functions = _empty_functions()
        for job_id, outcome in list(outcomes.items()):
            if outcome == 'blocked':
                counts['executed'] += 1
            counts[outcome] -= 1
            counts['invalid'] += 1
            outcomes[job_id] = 'invalid'

    semantic_failures = []
    semantic_implicated = set()
    for job_id, outcome in outcomes.items():
        if outcome != 'failed' or job_id in characterization_ids:
            continue
        job, row = jobs[job_id], rows[job_id]
        linked = job.get('verifies_jobs', [])
        if not isinstance(linked, list) or any(not isinstance(value, str) for value in linked):
            issues.append({'job_id': job_id, 'code': 'malformed_readback_links', 'detail': 'No mutation attribution inferred'})
            continue
        if not linked:
            continue
        getters = [call['name'] for call in _calls(row.get('input')) or []]
        mutations, unresolved = [], []
        for prior_id in linked:
            prior = jobs.get(prior_id)
            if prior is None or order[prior_id] >= order[job_id]:
                unresolved.append(prior_id)
                continue
            if (prior_id in characterization_ids or prior.get('phase') not in {'mutation', 'creation'}
                    or prior.get('fixture_family') != job.get('fixture_family')):
                unresolved.append(prior_id)
                continue
            names = [call['name'] for call in _calls(prior)]
            prior_outcome = outcomes.get(prior_id, 'unrecorded')
            mutations.append({'job_id': prior_id, 'functions': names, 'recorded_outcome': prior_outcome,
                              'return_success_does_not_prove_effect': True})
            semantic_implicated.update(names)
        semantic_implicated.update(getters)
        semantic_failures.append({'readback_job_id': job_id, 'getter_functions': getters,
                                  'linked_mutations': mutations, 'unresolved_verifies_jobs': unresolved,
                                  'attribution': 'The failed readback implicates the linked operation and getter; it does not isolate which API is defective.',
                                  'response': copy.deepcopy(row.get('result')),
                                  'recorded_assertions': copy.deepcopy(row.get('assertions', []))})
        if unresolved:
            issues.append({'job_id': job_id, 'code': 'unresolved_readback_links', 'references': unresolved,
                           'detail': 'Missing, later, or non-mutation IDs were not assigned to an API'})
    characterization_counts = Counter(planned=len(characterization_ids), executed=0, observed=0,
                                       failed=0, uncertain=0, invalid=0, remaining=len(characterization_ids))
    for job_id in characterization_ids:
        if job_id in outcomes:
            characterization_counts['executed'] += outcomes[job_id] != 'blocked'
            characterization_counts[outcomes[job_id]] += 1
            characterization_counts['remaining'] -= 1
    summary = {'run_id': plan.get('run_id'),
               'saved_run_status': None if result is None else result.get('status'),
               'result_availability': 'missing' if result is None else 'present',
               'host': None if result is None else copy.deepcopy(result.get('host')),
               'sdk': None if result is None else copy.deepcopy(result.get('sdk')),
               'counts': dict(counts), 'functions': _public_functions(functions),
               'characterization_counts': dict(characterization_counts),
               'characterization_functions': _public_functions(characterization_functions),
               'semantic_readback_failures': semantic_failures,
               'blocked_jobs': [{'job_id': job_id, 'error_code': rows[job_id]['result'].get('code'),
                                 'native_api_executed': False, 'response': copy.deepcopy(rows[job_id]['result'])}
                                for job_id, outcome in outcomes.items() if outcome == 'blocked'],
               'functions_implicated_by_failed_readback': sorted(semantic_implicated),
               'remaining_job_ids': [job_id for job_id in jobs if job_id not in outcomes],
               'job_outcomes': outcomes, 'issues': issues, 'invalid_observations': invalid_observations}
    if result is not None and result.get('status') == 'passed' and (counts['remaining'] or any(counts[key] for key in ('failed', 'blocked', 'uncertain', 'invalid'))):
        issues.append({'code': 'incomplete_passed_run', 'detail': 'Saved passed status does not establish completion of this plan'})
    return summary


def _read_json(path):
    raw = path.read_bytes()
    return json.loads(raw.decode('utf-8')), {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest()}


def build_report(run_directories):
    """Read only explicitly supplied run directories, with no filesystem scan."""
    paths = [Path(path).resolve() for path in run_directories]
    if not paths or len(set(paths)) != len(paths):
        raise ValueError('Choose one or more distinct explicit run directories')
    summaries = []
    for path in paths:
        plan, plan_source = _read_json(path / 'plan.json')
        result_path = path / 'result.json'
        result, result_source = _read_json(result_path) if result_path.is_file() else (None, {'path': str(result_path), 'missing': True})
        summary = summarize_run(plan, result)
        summary['sources'] = {'plan': plan_source, 'result': result_source}
        summaries.append(summary)
    totals, functions, implicated = Counter(), _empty_functions(), set()
    characterization_totals, characterization_functions = Counter(), _empty_functions()
    for summary in summaries:
        totals.update(summary['counts'])
        characterization_totals.update(summary['characterization_counts'])
        for kind in ('native', 'compatibility'):
            for field in FUNCTION_FIELDS:
                functions[kind][field].update(summary['functions'][kind][field])
                characterization_functions[kind][field].update(summary['characterization_functions'][kind][field])
        for field in ('rejected_before_dispatch', 'uncertain_requested'):
            functions[field].update(summary['functions'][field])
            characterization_functions[field].update(summary['characterization_functions'][field])
        implicated.update(summary['functions_implicated_by_failed_readback'])
    return {'schema_version': 1, 'report_kind': 'saved_typed_regression_outcomes', 'runs': summaries,
            'totals': dict(totals), 'functions': _public_functions(functions),
            'characterization_totals': dict(characterization_totals),
            'characterization_functions': _public_functions(characterization_functions),
            'functions_implicated_by_failed_readback': sorted(implicated),
            'limitations': [
                'Executed means a matching saved fixture record except a confirmed undispatched request; it includes uncertain attempts and is not proof of native execution.',
                'Blocked means transport confirmed that the request was not dispatched. It is separate from a failed SDK assertion or an uncertain claimed job; no automatic replay is performed.',
                'Remaining means no matching saved record. A request may have executed without a returned or saved result; never automatically replay it.',
                'Totals sum these explicit runs, including deliberately repeated fixtures; unique API lists are deduplicated separately.',
                'Passing assertions on a creation or void setter can verify only its return contract. Later semantic readbacks determine whether the intended effect was observed.',
                'A failed readback implicates its linked mutation and getter, without proving which API or fixture assumption caused the discrepancy.',
                'Guards, pending plans, unattributed responses, undispatched errors and uncertain attempts never earn confirmed API outcome credit.',
                'Characterization jobs are reported as observed, with separate response-contract outcomes; they never enter semantic passing counts or API lists.',
                'This report is an offline audit of saved data, not new native execution, complete semantic verification, or an import into LIVE_SDK_2027.json.',
            ]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', nargs='+', type=Path, help='Explicit run directories containing plan.json and optional result.json')
    parser.add_argument('--output', type=Path, help='Explicit report destination; stdout if omitted')
    args = parser.parse_args(argv)
    report = build_report(args.runs)
    rendered = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
    if args.output:
        args.output.write_text(rendered, encoding='utf-8', newline='\n')
        print(json.dumps({'runs': len(report['runs']), 'totals': report['totals'], 'output': str(args.output)}, sort_keys=True))
    else:
        print(rendered, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
