"""Opt-in, read-only typed MCP delivery check; no desktop input or native API credit.

Example: python tools/check_sdk_background_delivery.py --plugin-dir PATH
    --output-dir NEW_DIRECTORY --count 100 --execute
The journal is never resumed. Diagnostics and source files are read locally;
every host request uses sdk_call(GetVersionEx) over the ordinary stdio server.
"""
import argparse
import asyncio
from contextlib import AsyncExitStack
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
_DIAGNOSTIC_SPEC = importlib.util.spec_from_file_location(
    'delivery_diagnostic_io', ROOT / 'mcp-server/diagnostic_io.py')
_DIAGNOSTIC_IO = importlib.util.module_from_spec(_DIAGNOSTIC_SPEC)
_DIAGNOSTIC_SPEC.loader.exec_module(_DIAGNOSTIC_IO)
read_diagnostic_text = _DIAGNOSTIC_IO.read_diagnostic_text
PYTHON_FILES = ('commands.py', 'vwx_pump.py', 'BridgeStart_MenuCommand.py', 'vs_index.json',
                'vs_index_meta.json', 'sdk_catalog.json', 'sdk_generated.py', 'sdk_runtime.py', 'sdk_sequences.py')
NATIVE_FILES = ('VwxBridge.vlb', 'VwxBridge.vwr')
FILES = PYTHON_FILES + NATIVE_FILES
COUNTERS = ('posts', 'foreground_posts', 'background_posts', 'runner_completions_observed',
            'trigger_failures', 'acknowledgment_timeouts', 'menu_invocations', 'menu_returns', 'broker_rejections')
REQUEST = {'command': 'sdk_call', 'params': {'name': 'GetVersionEx', 'arguments': {}}}


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes(root=ROOT):
    root = Path(root)
    return {name: _hash(root / ('vwx-plugin' if name in PYTHON_FILES else 'native/Output/2027/Release') / name)
            for name in FILES}


def deployment_hashes(plugin_dir):
    plugin_dir = Path(plugin_dir)
    return {name: _hash((plugin_dir if name in PYTHON_FILES else plugin_dir.parent) / name) for name in FILES}


def validate_hashes(hashes):
    if (type(hashes) is not dict or set(hashes) != set(FILES)
            or any(type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value) for value in hashes.values())):
        raise ValueError('Complete SHA-256 provenance for all eleven deployment files is required')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def read_readiness(plugin_dir, *, now=None, max_age=8):
    """Fresh v4 scheduler and empty queue; reads never alter IPC files."""
    now = time.time() if now is None else now
    if not _finite(now) or not _finite(max_age) or max_age < 0:
        raise ValueError('Finite clock and nonnegative age limit required')
    ipc = Path(plugin_dir) / 'ipc'
    scheduler = None
    try:
        scheduler = json.loads(read_diagnostic_text(ipc / 'native.scheduler.json'))
        alive = read_diagnostic_text(ipc / 'native.alive').split()
        if (type(scheduler) is not dict or len(alive) != 2 or not alive[0].isdigit() or alive[1] != '0'
                or type(scheduler.get('updated_epoch')) is not int
                or not -2 <= now - scheduler['updated_epoch'] <= max_age
                or not -2 <= now - int(alive[0]) <= max_age):
            raise ValueError('Stale, paused or malformed heartbeat')
        validate_scheduler(scheduler)
        jobs = ipc / 'jobs'
        if not jobs.is_dir() or any(jobs.glob('*.json')):
            raise ValueError('Queue is missing or contains a job; do not retry or clear it')
        if _busy(scheduler):
            return {'ready': False, 'code': 'SETTLING', 'scheduler': scheduler}
        return {'ready': True, 'scheduler': scheduler}
    except (OSError, ValueError, TypeError) as error:
        return {'ready': False, 'code': 'NOT_READY', 'error': str(error), 'scheduler': scheduler}


def _busy(value):
    return (value['pending'] or value['queued_jobs'] or value['runner_stamp'] > value['completion_stamp']
            or value['broker_message_pending'] or value['menu_invocation_active'])


