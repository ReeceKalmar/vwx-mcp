"""Run independent native fixture families sequentially, never replaying a run.

The default CLI only writes plans. --execute uses the ordinary typed MCP runner.
An attributed successful response with a failed semantic assertion may stop one
family and continue the next independent family. Native errors, document/source
guard failures, unavailable bridge state and uncertain outcomes stop the batch.
"""
import argparse
import asyncio
import hashlib
import json
import math
import re
import time
from pathlib import Path

from sdk_regression_suite import ROOT, build_plan, coverage_kind, load, providers, validate_plan, verify_fixture_sources
from run_sdk_regression import execute, write_exclusive

HOST = load('batch_native_evaluator', ROOT / 'tools/sdk_host_suite.py')
RUNNER = load('batch_typed_requests', ROOT / 'tools/sdk_design_runner.py')
_DIAGNOSTIC_IO = load('batch_diagnostic_io', ROOT / 'mcp-server/diagnostic_io.py')
read_diagnostic_text = _DIAGNOSTIC_IO.read_diagnostic_text


def make_plans(document, run_id, selected=None, *, include_diagnostics=False):
    if type(run_id) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,60}', run_id):
        raise ValueError('Batch run_id must contain 1..60 letters, digits, underscores or hyphens')
    if type(include_diagnostics) is not bool:
        raise ValueError('include_diagnostics must be a boolean')
    if selected is None:
        selected = [prefix + ':' + family for prefix, (module, _) in providers().items()
                    for family in module.FAMILIES
                    if family not in getattr(module, 'CHARACTERIZATION_FAMILIES', ())
                    and (include_diagnostics or family not in getattr(module, 'DIAGNOSTIC_FAMILIES', ()))]
    # Validate the entire selection before creating any output or host connection.
    combined = build_plan(document, run_id=run_id, selected=selected)
    return [build_plan(document, run_id=run_id + '-' + hashlib.sha256(family.encode()).hexdigest()[:10],
                       selected=[family]) for family in combined['summary']['fixture_families']]


def validate_batch(plans):
    if type(plans) is not list or not plans:
        raise ValueError('A nonempty list of independent plans is required')
    families, run_ids, documents = set(), set(), set()
    for plan in plans:
        validate_plan(plan)
        verify_fixture_sources(plan)
        summary = plan.get('summary')
        selection = summary.get('fixture_families') if type(summary) is dict else None
        if (type(selection) is not list or len(selection) != 1 or type(selection[0]) is not str
                or not selection[0] or selection[0] in families or plan['run_id'] in run_ids
                or any(job['fixture_family'] != selection[0] for job in plan['jobs'])):
            raise ValueError('Each plan needs one distinct family and a distinct run ID')
        families.add(selection[0])
        run_ids.add(plan['run_id'])
        documents.add(plan['document_path'])
    if len(documents) != 1:
        raise ValueError('A batch must target one exact disposable document')


def bridge_readiness(plugin_dir, *, now=None, max_age=8):
    """Read only heartbeat/queue diagnostics; never clear or fabricate state.

    last_trigger_state describes a historical attempt. In particular an idle
    queue may retain modal_dialog_open after a dialog closes. Do not treat that
    label as a fresh observation or manipulate windows based on it.
    """
    now = time.time() if now is None else now
    if type(now) not in (int, float) or not _finite(now):
        raise ValueError('A finite clock value is required')
    if type(max_age) not in (int, float) or not _finite(max_age) or max_age < 0:
        raise ValueError('max_age must be a finite nonnegative number')
    ipc = Path(plugin_dir) / 'ipc'
    try:
        scheduler = json.loads(read_diagnostic_text(ipc / 'native.scheduler.json'))
        alive = read_diagnostic_text(ipc / 'native.alive').split()
        if (type(scheduler) is not dict or len(alive) != 2 or alive[1] not in {'0', '1'}
                or not alive[0].isdigit()):
            raise ValueError('Malformed bridge diagnostics')
        stamp = scheduler.get('updated_epoch')
        if (type(stamp) is not int or not -2 <= now - stamp <= max_age
                or not -2 <= now - int(alive[0]) <= max_age):
            raise ValueError('Bridge heartbeat is stale or from a future clock')
        if (type(scheduler.get('schema_version')) is not int or scheduler['schema_version'] != 1
                or type(scheduler.get('sdk_version')) is not int or scheduler['sdk_version'] != 3200
                or scheduler.get('timer_active') is not True
                or scheduler.get('paused') is not False or alive[1] != '0'
                or type(scheduler.get('pending')) is not bool
                or type(scheduler.get('queued_jobs')) is not int or scheduler['queued_jobs'] < 0
                or type(scheduler.get('process_id')) is not int or scheduler['process_id'] <= 0
                or type(scheduler.get('modifiers_pending_restore')) is not bool):
            raise ValueError('Bridge is paused, stopped, or has malformed scheduler state')
        if not (ipc / 'jobs').is_dir() or any((ipc / 'jobs').glob('*.json')):
            raise ValueError('Bridge job queue is missing or not empty')
        if scheduler['pending'] or scheduler['modifiers_pending_restore'] or scheduler['queued_jobs']:
            return {'ready': False, 'code': 'VW_BRIDGE_SETTLING', 'scheduler': scheduler,
                    'error': 'Waiting for fresh idle diagnostics after the outer menu invocation'}
        return {'ready': True, 'scheduler': scheduler,
                'meaning': 'Fresh idle bridge diagnostics only; not current modal, document ownership or native success proof'}
    except (OSError, ValueError, TypeError) as error:
        return {'ready': False, 'error': str(error)}


