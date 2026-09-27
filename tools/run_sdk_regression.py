"""Opt-in native regression runner over normal typed stdio MCP tools.

Requires an explicit disposable document and installed plug-in path. Uses no
desktop automation or raw file-IPC execution. An existing journal/run directory
is never resumed: a previous mutation may have executed without a response.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

from sdk_regression_suite import ROOT, build_plan, load, validate_plan, verify_fixture_sources


HOST = load('regression_cli_host', ROOT / 'tools/sdk_host_suite.py')


def write_exclusive(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def host_provenance(response):
    """Only the measured typed response supplies app/platform/build identity."""
    if (not isinstance(response, dict) or response.get('status') != 'ok' or 'error' in response
            or response.get('function') != 'GetVersionEx' or 'compatibility' in response
            or any(key in response and response[key] is not True for key in ('dispatched', 'native_dispatched'))):
        raise ValueError('Typed GetVersionEx host provenance did not complete')
    version = response.get('result')
    if (not isinstance(version, list) or len(version) != 5
            or any(type(value) is not int for value in version)
            or version[0] != 32 or version[3] != 2 or version[4] <= 0
            or any(value < 0 for value in version[1:3])):
        raise ValueError('Vectorworks 2027 for Windows and a positive measured build are required')
    return {'vectorworks_year': 2027, 'build': version[4], 'version_tuple': version[:4]}


def provenance_failure(response):
    """Classify a prelude failure without attributing any fixture execution."""
    blocked = HOST.transport_outcome(response) == 'blocked'
    return {'status': 'blocked' if blocked else 'uncertain', 'phase': 'host_provenance',
            'error': response.get('error', 'Typed host provenance is invalid') if type(response) is dict else 'Malformed host provenance',
            'error_code': response.get('code', 'SDK_SUITE_PROVENANCE') if type(response) is dict else 'SDK_SUITE_PROVENANCE',
            'records': [], 'host': None, 'native_functions_passed': [], 'compatibility_functions_passed': [],
            'adapter_functions_passed': [], 'native_semantics_fully_verified': False,
            'provenance_response': response}


async def execute(plan, plugin_dir, output_dir, *, python=sys.executable, timeout=45):
    if type(timeout) not in (int, float) or not 10 <= timeout <= 900:
        raise ValueError('timeout must be 10..900 seconds')
    # Complete all validation before importing or starting an MCP client. In
    # particular, a modal call at the end must prevent every earlier mutation.
    validate_plan(plan)
    verify_fixture_sources(plan)
    plugin_dir = Path(plugin_dir).resolve(strict=True)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    write_exclusive(output_dir / 'plan.json', plan)
    def hashes():
        return {name: hashlib.sha256((plugin_dir / name).read_bytes()).hexdigest() for name in plan['source_sha256']}
    if hashes() != plan['source_sha256']:
        raise ValueError('Deployed SDK files do not match this plan; no MCP connection made')
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    env = dict(os.environ, VWX_PLUGIN_DIR=str(plugin_dir), VWX_TRANSPORT='file',
               VWX_VW_VERSION='2027', VWX_BACKGROUND_MODE='1', VWX_SDK_TOOLS='0',
               VWX_CACHE_TTL='0', VWX_SOCKET_TIMEOUT=str(max(1, timeout - 5)))
    transport = StdioTransport(python, [str(ROOT / 'mcp-server/vwx_mcp_server.py')], env=env, cwd=str(ROOT))
    runner = load('regression_typed_runner', ROOT / 'tools/sdk_design_runner.py')
    loop = asyncio.get_running_loop()
    async with Client(transport, init_timeout=60, timeout=timeout) as client:
        async def invoke(request):
            # The runner emits only typed tools; enforce that boundary again at
            # the actual transport, even for an accidentally altered sender.
            if request['command'] not in {'sdk_call', 'sdk_sequence'}:
                raise ValueError('Only typed SDK tools are accepted')
            response = await client.call_tool(request['command'], request['params'])
            return json.loads(response.content[0].text)
        provenance_request = {'command': 'sdk_call', 'params': {'name': 'GetVersionEx', 'arguments': {}}}
        write_exclusive(output_dir / 'provenance-intent.json', provenance_request)
        provenance_response = await invoke(provenance_request)
        write_exclusive(output_dir / 'provenance-response.json', provenance_response)
        try:
            measured_host = host_provenance(provenance_response)
        except ValueError:
            measured_host = None
            result = dict(provenance_failure(provenance_response), schema_version=1, run_id=plan['run_id'],
                          document_path=plan['document_path'], source_sha256=plan['source_sha256'],
                          execution_path='typed_mcp_tools', fixture_execution_started=False)
        else:
            count = 0
            def send(request):
                nonlocal count
                result = asyncio.run_coroutine_threadsafe(invoke(request), loop).result(timeout=timeout + 5)
                count += 1
                if count % 50 == 0:
                    print('Completed typed requests:', count, flush=True)
                return result
            result = await asyncio.to_thread(runner.run_design_plan, send, plan, output_dir / 'journal.jsonl', deployed_source_hashes=hashes)
    result['fixture_source_sha256'] = plan['fixture_source_sha256']
    result['host'] = measured_host
    catalog = json.loads((ROOT / 'vwx-plugin/sdk_catalog.json').read_text(encoding='utf-8'))
    result['sdk'] = {key: catalog[key] for key in ('vectorworks_year', 'sdk_version', 'sdk_build')}
    write_exclusive(output_dir / 'result.json', result)
    print(json.dumps({'status': result['status'], 'records': len(result['records']),
                      'native_functions_passed': len(result['native_functions_passed']),
                      'stopped_job': result.get('stopped_job'), 'output': str(output_dir)}, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--document', required=True, help='Exact saved VWX-MCP-SDK-TEST-*.vwx drawing; must remain active')
    parser.add_argument('--plugin-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path, help='New directory, never reused or resumed')
    parser.add_argument('--family', action='append', help='Registered provider:family; repeat to select several')
    parser.add_argument('--run-id')
    parser.add_argument('--timeout', type=int, default=45)
    parser.add_argument('--execute', action='store_true', help='Explicitly connect and execute; default only writes an offline plan')
    args = parser.parse_args()
    if args.timeout < 10 or args.timeout > 900:
        parser.error('--timeout must be 10..900 seconds')
    plan = build_plan(args.document, run_id=args.run_id, selected=args.family)
    if not args.execute:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        write_exclusive(args.output_dir / 'plan.json', plan)
        print(json.dumps({'status': 'planned_not_executed', 'output': str(args.output_dir),
                          'summary': plan['summary']}, indent=2))
        return 0
    result = asyncio.run(execute(plan, args.plugin_dir, args.output_dir, timeout=args.timeout))
    return 0 if result['status'] == 'passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