def validate_scheduler(value):
    if (type(value) is not dict or value.get('scheduler') != 'sdk-named-menu-broker-ack-v4'
            or value.get('menu_caption') != 'VWX Bridge Start'
            or value.get('frame_source') != 'GS_GetMainHWND'
            or value.get('frame_available') is not True or value.get('broker_window_available') is not True
            or any(type(value.get(key)) is not bool for key in
                   ('frame_has_win32_menu', 'broker_message_pending', 'menu_invocation_active', 'menu_return_available'))
            or type(value.get('schema_version')) is not int or value['schema_version'] != 1
            or type(value.get('sdk_version')) is not int or value['sdk_version'] != 3200
            or value.get('timer_active') is not True or value.get('paused') is not False
            or type(value.get('process_id')) is not int or value['process_id'] <= 0
            or type(value.get('pending')) is not bool
            or any(value.get(key) is not False for key in ('keyboard_state_modified', 'global_input', 'focus_changed_by_bridge'))
            or value.get('modifiers_pending_restore', False) is not False):
        raise ValueError('Incomplete or unsafe v4 scheduler telemetry')
    for key in COUNTERS + ('queued_jobs', 'runner_stamp', 'completion_stamp'):
        if type(value.get(key)) is not int or value[key] < 0:
            raise ValueError('Invalid scheduler counter: ' + key)
    if (value['posts'] != value['background_posts'] + value['foreground_posts']
            or value['runner_completions_observed'] > value['posts']
            or (value['pending'] is False and value['runner_completions_observed'] != value['posts'])
            or not value['menu_returns'] <= value['menu_invocations'] <= value['posts']
            or (value['menu_invocation_active'] is False and value['menu_returns'] != value['menu_invocations'])
            or (value['pending'] is False and value['menu_returns'] != value['posts'])
            or (value['broker_message_pending'] and value['menu_invocation_active'])
            or ((value['broker_message_pending'] or value['menu_invocation_active']) and not value['pending'])):
        raise ValueError('Inconsistent scheduler counters')
    if (value['menu_return_available'] != (value['menu_returns'] > 0)
            or (value['menu_return_available'] and
                (type(value.get('last_menu_return')) is not int or not -32768 <= value['last_menu_return'] <= 32767))
            or (not value['menu_return_available'] and 'last_menu_return' in value)):
        raise ValueError('Incomplete menu return telemetry')


def host_identity(response):
    if (type(response) is not dict or response.get('status') != 'ok' or 'error' in response
            or response.get('function') != 'GetVersionEx' or 'compatibility' in response
            or any(key in response and response[key] is not True for key in ('native_dispatched', 'dispatched'))):
        raise ValueError('A successful native GetVersionEx response is required')
    version = response.get('result')
    if (type(version) is not list or len(version) != 5 or any(type(v) is not int for v in version)
            or version[0] != 32 or version[3] != 2 or version[4] <= 0 or any(v < 0 for v in version[1:3])):
        raise ValueError('Measured host must be Vectorworks 2027 on Windows with a positive build')
    return {'vectorworks_year': 2027, 'version_tuple': version[:4], 'build': version[4]}


def telemetry_delta(before, after, count):
    validate_scheduler(before)
    validate_scheduler(after)
    if before['process_id'] != after['process_id']:
        raise ValueError('Vectorworks process changed during delivery test')
    delta = {key: after[key] - before[key] for key in COUNTERS}
    if any(value < 0 for value in delta.values()):
        raise ValueError('Scheduler counters reset during delivery test')
    expected = dict(posts=count, foreground_posts=0, background_posts=count,
                    runner_completions_observed=count, trigger_failures=0, acknowledgment_timeouts=0,
                    menu_invocations=count, menu_returns=count, broker_rejections=0)
    if delta != expected:
        raise ValueError('Delivery counters do not establish exclusive background completion: ' + str(delta))
    if _busy(after) or after['menu_return_available'] is not True:
        raise ValueError('Final scheduler is not idle after the named menu command returned')
    return delta