async def settle_readiness(plugin_dir, readiness, *, sleep=asyncio.sleep):
    """Allow only fresh, empty-queue completion diagnostics to settle.

    This sends no host calls and never retries a fixture. Paused, stale, queued
    or malformed state stops immediately; a pending invocation gets at most
    three seconds before the batch stops with its observations preserved.
    """
    observations = []
    for attempt in range(31):
        state = readiness(plugin_dir)
        if (type(state) is not dict or state.get('ready') is True
                or state.get('code') != 'VW_BRIDGE_SETTLING'):
            break
        observations.append(state)
        if attempt < 30:
            await sleep(.1)
    if observations and type(state) is dict:
        state = dict(state, completion_wait_observations=observations)
    return state


def _finite(value):
    try:
        return math.isfinite(value)
    except (TypeError, ValueError, OverflowError):
        return False


def _same_json(actual, expected):
    """Compare recorded transport data without bool/int coercion or NaN."""
    return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)


def _records_match_plan(plan, result, *, complete):
    """Bind evidence to this plan and recompute every credited assertion.

    This does not import evidence or establish host correctness. It prevents a
    malformed/stale executor result from permitting more native work or a pass.
    """
    try:
        if any(not _same_json(result.get(key), plan[key]) for key in
               ('run_id', 'document_path', 'sdk', 'source_sha256', 'fixture_source_sha256')):
            return False
        host = result.get('host')
        if (type(host) is not dict or type(host.get('vectorworks_year')) is not int
                or host['vectorworks_year'] != 2027 or type(host.get('build')) is not int
                or host['build'] <= 0 or type(host.get('version_tuple')) is not list
                or len(host['version_tuple']) != 4
                or any(type(part) is not int or part < 0 for part in host['version_tuple'])
                or host['version_tuple'][0] != 32 or host['version_tuple'][3] != 2
                or result.get('execution_path') != 'typed_mcp_tools'):
            return False
        records = result.get('records')
        if type(records) is not list or not records or len(records) > len(plan['jobs']):
            return False
        if complete and len(records) != len(plan['jobs']):
            return False
        captures = {}
        for index, row in enumerate(records):
            job = plan['jobs'][index]
            request = RUNNER.render_typed_job(job, captures)
            if (type(row) is not dict or row.get('id') != job['id'] or row.get('kind') != 'native'
                    or not _same_json(row.get('functions'), HOST._functions(job))
                    or not _same_json(row.get('input'), request['params'])):
                return False
            if (('coverage_kind' in row or 'verification_dimension' in row)
                    and coverage_kind(row) != coverage_kind(job)):
                return False
            passed, assertions = HOST.evaluate_native(job, row.get('result'))
            expected_pass = complete or index != len(records) - 1
            if passed is not expected_pass or row.get('passed') is not passed:
                return False
            if not _same_json(row.get('assertions'), assertions):
                return False
            if passed and job.get('capture'):
                captures[job['capture']['name']] = HOST._at(row['result'], job['capture']['path'])
        return _same_json(result.get('captures'), captures)
    except (KeyError, TypeError, ValueError, IndexError, OverflowError):
        return False


def assertion_failure_only(result, plan=None):
    """Only a measured semantic mismatch permits another independent family."""
    if (type(result) is not dict or result.get('status') != 'failed' or result.get('error_code') != 'SDK_DESIGN_ASSERTION'
            or type(result.get('records')) is not list or not result['records']):
        return False
    row = result['records'][-1]
    if type(row) is not dict or type(row.get('input')) is not dict:
        return False
    response = row.get('result')
    assertions = row.get('assertions')
    if (row.get('passed') is not False or row.get('id') != result.get('stopped_job')
            or type(response) is not dict or response.get('status') != 'ok' or 'error' in response
            or type(assertions) is not list or not assertions
            or not any(item.get('passed') is False for item in assertions if type(item) is dict)
            or any(type(item) is not dict or type(item.get('passed')) is not bool or 'error' in item
                   or type(item.get('expected')) is not dict or 'actual' not in item for item in assertions)):
        return False
    calls = row.get('input', {}).get('calls')
    if calls is None:
        name = row['input'].get('name')
        attributed = type(name) is str and bool(name) and response.get('function') == name
    else:
        returned = response.get('results')
        attributed = (type(calls) is list and bool(calls) and all(type(call) is dict for call in calls)
                and type(returned) is list and type(response.get('count')) is int
                and response['count'] == len(calls) == len(returned)
                and all(type(item) is dict and item.get('status') == 'ok' and 'error' not in item
                        and type(call.get('name')) is str and bool(call['name'])
                        and item.get('function') == call['name'] for call, item in zip(calls, returned)))
    if not attributed:
        return False
    try:
        probe = dict(row['input'], assertions=[item['expected'] for item in assertions])
        passed, recomputed = HOST.evaluate_native(probe, response)
        if passed or not _same_json(assertions, recomputed):
            return False
    except (TypeError, ValueError, KeyError, OverflowError):
        return False
    return plan is None or _records_match_plan(plan, result, complete=False)


