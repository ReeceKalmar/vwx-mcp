"""Import recorded typed-MCP fixtures without inventing native coverage.

Always read/write explicit UTF-8. A repeat import is idempotent; changed evidence
under the same test-case ID is rejected. Parent-sequence assertions retain their
scope and complete response. Guard calls, unexecuted steps, local replacements,
undispatched errors and uncertain transport outcomes are distinguished.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNCERTAIN = {'VW_DISPATCH_UNCONFIRMED', 'VW_DISPATCH_STUCK', 'VW_UNKNOWN'}
_SPEC = importlib.util.spec_from_file_location('regression_import_host', ROOT / 'tools/sdk_host_suite.py')
HOST = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(HOST)
_COVERAGE_SPEC = importlib.util.spec_from_file_location('regression_import_coverage', ROOT / 'tools/sdk_regression_suite.py')
COVERAGE = importlib.util.module_from_spec(_COVERAGE_SPEC)
_COVERAGE_SPEC.loader.exec_module(COVERAGE)
SDK_NAMES = frozenset(json.loads((ROOT / 'vwx-plugin/vs_index.json').read_text(encoding='utf-8')))


def _same_json(left, right):
    """JSON equality preserves boolean/numeric types and rejects nonfinite data."""
    try:
        return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        return False


def _valid_hash(value):
    return type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _plan_calls(job):
    if type(job) is not dict or job.get('kind') != 'native' or 'code' in job or 'cases' in job:
        raise ValueError('The saved plan must contain only typed native fixture jobs')
    if 'calls' in job:
        if 'name' in job or 'arguments' in job:
            raise ValueError('Ambiguous saved plan request')
        calls = job['calls']
    else:
        calls = [{'name': job.get('name'), 'arguments': job.get('arguments')}]
    if (type(calls) is not list or not calls or any(type(call) is not dict
            or type(call.get('name')) is not str or call['name'] not in SDK_NAMES
            or type(call.get('arguments')) is not dict for call in calls)):
        raise ValueError('Saved plan requires concrete indexed SDK functions and arguments')
    return calls


def validate_plan_provenance(plan, run):
    """Check the historical pair, not today's fixture definitions or file hashes."""
    if type(plan) is not dict or type(run) is not dict:
        raise ValueError('The original saved plan and result objects are required')
    _provenance(run)
    if (type(plan.get('schema_version')) is not int or plan['schema_version'] != 1
            or type(run.get('schema_version')) is not int or run['schema_version'] != 1
            or run.get('execution_path') != 'typed_mcp_tools'):
        raise ValueError('Plan and result must use the typed regression schema')
    for key in ('run_id', 'document_path'):
        if type(plan.get(key)) is not str or not plan[key] or not _same_json(plan[key], run.get(key)):
            raise ValueError('Saved plan/result ' + key + ' is missing or differs')
    for key in ('sdk', 'source_sha256', 'fixture_source_sha256'):
        if key not in plan or key not in run or not _same_json(plan[key], run[key]):
            raise ValueError('Saved plan/result ' + key + ' provenance is missing or differs')
    hashes, fixtures = plan['source_sha256'], plan['fixture_source_sha256']
    if (type(hashes) is not dict or set(hashes) != set(HOST.MODULE_FILES)
            or not all(_valid_hash(value) for value in hashes.values())
            or type(fixtures) is not dict or not fixtures
            or any(type(name) is not str or not name or not _valid_hash(value) for name, value in fixtures.items())):
        raise ValueError('Complete runtime and fixture source hashes are required')
    jobs, seen, captured = plan.get('jobs'), set(), set()
    if type(jobs) is not list or not jobs:
        raise ValueError('A nonempty original saved fixture plan is required')
    for job in jobs:
        calls = _plan_calls(job)
        COVERAGE.coverage_kind(job)
        if type(job.get('id')) is not str or not job['id'] or job['id'] in seen:
            raise ValueError('Saved plan job IDs must be nonempty and unique')
        seen.add(job['id'])
        if 'execution_kind' in job and job['execution_kind'] not in ('native', 'compatibility'):
            raise ValueError('Invalid saved plan execution classification')
        kinds = job.get('function_execution_kinds', {})
        if (type(kinds) is not dict or set(kinds) - {call['name'] for call in calls}
                or any(value not in ('native', 'compatibility') for value in kinds.values())):
            raise ValueError('Invalid saved plan per-function execution classification')
        declarations = job.get('assertions')
        if type(declarations) is not list or not declarations:
            raise ValueError('Saved plan fixtures require original assertions')
        capture = job.get('capture')
        if capture is not None:
            if (type(capture) is not dict or set(capture) != {'name', 'path'}
                    or type(capture['name']) is not str or not capture['name'] or capture['name'] in captured
                    or type(capture['path']) is not list or not capture['path']
                    or any(type(part) not in (int, str) or (type(part) is int and part < 0) for part in capture['path'])):
                raise ValueError('Saved plan capture names and paths must be valid and unique')
            captured.add(capture['name'])
    return jobs