def write_exclusive(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


async def run_delivery(send, plugin_dir, output_dir, *, expected_hashes, count=100,
                       hash_reader=deployment_hashes, readiness=read_readiness, sleep=asyncio.sleep):
    """Injected async typed sender; no request retries or semantic coverage credit."""
    if type(count) is not int or not 1 <= count <= 1000:
        raise ValueError('count must be an integer from 1 to 1000')
    validate_hashes(expected_hashes)
    expected_hashes = copy.deepcopy(expected_hashes)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    result = {'schema_version': 1, 'scope': 'read-only typed MCP background delivery',
              'status': 'running', 'requested_reads': count, 'attempted_reads': 0, 'completed_reads': 0,
              'background_verified': False, 'host': None, 'records': [], 'errors': [],
              'native_functions_passed': [], 'native_semantics_fully_verified': False,
              'expected_source_sha256': expected_hashes, 'execution_path': 'typed_mcp_stdio',
              'limitations': ['This tests delivery and identity, not GetVersionEx or other API semantics.',
                              'Bridge telemetry is not an independent measurement of the desktop foreground process.',
                              'No request is retried and no interrupted journal is resumed.']}
    write_exclusive(output_dir / 'plan.json', {'count': count, 'request': REQUEST, 'source_sha256': expected_hashes})
    interruption = None
    with (output_dir / 'journal.jsonl').open('x', encoding='utf-8', newline='\n') as journal:
        def record(event, **detail):
            journal.write(json.dumps(dict(event=event, utc=datetime.now(timezone.utc).isoformat(), **detail),
                                     ensure_ascii=False, allow_nan=False) + '\n')
            journal.flush()
            os.fsync(journal.fileno())

        async def snapshot(phase):
            for attempt in range(31):
                state = readiness(plugin_dir)
                record('readiness', phase=phase, observation=state)
                if type(state) is dict and type(state.get('scheduler')) is dict:
                    # Preserve the final busy/stale snapshot too: interrupted
                    # delivery needs actual counters, not only an error label.
                    result['scheduler_' + phase] = copy.deepcopy(state['scheduler'])
                if type(state) is not dict or state.get('code') != 'SETTLING' or attempt == 30:
                    break
                await sleep(.1)
            if type(state) is not dict or state.get('ready') is not True:
                raise ValueError('Bridge is not fresh and idle: ' + str(state))
            value = state.get('scheduler')
            validate_scheduler(value)
            if _busy(value):
                raise ValueError('Readiness cannot claim idle while the scheduler is busy')
            return copy.deepcopy(value)

        try:
            result['source_sha256_before'] = hash_reader(plugin_dir)
            validate_hashes(result['source_sha256_before'])
            record('deployment', phase='before', hashes=result['source_sha256_before'])
            if result['source_sha256_before'] != expected_hashes:
                raise ValueError('Deployment differs from reviewed sources; no MCP request sent')
            result['scheduler_before'] = await snapshot('before')
            for index in range(count):
                request = copy.deepcopy(REQUEST)
                record('intent', index=index + 1, request=request)
                result['attempted_reads'] += 1
                try:
                    response = await send(request)
                except Exception as error:
                    result['status'] = 'uncertain'
                    raise ValueError('Request outcome unknown; no retry: ' + str(error)) from error
                record('response', index=index + 1, response=response)
                result['records'].append({'index': index + 1, 'response': copy.deepcopy(response)})
                if (type(response) is dict and response.get('error') and response.get('code') in
                        {'VW_DISPATCH_UNCONFIRMED', 'VW_DISPATCH_STUCK', 'VW_UNKNOWN'}):
                    result['status'] = 'uncertain'
                if (type(response) is dict and response.get('error') and
                        response.get('code') in {'VW_JOB_UNCLAIMED', 'VW_BRIDGE_DOWN', 'VW_BRIDGE_PAUSED'}):
                    result['status'] = ('uncertain' if response.get('dispatched') is True
                                        or response.get('native_dispatched') is True or response.get('results') else 'blocked')
                identity = host_identity(response)
                if result['host'] is None:
                    result['host'] = identity
                elif result['host'] != identity:
                    raise ValueError('Measured host identity changed during delivery test')
                result['completed_reads'] += 1
                if (index + 1) % 25 == 0:
                    print('Verified read responses:', index + 1, flush=True)
        except (Exception, asyncio.CancelledError, KeyboardInterrupt) as error:
            if not isinstance(error, Exception):
                interruption = error
                result['status'] = 'uncertain'
                message = type(error).__name__ + ': interrupted without retry'
            else:
                message = str(error)
            if result['status'] == 'running':
                result['status'] = 'failed'
            result['errors'].append(message)
            record('stop', status=result['status'], error=message)
        # Read local evidence even after a failed send; never send a recovery call.
        for phase in ('deployment', 'readiness'):
            try:
                if phase == 'deployment':
                    hashes = hash_reader(plugin_dir)
                    result['source_sha256_after'] = copy.deepcopy(hashes)
                    record('deployment', phase='after', hashes=hashes)
                    validate_hashes(hashes)
                    if hashes != expected_hashes:
                        raise ValueError('Deployment source drift detected')
                else:
                    result['scheduler_after'] = await snapshot('after')
            except (Exception, asyncio.CancelledError, KeyboardInterrupt) as error:
                if not isinstance(error, Exception):
                    interruption = error
                    result['status'] = 'uncertain'
                    message = type(error).__name__ + ': interrupted without retry'
                else:
                    message = str(error)
                result['errors'].append(message)
                record('postcheck_failure', phase=phase, error=message)
        if (all(type(result.get('scheduler_' + phase)) is dict for phase in ('before', 'after'))
                and all(type(result['scheduler_' + phase].get(key)) is int
                        for phase in ('before', 'after') for key in COUNTERS)):
            result['telemetry_delta'] = {key: result['scheduler_after'][key] - result['scheduler_before'][key] for key in COUNTERS}
        if not result['errors']:
            try:
                telemetry_delta(result['scheduler_before'], result['scheduler_after'], count)
                result.update(status='passed', background_verified=True)
            except ValueError as error:
                result['errors'].append(str(error))
        if result['errors'] and result['status'] == 'running':
            result['status'] = 'failed'
        record('finished', status=result['status'], background_verified=result['background_verified'])
    write_exclusive(output_dir / 'result.json', result)
    if interruption is not None:
        # Preserve normal cancellation semantics after durable incomplete
        # evidence, without sending any recovery request to Vectorworks.
        raise interruption
    return result


async def execute(plugin_dir, output_dir, *, count=100, timeout=45, python=sys.executable):
    if not _finite(timeout) or not 10 <= timeout <= 900:
        raise ValueError('timeout must be 10..900 seconds')
    plugin_dir = Path(plugin_dir).resolve(strict=True)
    # The client is created lazily, after local deployment/readiness validation.
    async with AsyncExitStack() as stack:
        client = None
        async def send(request):
            nonlocal client
            if request != REQUEST:
                raise ValueError('Only the exact read-only GetVersionEx request is permitted')
            if client is None:
                from fastmcp import Client
                from fastmcp.client.transports import StdioTransport
                env = dict(os.environ, VWX_PLUGIN_DIR=str(plugin_dir), VWX_TRANSPORT='file',
                           VWX_VW_VERSION='2027', VWX_BACKGROUND_MODE='1', VWX_SDK_TOOLS='0',
                           VWX_CACHE_TTL='0', VWX_SOCKET_TIMEOUT=str(max(1, timeout - 5)))
                transport = StdioTransport(python, [str(ROOT / 'mcp-server/vwx_mcp_server.py')], env=env, cwd=str(ROOT))
                client = await stack.enter_async_context(Client(transport, init_timeout=60, timeout=timeout))
            response = await client.call_tool(request['command'], request['params'])
            if getattr(response, 'is_error', False):
                raise ValueError('MCP returned a tool error')
            if len(response.content) != 1 or not hasattr(response.content[0], 'text'):
                raise ValueError('Expected one typed JSON text response')
            return json.loads(response.content[0].text)
        return await run_delivery(send, plugin_dir, output_dir, expected_hashes=source_hashes(), count=count)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--count', type=int, default=100)
    parser.add_argument('--timeout', type=int, default=45)
    parser.add_argument('--execute', action='store_true', help='Explicitly permit read-only typed MCP requests')
    args = parser.parse_args()
    if not 1 <= args.count <= 1000 or not 10 <= args.timeout <= 900:
        parser.error('count must be 1..1000 and timeout 10..900')
    if not args.execute:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        write_exclusive(args.output_dir / 'plan.json', {'count': args.count, 'request': REQUEST, 'status': 'planned_not_executed'})
        print('Planned only; use a new output directory with --execute to run.')
        return 0
    result = asyncio.run(execute(args.plugin_dir, args.output_dir, count=args.count, timeout=args.timeout))
    print(json.dumps({key: result.get(key) for key in ('status', 'attempted_reads', 'completed_reads', 'background_verified', 'telemetry_delta', 'errors')}, indent=2))
    return 0 if result['status'] == 'passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
