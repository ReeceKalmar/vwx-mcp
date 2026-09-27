"""Journaled typed-MCP execution for curated design plans; no raw-script path.

The caller injects an MCP sender and a read-only deployed-source hash reader.
This module never opens a socket, discovers an IPC queue, controls the desktop,
or generates executable Python for the host. The server's normal background
preflight remains in the request path. A guard and its following fixture are
separate menu invocations; the active document must remain unchanged between
them. This is a test runner, not an atomic document lock or a transaction.
"""
from datetime import datetime, timezone
import importlib.util
import json
import ntpath
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location('sdk_design_runner_host', ROOT / 'tools/sdk_host_suite.py')
HOST = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(HOST)
_COVERAGE_SPEC = importlib.util.spec_from_file_location('sdk_design_runner_coverage', ROOT / 'tools/sdk_regression_suite.py')
COVERAGE = importlib.util.module_from_spec(_COVERAGE_SPEC)
_COVERAGE_SPEC.loader.exec_module(COVERAGE)


def render_typed_job(job, captures):
    """Serialize only the two normal typed SDK tools, never execute_script."""
    if job.get('kind') != 'native' or 'cases' in job or 'code' in job:
        raise ValueError('Only curated native SDK fixtures are accepted')
    if 'calls' in job:
        if 'name' in job or 'arguments' in job:
            raise ValueError('Ambiguous fixture request')
        return {'command': 'sdk_sequence', 'params': {'calls': HOST._substitute(job['calls'], captures)}}
    return {'command': 'sdk_call', 'params': {'name': job['name'],
                                              'arguments': HOST._substitute(job['arguments'], captures)}}


def _guard_request():
    return {'command': 'sdk_sequence', 'params': {'calls': [
        {'name': 'GetFPathName', 'arguments': {}}, {'name': 'GetVersion', 'arguments': {}}]}}


def _check_guard(response, expected_path):
    try:
        if type(response) is not dict:
            raise ValueError('Guard response is not an object')
        if response.get('error'):
            return response
        if (response.get('status') != 'ok' or 'error' in response
                or type(response.get('count')) is not int or response['count'] != 2
                or type(response.get('results')) is not list or len(response['results']) != 2
                or any(type(item) is not dict or item.get('status') != 'ok' or 'error' in item
                       or item.get('function') != name for name, item in
                       zip(('GetFPathName', 'GetVersion'), response['results']))):
            return {'error': 'Typed document/version guard did not complete', 'code': 'SDK_DESIGN_GUARD'}
        path, version = [item['result'] for item in response['results']]
    except (KeyError, TypeError, ValueError):
        return {'error': 'Incomplete typed document/version guard', 'code': 'SDK_DESIGN_GUARD'}
    if type(path) is not str or not path or ntpath.normcase(ntpath.normpath(path)) != ntpath.normcase(expected_path):
        return {'error': 'Exact disposable document is not active', 'code': 'SDK_SUITE_DOCUMENT', 'actual_path': path}
    if (type(version) not in (list, tuple) or len(version) != 4
            or any(type(part) is not int or part < 0 for part in version)
            or version[0] != 32 or version[3] != 2):
        return {'error': 'Vectorworks 2027 is required', 'code': 'SDK_SUITE_VERSION', 'actual_version': version}
    return None