def bind_record(job, row, captures, *, require_pass_claim=True):
    """Bind one observation to its original request and oracles without dispatch."""
    if type(row) is not dict or row.get('kind') != 'native' or row.get('id') != job['id']:
        raise ValueError('Recorded fixtures must be an exact ordered prefix of the saved plan')
    calls = _plan_calls(job)
    if (('coverage_kind' in row or 'verification_dimension' in row)
            and COVERAGE.coverage_kind(row) != COVERAGE.coverage_kind(job)):
        raise ValueError('Recorded characterization/semantic classification differs from the saved plan')
    envelope = ({'calls': HOST._substitute(job['calls'], captures)} if 'calls' in job else
                {'name': job['name'], 'arguments': HOST._substitute(job['arguments'], captures)})
    if not _same_json(envelope, row.get('input')):
        raise ValueError('Recorded request arguments or capture substitutions differ from the saved plan')
    if not _same_json(row.get('functions'), [call['name'] for call in calls]):
        raise ValueError('Recorded API attribution differs from the saved plan')
    if 'execution_kind' in row and row['execution_kind'] not in ('native', 'compatibility'):
        raise ValueError('Invalid recorded execution classification')
    metadata = row.get('function_executions', [])
    if (type(metadata) is not list or (metadata and (len(metadata) != len(calls)
            or any(type(item) is not dict or type(item.get('step')) is not int or item['step'] != index
                   or item.get('function') != call['name'] or item.get('execution_kind') not in ('native', 'compatibility')
                   for index, (item, call) in enumerate(zip(metadata, calls)))))):
        raise ValueError('Recorded per-step execution attribution differs from the saved plan')
    # Uncertain runner rows intentionally omit these descriptive fields.
    for key, default in (('phase', None), ('verifies_jobs', [])):
        if key in row and not _same_json(row[key], job.get(key, default)):
            raise ValueError('Recorded ' + key + ' differs from the saved plan')
    recorded = row.get('assertions')
    if type(recorded) is not list:
        raise ValueError('Recorded assertions must be a list')
    declarations, position = job['assertions'], 0
    for item in recorded:
        if type(item) is not dict:
            raise ValueError('Malformed recorded assertion')
        if 'expected' not in item:
            if item.get('passed') is not False or not item.get('error'):
                raise ValueError('Missing original assertion declaration')
            continue
        while position < len(declarations) and not _same_json(item['expected'], declarations[position]):
            position += 1
        if position == len(declarations):
            raise ValueError('Recorded assertion differs from the original saved plan oracle')
        position += 1
    response = row.get('result')
    evaluated, recomputed = HOST.evaluate_native(job, response)
    # Complete protocol responses must retain every original oracle. Partial
    # sequence/error responses can retain a planned subset; they cannot invent
    # replacement expectations or promote an unasserted step.
    if (type(response) is dict and response.get('status') == 'ok' and 'error' not in response
            and (recomputed or row.get('passed') is True)):
        if not _same_json(recorded, recomputed):
            raise ValueError('Recorded assertions do not match evaluation of the original saved plan')
    if isinstance(response, dict):
        _checked_assertions(row, response)
    if row.get('passed') is True:
        if not evaluated and require_pass_claim:
            raise ValueError('Claimed pass does not satisfy the original saved plan')
        if evaluated and job.get('capture'):
            capture = job['capture']
            captures[capture['name']] = copy.deepcopy(HOST._at(response, capture['path']))
    return evaluated


def compatibility_result(job, row, response, returned, index):
    """A narrower row classification cannot erase plan/response disclosures."""
    name = _plan_calls(job)[index]['name']
    planned = job.get('function_execution_kinds', {}).get(name, job.get('execution_kind'))
    metadata = row.get('function_executions', [])
    classified = metadata[index]['execution_kind'] if metadata else row.get('execution_kind')
    return (planned == 'compatibility' or classified == 'compatibility'
            or bool(returned.get('compatibility')) or returned.get('native_dispatched') is False
            or bool(response.get('compatibility')) or response.get('native_dispatched') is False)


