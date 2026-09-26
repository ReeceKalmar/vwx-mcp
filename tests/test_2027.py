"""Offline regression tests. These do not claim live Vectorworks compatibility."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class PumpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        spec = importlib.util.spec_from_file_location('pump_test', ROOT/'vwx-plugin/vwx_pump.py')
        self.pump = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.pump)
        for name, rel in {'_IPC':'ipc', '_JOBS':'ipc/jobs', '_RESULTS':'ipc/results',
                          '_STAMP':'ipc/pump.stamp', '_LOG':'bridge.log'}.items():
            setattr(self.pump, name, str(Path(self.temp.name)/rel))
        self.pump._housekeep()
        self.calls = []
        self.pump._dispatch = lambda cmd, params: self.calls.append(cmd) or {'ok':True}

    def job(self, n, command='get_document_info'):
        name = '%04d' % n
        (Path(self.pump._JOBS)/(name+'.json')).write_text(json.dumps(
            {'_cid':name, 'type':command, 'params':{}}))

    def test_one_job_per_invocation_and_fifo(self):
        self.job(1, 'draw_rectangle')
        self.job(2)
        self.assertEqual(self.pump.pump_all(), 1)
        self.assertEqual(self.calls, ['draw_rectangle'])
        self.assertEqual(len(self.pump._list_jobs()), 1)
        self.assertEqual(self.pump.pump_all(), 1)
        self.assertEqual(self.calls, ['draw_rectangle', 'get_document_info'])

    def test_notification_never_dispatches_reads(self):
        self.job(1)
        self.assertEqual(self.pump.pump_readonly(), 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.pump._list_jobs()), 1)

    def test_job_arriving_mid_dispatch_waits_for_next_invocation(self):
        self.job(1)
        self.pump._dispatch = lambda *args: self.job(2) or {'ok':True}
        self.pump.pump_all()
        self.assertEqual(self.pump._list_jobs(), ['0002.json'])

    def test_reentrant_dispatch_is_refused(self):
        self.job(1)
        self.job(2)
        nested = []
        self.pump._dispatch = lambda *args: nested.append(self.pump.pump_all()) or {}
        self.pump.pump_all()
        self.assertEqual(nested, [0])
        self.assertEqual(len(self.pump._list_jobs()), 1)

    def test_claim_is_consumed_before_native_crash_and_not_replayed(self):
        self.job(1, 'create_wall')
        def crash(*args):
            self.assertEqual(self.pump._list_jobs(), [])
            raise SystemExit('simulate fatal host exit')
        self.pump._dispatch = crash
        with self.assertRaises(SystemExit):
            self.pump.pump_all()
        self.assertFalse(self.pump._pumping)
        self.assertEqual(list(Path(self.pump._JOBS).iterdir()), [])
        self.assertIn('START cid=0001 cmd=create_wall', Path(self.pump._LOG).read_text())


class VersionTests(unittest.TestCase):
    def setUp(self):
        # Exercise actual server routing helpers without importing FastMCP or
        # starting a server/writing a manifest into an installed VW folder.
        tree = ast.parse((ROOT/'mcp-server/vwx_mcp_server.py').read_text(encoding='utf-8'))
        keep = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name in ('vw_versions', '_plugin_dir')]
        self.ns = {'os':os, 'json':json}
        exec(compile(ast.Module(body=keep, type_ignores=[]), 'server_helpers', 'exec'), self.ns)

    def test_newer_install_does_not_change_target(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.ns['vw_versions'](), ['2027'])

    def test_wrong_explicit_host_rejected(self):
        with patch.dict(os.environ, {'VWX_VW_VERSION':'2026'}):
            with self.assertRaisesRegex(RuntimeError, '2027'):
                self.ns['_plugin_dir']()

    def test_bad_custom_directory_does_not_fall_back(self):
        with patch.dict(os.environ, {'VWX_VW_VERSION':'2027',
                                     'VWX_PLUGIN_DIR':'missing-test-plugin-dir'}):
            with self.assertRaisesRegex(RuntimeError, 'does not exist'):
                self.ns['_plugin_dir']()

    def test_index_matches_provenance_and_2027_api(self):
        raw = (ROOT/'vwx-plugin/vs_index.json').read_bytes()
        idx = json.loads(raw)
        meta = json.loads((ROOT/'vwx-plugin/vs_index_meta.json').read_text())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), meta['index_sha256'])
        self.assertEqual(len(idx), meta['function_count'])
        self.assertEqual(meta['sdk_version'], 3200)
        self.assertIn('Prot_GetAppMode', idx)
        self.assertNotIn('Prot_GetLicenseType', idx)


if __name__ == '__main__':
    unittest.main()