def _passed_family(plan, result):
    return (result.get('status') == 'passed' and not any(key in result for key in ('error', 'error_code', 'stopped_job'))
            and _records_match_plan(plan, result, complete=True))


def reserve_batch(plans, output_dir, *, offline):
    validate_batch(plans)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'schema_version': 1, 'execution_requested': not offline,
                'batch_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'document_path': plans[0]['document_path'], 'families': []}
    for i, plan in enumerate(plans):
        family = plan['summary']['fixture_families'][0]
        directory = '%03d-%s' % (i + 1, hashlib.sha256(family.encode()).hexdigest()[:12])
        manifest['families'].append({'family': family, 'run_id': plan['run_id'], 'directory': directory,
                                     'planned_jobs': len(plan['jobs']),
                                     'characterization_jobs': sum(coverage_kind(job) == 'characterization' for job in plan['jobs'])})
    write_exclusive(output / 'batch-plan.json', manifest)
    # Keep every exact plan, including families never reached by execution.
    (output / 'plans').mkdir()
    for item, plan in zip(manifest['families'], plans):
        write_exclusive(output / 'plans' / (item['directory'] + '.json'), plan)
    return output, manifest


async def execute_batch(plans, plugin_dir, output_dir, *, timeout=45, executor=execute, readiness=bridge_readiness):
    if type(timeout) not in (int, float) or not 10 <= timeout <= 900:
        raise ValueError('timeout must be 10..900 seconds')
    output, manifest = reserve_batch(plans, output_dir, offline=False)
    result = {'schema_version': 1, 'status': 'running', 'families': [],
              'pending_families': [item['family'] for item in manifest['families']],
              'native_semantics_fully_verified': False}
    for item, plan in zip(manifest['families'], plans):
        executor_started = False
        try:
            verify_fixture_sources(plan)
            state = await settle_readiness(plugin_dir, readiness)
            write_exclusive(output / (item['directory'] + '-readiness.json'), state)
            if type(state) is not dict or state.get('ready') is not True:
                error = state.get('error', 'Bridge is not ready') if type(state) is dict else 'Malformed bridge readiness'
                result.update(status='blocked', error=error)
                break
            executor_started = True
            measured = await executor(plan, plugin_dir, output / item['directory'], timeout=timeout)
            if (type(measured) is not dict or measured.get('status') not in {'passed', 'failed', 'blocked', 'uncertain'}
                    or type(measured.get('records')) is not list):
                raise ValueError('Malformed family result; execution cannot be established')
            passed = _passed_family(plan, measured)
            semantic_failure = assertion_failure_only(measured, plan)
            if measured['status'] == 'passed' and not passed:
                raise ValueError('Family pass is incomplete or does not match the planned evidence')
            result['pending_families'].remove(item['family'])
            result['families'].append(dict(item, status=measured['status'], records=len(measured.get('records', [])),
                                            error_code=measured.get('error_code'), stopped_job=measured.get('stopped_job')))
            if not passed and not semantic_failure:
                result.update(status=measured['status'], error=measured.get('error', 'Family did not complete'),
                              error_code=measured.get('error_code'))
                break
        except asyncio.CancelledError:
            result.update(status='uncertain' if executor_started else 'blocked', error='Batch execution was cancelled')
            if executor_started:
                result['uncertain_family'] = item['family']
            write_exclusive(output / 'batch-result.json', result)
            raise
        except Exception as error:
            # The executor may have sent a mutation before raising. Do not
            # infer no effect, continue another family, or replay this plan.
            result.update(status='uncertain' if executor_started else 'blocked', error=str(error))
            if executor_started:
                result['uncertain_family'] = item['family']
            break
    else:
        result['status'] = ('completed_with_failures' if any(item['status'] != 'passed' for item in result['families'])
                            else 'passed')
    write_exclusive(output / 'batch-result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--document', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--family', action='append')
    parser.add_argument('--plugin-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=45)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--include-diagnostics', action='store_true',
                        help='Include semantic diagnostic families; characterization families require explicit --family')
    args = parser.parse_args()
    plans = make_plans(args.document, args.run_id, args.family, include_diagnostics=args.include_diagnostics)
    if args.execute:
        result = asyncio.run(execute_batch(plans, args.plugin_dir, args.output_dir, timeout=args.timeout))
        print(json.dumps(result, indent=2))
        return 0 if result['status'] == 'passed' else 2
    _, manifest = reserve_batch(plans, args.output_dir, offline=True)
    print(json.dumps({'status': 'planned_not_executed', 'families': len(plans),
                      'jobs': sum(item['planned_jobs'] for item in manifest['families'])}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