def validate_bound_run(plan, run):
    jobs = validate_plan_provenance(plan, run)
    rows = run.get('records')
    if type(rows) is not list or len(rows) > len(jobs):
        raise ValueError('Recorded fixtures exceed the saved plan')
    if run.get('status') == 'passed' and len(rows) != len(jobs):
        raise ValueError('A passed run must contain the complete saved plan')
    captures, stopped = {}, False
    for job, row in zip(jobs, rows):
        if stopped:
            raise ValueError('A fixture was recorded after the runner stopped')
        bind_record(job, row, captures)
        stopped = row.get('passed') is not True
    if not _same_json(run.get('captures'), captures):
        raise ValueError('Recorded final captures differ from successful saved-plan responses')
    return jobs


def _provenance(run):
    if type(run) is not dict:
        raise ValueError('A recorded run object is required')
    host, sdk = run.get('host'), run.get('sdk')
    if (type(host) is not dict or type(host.get('vectorworks_year')) is not int or host['vectorworks_year'] != 2027
            or type(host.get('build')) is not int or host['build'] <= 0):
        raise ValueError('Measured Vectorworks 2027 host provenance is required')
    version = host.get('version_tuple')
    if (type(version) is not list or len(version) != 4 or version[0] != 32 or version[3] != 2
            or any(type(part) is not int or part < 0 for part in version)):
        raise ValueError('A complete Windows 2027 host version tuple is required')
    if (type(sdk) is not dict or type(sdk.get('vectorworks_year')) is not int or sdk['vectorworks_year'] != 2027
            or type(sdk.get('sdk_version')) is not int or sdk['sdk_version'] != 3200
            or type(sdk.get('sdk_build')) is not int or sdk['sdk_build'] <= 0):
        raise ValueError('SDK 3200 provenance is required')


def _checked_assertions(row, result):
    """Re-evaluate the recorded declarations, including on partial responses.

    Wrapping the entire parent response lets the same strict predicate evaluator
    check partial-sequence assertions without pretending that sequence succeeded.
    The original response remains unchanged and is preserved in the evidence.
    """
    recorded = row.get('assertions', [])
    if type(recorded) is not list:
        raise ValueError('Recorded assertions must be a list')
    checked = []
    for item in recorded:
        if type(item) is not dict or type(item.get('passed')) is not bool:
            raise ValueError('Each recorded assertion requires a boolean outcome')
        if 'expected' not in item:
            if item['passed'] or not item.get('error'):
                raise ValueError('A passing assertion requires its original declaration')
            checked.append(copy.deepcopy(item))
            continue
        declaration = copy.deepcopy(item['expected'])
        if type(declaration) is not dict or type(declaration.get('path')) is not list:
            raise ValueError('An assertion requires its original declaration and path')
        declaration['path'] = ['result'] + declaration['path']
        _, evaluated = HOST.evaluate_native(
            {'name': '__recorded_assertion__', 'assertions': [declaration]},
            {'status': 'ok', 'function': '__recorded_assertion__', 'result': result})
        if len(evaluated) != 1 or evaluated[0].get('passed') is not item['passed']:
            raise ValueError('Recorded assertion outcome differs from its actual result')
        actual = evaluated[0]
        if ('actual' in item) != ('actual' in actual):
            raise ValueError('Recorded assertion actual value is missing or fabricated')
        if 'actual' in actual and json.dumps(item['actual'], sort_keys=True, allow_nan=False) != json.dumps(actual['actual'], sort_keys=True, allow_nan=False):
            raise ValueError('Recorded assertion actual value differs from the response')
        checked.append(copy.deepcopy(item))
    return checked


