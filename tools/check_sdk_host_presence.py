"""Inspect every installed SDK callable through ordinary typed MCP discovery.

Presence is not execution, semantic verification, or permission to invoke APIs
outside their supported context. Callable inspection does not invoke its targets;
GetVersionEx is called separately to establish the running host's identity.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON_FILES = ('commands.py', 'vwx_pump.py', 'BridgeStart_MenuCommand.py',
                'vs_index.json', 'vs_index_meta.json', 'sdk_catalog.json',
                'sdk_generated.py', 'sdk_runtime.py', 'sdk_sequences.py',
                'project_guard.py', 'landscape_takeoff.py')


def validate_page(page, names, offset, limit):
    if (type(page) is not dict or page.get('error') or type(page.get('sdk_version')) is not int or page['sdk_version'] != 3200
            or type(page.get('total')) is not int or page['total'] != len(names)
            or type(page.get('offset')) is not int or page['offset'] != offset
            or type(page.get('functions')) is not list):
        raise ValueError('Malformed, failed, or mismatched SDK discovery page')
    expected = names[offset:offset + limit]
    entries = page['functions']
    if (len(entries) != len(expected) or any(type(item) is not dict or item.get('name') != name
                                           for item, name in zip(entries, expected))):
        raise ValueError('SDK discovery names are missing, duplicated, unexpected, or reordered')
    for item in entries:
        if 'host_callable' not in item or type(item['host_callable']) not in (bool, type(None)):
            raise ValueError('Missing or invalid installed callable observation')
        error = item.get('host_inspection_error')
        if item['host_callable'] is None:
            if type(error) is not str or not error:
                raise ValueError('Unknown callable presence requires its inspection error')
        elif error is not None:
            raise ValueError('A failed inspection cannot claim known presence')
    return entries


def summarize(entries, names):
    if [entry['name'] for entry in entries] != names:
        raise ValueError('Complete ordered SDK coverage is required')
    return {'sdk_functions_total': len(names),
            'host_callable': [entry['name'] for entry in entries if entry['host_callable'] is True],
            'host_missing_or_noncallable': [entry['name'] for entry in entries if entry['host_callable'] is False],
            'host_inspection_failed': [entry['name'] for entry in entries if entry['host_callable'] is None],
            'native_semantic_coverage_credit': False}


async def execute(plugin_dir, output, *, page_size=200):
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    from run_sdk_regression import host_provenance, write_exclusive
    from run_sdk_regression_batch import bridge_readiness, settle_readiness
    if type(page_size) is not int or not 1 <= page_size <= 200:
        raise ValueError('page_size must be 1..200')
    plugin_dir = Path(plugin_dir).resolve(strict=True)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    def hashes(directory):
        return {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in PYTHON_FILES}
    expected_hashes = hashes(ROOT / 'vwx-plugin')
    if hashes(plugin_dir) != expected_hashes:
        raise ValueError('Deploy matching discovery/runtime files before checking installed availability')
    def verify_deployment():
        if hashes(plugin_dir) != expected_hashes:
            raise ValueError('Deployment changed during presence inspection')
    names = sorted(json.loads((ROOT / 'vwx-plugin/vs_index.json').read_text(encoding='utf-8')))
    state = {'status': 'started', 'source_sha256': expected_hashes,
             'native_semantic_coverage_credit': False, 'entries': []}
    write_exclusive(output / 'intent.json', dict(state, expected_sdk_names=names, page_size=page_size))
    try:
        readiness = await settle_readiness(plugin_dir, bridge_readiness)
        write_exclusive(output / 'readiness.json', readiness)
        if readiness.get('ready') is not True:
            raise ValueError('Bridge is not idle: ' + readiness.get('error', 'unavailable'))
        env = dict(os.environ, VWX_PLUGIN_DIR=str(plugin_dir), VWX_TRANSPORT='file', VWX_VW_VERSION='2027',
                   VWX_BACKGROUND_MODE='1', VWX_SDK_TOOLS='0', VWX_CACHE_TTL='0', VWX_SOCKET_TIMEOUT='40')
        transport = StdioTransport(sys.executable, [str(ROOT / 'mcp-server/vwx_mcp_server.py')], env=env, cwd=str(ROOT))
        async with Client(transport, init_timeout=60, timeout=50) as client:
            verify_deployment()
            response = json.loads((await client.call_tool('sdk_call', {'name': 'GetVersionEx', 'arguments': {}})).content[0].text)
            write_exclusive(output / 'host-response.json', response)
            verify_deployment()
            state['host'] = host_provenance(response)
            for offset in range(0, len(names), page_size):
                verify_deployment()
                request = {'offset': offset, 'limit': page_size, 'include_presence': True}
                write_exclusive(output / ('page-%04d-intent.json' % offset), request)
                response = json.loads((await client.call_tool('sdk_list', request)).content[0].text)
                write_exclusive(output / ('page-%04d-response.json' % offset), response)
                # Preserve the raw observation, but do not credit a page whose
                # deployed source changed while the native job was outstanding.
                verify_deployment()
                entries = validate_page(response, names, offset, page_size)
                state['entries'].extend({key: item[key] for key in ('name', 'host_callable', 'host_inspection_error') if key in item}
                                        for item in entries)
        verify_deployment()
        state.update(summary=summarize(state['entries'], names), status='inspection_complete')
    except BaseException as error:
        # Cancellation and a user's interruption are incomplete observations too.
        # Persist that state and re-raise; no request is resumed or replayed.
        state.update(status='incomplete', error=str(error) or type(error).__name__)
        raise
    finally:
        write_exclusive(output / 'result.json', state)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    state = asyncio.run(execute(args.plugin_dir, args.output_dir))
    print(json.dumps({'status': state['status'], 'inspected': len(state['entries']),
                      'missing': len(state['summary']['host_missing_or_noncallable']),
                      'inspection_failed': len(state['summary']['host_inspection_failed']),
                      'native_semantic_coverage_credit': False}))


if __name__ == '__main__':
    main()
