"""Offline server routing and claimed-job uncertainty tests."""
import ast
import importlib.util
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def server_namespace():
    source = ast.parse((ROOT / 'mcp-server/vwx_mcp_server.py').read_text(encoding='utf-8'))
    names = {'vw_versions', '_plugin_dir', 'VwxFileTransport', 'get_vwx_connection'}
    keep = [n for n in source.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    ns = dict(os=os, json=json, logging=logging, threading=threading, time=time, uuid=uuid,
              logger=logging.getLogger('test_server'), VWX_TRANSPORT='file', _vwx_connection=None,
              VWX_SOCKET_TIMEOUT=1, VWX_ALIVE_MAX_AGE=8, VWX_ALIVE_GRACE=0)
    spec = importlib.util.spec_from_file_location('server_test_maintenance', ROOT / 'mcp-server/maintenance.py')
    maintenance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(maintenance)
    ns['bridge_lease'] = maintenance
    exec(compile(ast.Module(body=keep, type_ignores=[]), '<server>', 'exec'), ns)
    return ns


class Server2027Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'APPDATA': str(self.base), 'VWX_VW_VERSION': '2027'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.ns = server_namespace()

    def install(self, name):
        folder = self.base / 'Nemetschek/Vectorworks/2027/Plug-ins' / name
        folder.mkdir(parents=True)
        for file in ('commands.py', 'vwx_pump.py'):
            (folder / file).touch()
        return folder

    def test_server_selects_same_canonical_folder_as_runner(self):
        self.install('VW-MCP')
        canonical = self.install('VWX-MCP')
        self.assertEqual(Path(self.ns['_plugin_dir']()), canonical)
        (canonical / 'commands.py').unlink()
        self.assertEqual(Path(self.ns['_plugin_dir']()).name, 'VW-MCP')

    def test_incomplete_explicit_directory_does_not_fall_back(self):
        self.install('VWX-MCP')
        os.environ['VWX_PLUGIN_DIR'] = str(self.base)
        with self.assertRaisesRegex(RuntimeError, 'must contain'):
            self.ns['_plugin_dir']()

    def test_non_file_transport_rejected_before_constructing_or_reusing_connection(self):
        cached = object()
        self.ns['_vwx_connection'] = cached
        constructor = Mock(side_effect=AssertionError('No transport may be constructed'))
        with patch.dict(self.ns, {'VwxFileTransport': constructor}):
            for transport in ('tcp', 'socket', 'http', '', None):
                with self.subTest(transport=transport):
                    self.ns['VWX_TRANSPORT'] = transport
                    with self.assertRaisesRegex(RuntimeError, 'requires VWX_TRANSPORT=file'):
                        self.ns['get_vwx_connection']()
                    self.assertIs(self.ns['_vwx_connection'], cached)
        constructor.assert_not_called()
        self.assertEqual(list(self.base.iterdir()), [])

    def test_file_transport_reuses_only_a_valid_file_connection(self):
        folder = self.install('VWX-MCP')
        self.ns['_vwx_connection'] = object()
        transport = self.ns['get_vwx_connection']()
        self.assertIsInstance(transport, self.ns['VwxFileTransport'])
        self.assertEqual(Path(transport.base), folder)
        self.assertIs(self.ns['get_vwx_connection'](), transport)
        transport.disconnect()
        self.assertIs(self.ns['get_vwx_connection'](), transport)
        self.assertEqual(list((folder / 'ipc/jobs').iterdir()), [])

    def test_paused_unclaimed_job_is_discarded(self):
        folder = self.install('VWX-MCP')
        transport = self.ns['VwxFileTransport']()
        transport.bridge_state = lambda: (True, True, 0)
        result = transport.send_command('draw_rectangle')
        self.assertEqual(result['code'], 'VW_BRIDGE_PAUSED')
        self.assertEqual(list((folder / 'ipc/jobs').iterdir()), [])

    def test_paused_after_claim_never_advises_retry(self):
        folder = self.install('VWX-MCP')
        transport = self.ns['VwxFileTransport']()
        def claimed():
            for job in (folder / 'ipc/jobs').glob('*.json'):
                job.unlink()
            return True, True, 0
        transport.bridge_state = claimed
        result = transport.send_command('create_wall')
        self.assertEqual(result['code'], 'VW_DISPATCH_UNCONFIRMED')
        self.assertIn('Do not retry', result['error'])

    def test_missing_heartbeat_after_claim_reports_uncertainty(self):
        folder = self.install('VWX-MCP')
        transport = self.ns['VwxFileTransport']()
        def claimed():
            for job in (folder / 'ipc/jobs').glob('*.json'):
                job.unlink()
            return False, False, float('inf')
        transport.bridge_state = claimed
        result = transport.send_command('create_wall')
        self.assertEqual(result['code'], 'VW_DISPATCH_UNCONFIRMED')
        self.assertIn('Do not retry', result['error'])

    def test_timeout_discard_proves_unclaimed_and_does_not_prescribe_shortcut_input(self):
        folder = self.install('VWX-MCP')
        transport = self.ns['VwxFileTransport']()
        self.ns['VWX_SOCKET_TIMEOUT'] = 0
        result = transport.send_command('sdk_call', {'name': 'GetTextSpace', 'arguments': {}})
        self.assertEqual(result['code'], 'VW_JOB_UNCLAIMED')
        self.assertIs(result['dispatched'], False)
        self.assertIn('native.scheduler.json', result['error'])
        self.assertNotIn('Ctrl+Shift+B', result['error'])
        self.assertEqual(list((folder / 'ipc/jobs').iterdir()), [])

    def test_timeout_after_claim_never_claims_undispatched_or_recreates_job(self):
        folder = self.install('VWX-MCP')
        transport = self.ns['VwxFileTransport']()
        self.ns['VWX_SOCKET_TIMEOUT'] = 0
        def lost_claim(path):
            # Simulate the host consuming the request before timeout cleanup.
            os.remove(path)
            return False
        transport._discard = lost_claim
        result = transport.send_command('create_wall')
        self.assertEqual(result['code'], 'VW_DISPATCH_STUCK')
        self.assertNotIn('dispatched', result)
        self.assertIn('Do NOT retry', result['error'])
        self.assertEqual(list((folder / 'ipc/jobs').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