def normalize_run(run, *, source_name, source_sha256, plan=None):
    _provenance(run)
    valid_hash = lambda value: type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) is not None
    if type(source_name) is not str or not source_name or not valid_hash(source_sha256):
        raise ValueError('A source filename and SHA-256 digest are required')
    runtime_hashes, fixture_hashes = run.get('source_sha256'), run.get('fixture_source_sha256')
    if (type(runtime_hashes) is not dict or set(runtime_hashes) != set(HOST.MODULE_FILES)
            or not all(valid_hash(value) for value in runtime_hashes.values())
            or type(fixture_hashes) is not dict or not fixture_hashes
            or any(type(key) is not str or not key or not valid_hash(value) for key, value in fixture_hashes.items())):
        raise ValueError('Complete runtime and fixture source hashes are required')
    if type(run.get('schema_version')) is not int or run['schema_version'] != 1 or run.get('execution_path') != 'typed_mcp_tools':
        raise ValueError('Only the typed regression runner format is accepted')
    if run.get('status') not in {'passed', 'failed', 'blocked', 'uncertain'} or not isinstance(run.get('records'), list):
        raise ValueError('A finished run with recorded results is required')
    if not isinstance(run.get('run_id'), str) or not run['run_id']:
        raise ValueError('A run ID is required')
    # Refuse the complete source pair, including unexecuted characterization
    # jobs in a mixed plan. Importing only its successful semantic-looking
    # prefix would conceal the purpose of an exploratory run. Historical
    # semantic plans with no new coverage metadata remain valid.
    planned = plan.get('jobs', []) if type(plan) is dict else []
    for item in (planned if type(planned) is list else []) + run['records']:
        if type(item) is dict and COVERAGE.coverage_kind(item) == 'characterization':
            raise ValueError('Characterization plans/results cannot be imported as semantic SDK coverage; preserve them as observations')
    jobs = validate_bound_run(plan, run)
    records, rejected, uncredited, seen = [], [], [], set()
    stopped = False
    for job, row in zip(jobs, run['records']):
        if stopped:
            raise ValueError('A fixture was recorded after the runner stopped')
        if row.get('kind') != 'native':
            raise ValueError('Only fixture records may be imported; guards never earn API credit')
        if type(row.get('id')) is not str or not row['id']:
            raise ValueError('Each fixture requires a nonempty job ID')
        if row.get('id') in seen:
            raise ValueError('Duplicate fixture job ID')
        seen.add(row['id'])
        envelope, result = row['input'], row['result']
        if type(envelope) is not dict:
            raise ValueError('A typed request envelope is required')
        sequence = 'calls' in envelope
        calls = envelope['calls'] if sequence else [envelope]
        if (type(calls) is not list or not calls or not isinstance(result, dict)
                or any(type(call) is not dict or type(call.get('name')) is not str
                       or type(call.get('arguments')) is not dict for call in calls)):
            raise ValueError('Invalid recorded request/result')
        if row.get('functions') != [call['name'] for call in calls]:
            raise ValueError('Recorded API attribution differs from the actual request')
        base = {'job_id': row['id'], 'phase': row.get('phase'), 'verifies_jobs': row.get('verifies_jobs', []),
                'source_journal': source_name, 'source_journal_sha256': source_sha256,
                'execution': 'typed_mcp_tools', 'runtime_source_sha256': copy.deepcopy(run.get('source_sha256', {})),
                'fixture_source_sha256': copy.deepcopy(run.get('fixture_source_sha256', {})),
                'host': copy.deepcopy(run['host']), 'sdk': copy.deepcopy(run['sdk'])}
        transport = HOST.transport_outcome(result)
        blocked = transport == 'blocked'
        uncertain = transport == 'uncertain' or row.get('status') == 'uncertain'
        if 'status' in row and row['status'] not in {'passed', 'failed', 'blocked', 'uncertain'}:
            raise ValueError('Unknown recorded fixture status')
        if row.get('status') == 'blocked' and not blocked:
            raise ValueError('Blocked fixture requires proof that its request was not dispatched')
        if blocked:
            # Original runners called these failed assertions and recorded
            # passed=False. Preserve those rows as transport evidence only.
            if row.get('passed') is not None and row.get('passed') is not False:
                raise ValueError('An undispatched fixture cannot claim a native outcome')
            if row.get('status') in {'passed', 'uncertain'} or run['status'] == 'passed':
                raise ValueError('Undispatched transport response contradicts its recorded status')
            if not sequence and result.get('function') not in (None, calls[0]['name']):
                raise ValueError('Returned function attribution is incorrect')
            stopped = True
            _checked_assertions(row, result)
            if result.get('code') in HOST.UNCLAIMED_TRANSPORT_CODES:
                uncredited.append(dict(base, status='blocked', native_api_executed=False,
                                       reason='Transport confirmed the queued job was not claimed; no SDK outcome',
                                       request=envelope, result=result))
            else:
                for index, call in enumerate(calls):
                    rejected.append(dict(base, id=run['run_id'] + ':' + row['id'] + ':' + str(index),
                                         name=call['name'], arguments=call['arguments'], result=result,
                                         passed=False, dimension='native_fixture_rejected_before_dispatch'))
            continue
        if ('status' in row and row['status'] != 'uncertain'
                and row.get('passed') is not (row['status'] == 'passed')):
            raise ValueError('Recorded fixture status contradicts its outcome')
        if uncertain and row.get('passed') is not None:
            raise ValueError('An uncertain result cannot claim a boolean outcome')
        if not uncertain and type(row.get('passed')) is not bool:
            raise ValueError('A confirmed fixture requires a boolean outcome')
        if run['status'] == 'passed' and row.get('passed') is not True:
            raise ValueError('A passed run cannot contain a failed or uncertain fixture')
        stopped = row.get('passed') is not True
        assertions = _checked_assertions(row, result)
        if uncertain and sequence:
            uncredited.append(dict(base, reason='Unknown sequence progress; no individual target is assumed executed', request=envelope, result=result))
            continue
        responses = result.get('results', []) if sequence else [result]
        if not isinstance(responses, list) or len(responses) > len(calls):
            raise ValueError('Invalid sequence response length')
        if row.get('passed') is True:
            if not assertions or not all(a.get('passed') is True for a in assertions):
                raise ValueError('A passing fixture requires successful recorded assertions')
            checked_job = dict(envelope, assertions=[a['expected'] for a in assertions])
            if not HOST.evaluate_native(checked_job, result)[0]:
                raise ValueError('A passing sequence requires all returned steps')
        if sequence and result.get('status') == 'ok' and (type(result.get('count')) is not int
                or result['count'] != len(calls) or len(responses) != len(calls)):
            raise ValueError('Successful sequence count differs from the request')
        if sequence and not responses:
            uncredited.append(dict(base, reason='No native step result returned', request=envelope, result=result))
            continue
        for index, (call, response) in enumerate(zip(calls, responses)):
            case_id = run['run_id'] + ':' + row['id'] + ':' + str(index)
            if not isinstance(response, dict) or (not uncertain and response.get('function') != call['name']):
                raise ValueError('Returned function attribution is missing or incorrect')
            if not uncertain and response.get('error') and (response.get('dispatched') is False or response.get('native_dispatched') is False):
                rejected.append(dict(base, id=case_id, name=call['name'], arguments=call['arguments'], result=response,
                                     passed=False, dimension='native_fixture_rejected_before_dispatch'))
                continue
            if (response.get('error') and not uncertain
                    and response.get('dispatched') is not True and response.get('native_dispatched') is not True):
                uncredited.append(dict(base, reason='Error does not establish native dispatch', request=call, result=response))
                continue
            step_assertions = assertions
            status = 'uncertain' if uncertain else ('passed' if row.get('passed') is True else 'failed')
            if sequence and row.get('passed') is not True and not response.get('error'):
                targeted = [a for a in assertions if a.get('expected', {}).get('path', [])[:2] == ['results', index]]
                if not targeted:
                    uncredited.append(dict(base, reason='Incomplete parent fixture; this step has no independent assertion',
                                           request=call, result=response))
                    continue
                status = 'passed' if all(a.get('passed') is True for a in targeted) else 'failed'
                step_assertions = targeted
            if status == 'passed' and (response.get('status') != 'ok' or response.get('error')):
                raise ValueError('An error cannot receive pass credit')
            compatibility = compatibility_result(job, row, result, response, index)
            records.append(dict(base, function=call['name'], test_case=case_id, status=status,
                                execution_kind='compatibility' if compatibility else 'native',
                                input=copy.deepcopy(call['arguments']), result=copy.deepcopy(response),
                                assertions=copy.deepcopy(step_assertions),
                                assertion_scope='parent_job' if sequence else 'result',
                                **({'assertion_parent_result': copy.deepcopy(result)} if sequence else {})))
    return {'records': records, 'adapter_edge_cases': rejected, 'uncredited_results': uncredited}