def run_design_plan(send_tool, plan, journal_path, *, deployed_source_hashes):
    """Run with no retries, recording every typed guard and fixture request.

    ``send_tool(request)`` must route ``command``/``params`` through the normal
    MCP server, not its underlying file IPC. ``deployed_source_hashes()`` reads
    the actual installed catalog/runtime/generated/sequences files, returning
    filename-to-SHA256 strings; it is called again before every fixture. Its
    invocation is local and read-only. No hash result is inferred from a local
    source tree or from an API's existence.
    """
    if not callable(send_tool) or not callable(deployed_source_hashes):
        raise TypeError('Explicit MCP sender and deployed-source hash reader are required')
    expected_path = HOST._document_path(plan['document_path'])
    hashes = plan.get('source_sha256')
    if not isinstance(hashes, dict) or set(hashes) != set(HOST.MODULE_FILES):
        raise ValueError('Complete catalog/runtime/generated/sequences provenance is required')
    jobs = plan.get('jobs')
    if not isinstance(jobs, list) or not jobs:
        raise ValueError('At least one curated native fixture is required')
    # Refuse an accidental contract/raw-source plan before the first guard.
    if any(job.get('kind') != 'native' or 'code' in job or 'cases' in job for job in jobs):
        raise ValueError('Typed design runner accepts native fixture plans only')
    declared = COVERAGE.characterization_families()
    declared.update(name.split(':', 1)[1] for name in tuple(declared))
    coverage = [COVERAGE.coverage_kind(job) for job in jobs]
    if any(job.get('fixture_family') in declared and kind != 'characterization' for job, kind in zip(jobs, coverage)):
        raise ValueError('Declared characterization family cannot receive semantic coverage')
    captures, records, native_passed, compatibility_passed = {}, [], set(), set()
    characterization_native, characterization_compatibility = set(), set()
    result = {'schema_version': 1, 'run_id': plan['run_id'], 'document_path': expected_path,
              'source_sha256': hashes, 'status': 'running', 'records': records, 'captures': captures,
              'native_functions_passed': [], 'compatibility_functions_passed': [],
              'characterization_native_functions_observed': [], 'characterization_compatibility_functions_observed': [],
              'adapter_functions_passed': [], 'native_semantics_fully_verified': False,
              'execution_path': 'typed_mcp_tools', 'limitations': list(plan['limitations']) + [
                  'Document/version guards run immediately before each fixture in a separate menu invocation; the document must not be switched between them.',
                  'Only actual semantic fixture results receive test credit; guard calls, characterization observations and local provenance checks receive none.']}
    with Path(journal_path).open('x', encoding='utf-8') as stream:
        def journal(event):
            stream.write(json.dumps(dict(event, utc=datetime.now(timezone.utc).isoformat()),
                                    ensure_ascii=False, allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

        def stop(status, job, error):
            result.update(status=status, error=error.get('error', str(error)),
                          error_code=error.get('code'), stopped_job=job['id'])
            if status == 'uncertain':
                result['uncertain_job'] = job['id']
            journal({'event': 'stop', 'job_id': job['id'], 'status': status, 'detail': error})

        def send(request, job, phase):
            journal({'event': 'intent', 'job_id': job['id'], 'phase': phase, 'request': request})
            response = HOST._unwrap(send_tool(request))
            journal({'event': 'response', 'job_id': job['id'], 'phase': phase, 'response': response})
            return response

        journal({'event': 'start', 'run_id': plan['run_id'], 'document_path': expected_path,
                 'source_sha256': hashes, 'plan_summary': plan['summary'], 'execution_path': 'typed_mcp_tools'})
        for job, purpose in zip(jobs, coverage):
            sent = False
            try:
                actual_hashes = deployed_source_hashes()
                journal({'event': 'deployment_check', 'job_id': job['id'], 'actual_source_sha256': actual_hashes})
                if not isinstance(actual_hashes, dict) or any(actual_hashes.get(name) != value for name, value in hashes.items()):
                    stop('failed', job, {'error': 'Deployed SDK files differ from this plan', 'code': 'SDK_SUITE_SOURCE'})
                    break
                # Resolve captures before any host operation, so malformed plans
                # fail locally without even executing a read-only guard.
                request = render_typed_job(job, captures)
                sent = True
                guard = send(_guard_request(), job, 'guard')
                guard_transport = HOST.transport_outcome(guard)
                if guard_transport:
                    stop(guard_transport, job, guard)
                    break
                guard_error = _check_guard(guard, expected_path)
                if guard_error:
                    stop('failed', job, guard_error)
                    break
                response = send(request, job, 'fixture')
                transport = HOST.transport_outcome(response)
                if transport:
                    record = {'id': job['id'], 'functions': HOST._functions(job), 'kind': 'native',
                              'coverage_kind': purpose, 'verification_dimension': job.get('verification_dimension'),
                              'phase': job.get('phase'), 'verifies_jobs': job.get('verifies_jobs', []),
                              'passed': None, 'status': transport, 'input': request['params'],
                              'result': response, 'assertions': [],
                              'native_api_executed': False if transport == 'blocked' else None}
                    records.append(record)
                    journal({'event': 'case_result', **record})
                    stop(transport, job, response)
                    break
                passed, assertions = HOST.evaluate_native(job, response)
                record = {'id': job['id'], 'functions': HOST._functions(job), 'kind': 'native',
                          'coverage_kind': purpose, 'verification_dimension': job.get('verification_dimension'),
                          'phase': job.get('phase'), 'verifies_jobs': job.get('verifies_jobs', []),
                          'input': request['params'], 'result': response, 'assertions': assertions,
                          'passed': passed, **HOST.execution_evidence(job, response)}
                records.append(record)
                journal({'event': 'case_result', **record})
                if not passed:
                    stop('failed', job, response if response.get('error') else
                         {'error': 'Native fixture assertion failed', 'code': 'SDK_DESIGN_ASSERTION'})
                    break
                for execution in record['function_executions']:
                    if purpose == 'characterization':
                        destination = (characterization_compatibility if execution['execution_kind'] == 'compatibility'
                                       else characterization_native)
                    else:
                        destination = compatibility_passed if execution['execution_kind'] == 'compatibility' else native_passed
                    destination.add(execution['function'])
                if job.get('capture'):
                    captures[job['capture']['name']] = HOST._at(response, job['capture']['path'])
            except Exception as error:
                # A lost response after any send does not establish whether the
                # native mutation happened. Never replay even a partial run.
                stop('uncertain' if sent else 'failed', job,
                     {'error': str(error), 'code': 'SDK_DESIGN_SEND' if sent else 'SDK_DESIGN_LOCAL'})
                break
        else:
            result['status'] = 'passed'
        result['native_functions_passed'] = sorted(native_passed)
        result['compatibility_functions_passed'] = sorted(compatibility_passed)
        result['characterization_native_functions_observed'] = sorted(characterization_native)
        result['characterization_compatibility_functions_observed'] = sorted(characterization_compatibility)
        result['characterization_jobs_completed'] = sum(r.get('passed') is True and r.get('coverage_kind') == 'characterization'
                                                       for r in records)
        passed_ids = {record['id'] for record in records if record.get('passed') is True}
        all_api_ids = {}
        for job, purpose in zip(jobs, coverage):
            if purpose == 'characterization':
                continue
            for name in HOST._functions(job):
                all_api_ids.setdefault(name, set()).add(job['id'])
        result['functions_all_planned_cases_passed'] = sorted(name for name, ids in all_api_ids.items() if ids <= passed_ids)
        journal({'event': 'finish', 'status': result['status'],
                 'native_functions_passed': result['native_functions_passed'],
                 'compatibility_functions_passed': result['compatibility_functions_passed'],
                 'characterization_native_functions_observed': result['characterization_native_functions_observed'],
                 'characterization_compatibility_functions_observed': result['characterization_compatibility_functions_observed'],
                 'characterization_jobs_completed': result['characterization_jobs_completed'],
                 'functions_all_planned_cases_passed': result['functions_all_planned_cases_passed'],
                 'native_semantics_fully_verified': False})
    return result