def merge_run(evidence, run, *, source_name, source_sha256, plan=None, plan_source_name=None, plan_sha256=None):
    _provenance(run)
    if evidence.get('host') != run['host']:
        raise ValueError('Run host provenance differs from the evidence host')
    if (evidence.get('sdk', {}).get('vectorworks_year', 2027) != 2027
            or any(evidence.get('sdk', {}).get(key) != run['sdk'][key] for key in ('sdk_version', 'sdk_build'))):
        raise ValueError('Run SDK provenance differs from the evidence SDK')
    output = copy.deepcopy(evidence)
    normalized = normalize_run(run, source_name=source_name, source_sha256=source_sha256, plan=plan)
    if plan_source_name is None:
        plan_source_name = str(Path(source_name).with_name('plan.json')).replace('\\', '/')
    if plan_sha256 is None:
        plan_sha256 = hashlib.sha256(json.dumps(plan, sort_keys=True, allow_nan=False).encode('utf-8')).hexdigest()
        hash_encoding = 'canonical_json_utf8'
    else:
        hash_encoding = 'file_bytes'
    if type(plan_source_name) is not str or not plan_source_name or not _valid_hash(plan_sha256):
        raise ValueError('Saved plan source name and SHA-256 digest are required')
    for key, identifier in [('records', 'test_case'), ('adapter_edge_cases', 'id')]:
        target = output.setdefault(key, [])
        # Historical cases intentionally inspect several API names under one
        # fixture ID. Identity is API + case, not the case label alone.
        def identity(row):
            return (row['function'], row[identifier]) if key == 'records' else row[identifier]
        existing = {identity(row): row for row in target}
        if len(existing) != len(target):
            raise ValueError('Duplicate IDs already present in target evidence')
        for row in normalized[key]:
            previous = existing.get(identity(row))
            if previous is not None and previous != row:
                raise ValueError('Conflicting evidence for ' + row[identifier])
            if previous is None:
                target.append(row)
                existing[identity(row)] = row
    runs = output.setdefault('regression_runs', {})
    summary = {'status': run['status'], 'source_journal': source_name, 'source_journal_sha256': source_sha256,
               'fixture_source_sha256': copy.deepcopy(run.get('fixture_source_sha256', {})),
               'case_records': len(normalized['records']), 'undispatched_cases': len(normalized['adapter_edge_cases']),
               'uncredited_results': normalized['uncredited_results'], 'full_semantics_verified': False}
    binding = {'schema_version': 1, 'source_plan': plan_source_name, 'source_plan_sha256': plan_sha256,
               'hash_encoding': hash_encoding, 'requests_captures_oracles_provenance_verified': True}
    if run['run_id'] in runs:
        previous = copy.deepcopy(runs[run['run_id']])
        prior_binding = previous.pop('plan_binding', None)
        if previous != summary or (prior_binding is not None and prior_binding != binding):
            raise ValueError('Conflicting source run ID')
    # A valid legacy import keeps identical case records and gains this audit
    # entry only after the complete historical pair has passed the new checks.
    summary['plan_binding'] = binding
    runs[run['run_id']] = summary
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result', type=Path)
    parser.add_argument('--plan', type=Path, help='Original saved plan; defaults to sibling plan.json')
    parser.add_argument('--evidence', type=Path, default=ROOT / 'docs/LIVE_SDK_2027.json')
    args = parser.parse_args()
    raw = args.result.read_bytes()
    run = json.loads(raw.decode('utf-8'))
    plan_path = args.plan if args.plan is not None else args.result.with_name('plan.json')
    plan_raw = plan_path.read_bytes()
    plan = json.loads(plan_raw.decode('utf-8'))
    evidence = json.loads(args.evidence.read_text(encoding='utf-8'))
    merged = merge_run(evidence, run, source_name=args.result.parent.name + '/' + args.result.name,
                       source_sha256=hashlib.sha256(raw).hexdigest(), plan=plan,
                       plan_source_name=plan_path.parent.name + '/' + plan_path.name,
                       plan_sha256=hashlib.sha256(plan_raw).hexdigest())
    # The existing SDK-wide validator checks host/catalog provenance and types.
    from sdk_test_matrix import validate_live_evidence
    catalog = json.loads((ROOT / 'vwx-plugin/sdk_catalog.json').read_text(encoding='utf-8'))
    validate_live_evidence(merged, catalog)
    temporary = args.evidence.with_suffix(args.evidence.suffix + '.tmp')
    temporary.write_text(json.dumps(merged, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
    temporary.replace(args.evidence)
    print(json.dumps({'recorded_cases': len(merged['records']), 'imported_run': run['run_id'], 'status': run['status']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
