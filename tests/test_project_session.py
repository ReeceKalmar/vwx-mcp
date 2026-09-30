"""Cross-client ownership and same-job drawing checks; no installed host access."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_bridge_maintenance as fixtures

ROOT = Path(__file__).resolve().parents[1]
MAINT = fixtures.MAINT
PROJECT = MAINT.project_module()
TOKEN, OTHER = 'c' * 64, 'd' * 64
CID = '012345abcdef'


class ProjectSessionTests(unittest.TestCase):
    refresh = fixtures.BridgeMaintenanceTests.refresh

    def setUp(self):
        fixtures.BridgeMaintenanceTests.setUp(self)
        self.drawing = self.base / 'Landscape.vwx'
        self.drawing.write_bytes(b'disposable offline fixture')
        self.expected = PROJECT.guard.canonical_path(str(self.drawing))

    def acquire(self, token=TOKEN):
        return PROJECT.acquire(self.base, token, str(self.drawing), 'planting agent', coordinator=MAINT)

    def release(self, token=TOKEN):
        return PROJECT.release(self.base, token, coordinator=MAINT)

    def status(self, token=''):
        return PROJECT.status(self.base, token, coordinator=MAINT)

    def error(self, code, call, *args, **kwargs):
        with self.assertRaises((PROJECT.ProjectError, MAINT.MaintenanceError)) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertIs(caught.exception.response()['dispatched'], False)
        self.assertNotIn(TOKEN, str(caught.exception))

    def envelope(self, command='draw_rectangle', params=None, token=TOKEN):
        return {'token': token, 'command': command, 'params': params or {}}

    def publish(self, command='project_execute', params=None, cid=CID):
        with MAINT.publication_guard(self.base, command, params or self.envelope(), cid) as safe:
            path = self.ipc / 'jobs' / (cid + '.json')
            path.write_text(json.dumps({'type': command, 'params': safe, '_cid': cid}), encoding='utf-8')
        return safe

    def test_owner_identity_is_persistent_hashed_and_tokens_never_enter_jobs_or_status(self):
        result = self.acquire()
        stored = json.loads((self.base / PROJECT.LEASE_FILE).read_text(encoding='utf-8'))
        self.assertEqual(stored['token_sha256'], hashlib.sha256(TOKEN.encode('ascii')).hexdigest())
        self.assertEqual(stored['expected_path'], self.expected)
        self.assertEqual(stored['host_process_id'], 2468)
        self.assertTrue(result['owned'])
        self.assertFalse(self.status(OTHER)['owned'])
        self.assertTrue(self.status(TOKEN)['owned'])
        self.assertNotIn('token_sha256', self.status())
        safe = self.publish()
        self.assertNotIn('token', safe)
        for path in self.base.rglob('*.json'):
            self.assertNotIn(TOKEN, path.read_text(encoding='utf-8'))
        self.assertEqual(safe['lease_id'], stored['lease_id'])

    def test_nonowners_cannot_publish_read_write_sdk_or_batch_jobs(self):
        self.acquire()
        for command in ('ping', 'draw_rectangle', 'sdk_call', '_batch', 'bridge_maintenance'):
            with self.subTest(command=command):
                self.error('VWX_PROJECT_HELD', self.publish, command, {'token': TOKEN, 'calls': []})
        self.error('VWX_PROJECT_TOKEN', self.publish, params=self.envelope(token=OTHER))
        self.error('VWX_PROJECT_TOKEN', self.release, OTHER)
        self.assertEqual(list((self.ipc / 'jobs').iterdir()), [])
        self.assertFalse((self.base / MAINT.PUBLICATIONS_DIR).exists())

    def test_maintenance_and_project_acquisition_are_mutually_exclusive(self):
        self.acquire()
        self.error('VWX_PROJECT_HELD', MAINT.acquire, self.base, OTHER)
        self.release()
        MAINT.acquire(self.base, OTHER)
        self.error('VWX_MAINTENANCE_HELD', self.acquire)

    def test_old_owner_pid_and_timestamp_never_enable_stealing(self):
        self.acquire()
        path = self.base / PROJECT.LEASE_FILE
        value = json.loads(path.read_text(encoding='utf-8'))
        value.update(created_epoch=0, owner_server_pid=2147483647)
        path.write_text(json.dumps(value), encoding='utf-8')
        before = path.read_bytes()
        self.error('VWX_PROJECT_HELD', self.acquire, OTHER)
        self.error('VWX_PROJECT_TOKEN', self.release, OTHER)
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(self.status(TOKEN)['owned'])

    def test_acquire_requires_existing_absolute_drawing_owner_and_token(self):
        for path in ('Landscape.vwx', str(self.base / 'missing.vwx'), str(self.base / 'wrong.txt'), ''):
            self.error('VWX_PROJECT_DOCUMENT', PROJECT.acquire, self.base, TOKEN, path, 'owner', coordinator=MAINT)
        for owner in ('', ' ', 'line\nbreak', 'x' * 161):
            self.error('VWX_PROJECT_OWNER', PROJECT.acquire, self.base, TOKEN, str(self.drawing), owner, coordinator=MAINT)
        for token in ('', 'X' * 64, 'f' * 63, None, True):
            self.error('VWX_PROJECT_TOKEN', self.acquire, token)
        self.assertFalse((self.base / PROJECT.LEASE_FILE).exists())

    def test_malformed_lease_blocks_all_clients_without_rewriting_state(self):
        self.acquire()
        path = self.base / PROJECT.LEASE_FILE
        original = json.loads(path.read_text(encoding='utf-8'))
        variants = [None, {}, dict(original, schema_version=True), dict(original, lease_id=True),
                    dict(original, token_sha256='bad'), dict(original, created_epoch=float('nan')),
                    dict(original, created_epoch=10 ** 400),
                    dict(original, host_process_id=False), dict(original, owner='bad\nlabel'),
                    dict(original, expected_path='relative.vwx'), dict(original, unexpected=True)]
        for value in variants:
            with self.subTest(value=value):
                path.write_text(json.dumps(value), encoding='utf-8')
                before = path.read_bytes()
                for action in (self.status, self.release, self.acquire, self.publish):
                    self.error('VWX_PROJECT_STATE', action)
                self.error('VWX_PROJECT_STATE', MAINT.acquire, self.base, OTHER)
                self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list((self.ipc / 'jobs').iterdir()), [])

    def test_unreadable_lease_path_never_looks_like_an_absent_owner(self):
        self.acquire()
        target = self.base / PROJECT.LEASE_FILE
        before = target.read_bytes()
        actual_lstat = Path.lstat
        def denied(path):
            if path == target:
                raise PermissionError('lease metadata inaccessible')
            return actual_lstat(path)
        with patch.object(Path, 'lstat', denied):
            for action in (self.status, self.release, self.acquire, self.publish):
                self.error('VWX_PROJECT_STATE', action)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(list((self.ipc / 'jobs').iterdir()), [])

    def test_release_and_further_jobs_cannot_clear_uncertain_publication(self):
        self.acquire()
        self.publish()
        (self.ipc / 'jobs' / (CID + '.json')).unlink()  # consumed without a result
        marker = self.base / MAINT.PUBLICATIONS_DIR / (CID + '.json')
        self.error('VWX_PROJECT_NOT_IDLE', self.release)
        self.error('VWX_PROJECT_NOT_IDLE', self.publish, cid='f' * 12)
        self.assertTrue(marker.exists())
        self.assertTrue(self.status(TOKEN)['active'])

    def test_status_and_result_poll_remain_local_while_project_is_held(self):
        self.acquire()
        self.refresh(updated_epoch=0)  # local diagnostics must still be usable
        self.assertTrue(self.status()['active'])
        ns = fixtures.server_namespace(self.base)
        transport = ns['VwxFileTransport']()
        result_path = self.ipc / 'results' / (CID + '.json')
        result_path.write_text(json.dumps({'status': 'ok', 'object_id': 'fixture'}), encoding='utf-8')
        result = transport.send_command('poll', {'cid': CID})
        self.assertEqual(result['status'], 'done')
        self.assertEqual(result['result']['object_id'], 'fixture')
        self.assertEqual(list((self.ipc / 'jobs').iterdir()), [])
        self.assertTrue(self.status(TOKEN)['active'])

    def test_fresh_results_do_not_release_before_outer_completion_acknowledgment(self):
        self.acquire()
        self.publish()
        (self.ipc / 'jobs' / (CID + '.json')).unlink()
        (self.ipc / 'results' / (CID + '.json')).write_text('{"status":"ok"}', encoding='utf-8')
        ns = fixtures.server_namespace(self.base)
        self.assertEqual(ns['VwxFileTransport']().send_command('poll', {'cid': CID})['status'], 'done')
        self.refresh(menu_invocation_active=True)
        self.error('VWX_PROJECT_NOT_IDLE', self.release)
        self.refresh()
        self.assertFalse(self.release()['active'])

    def test_acquire_release_and_execution_require_fresh_completion_fences(self):
        self.refresh(menu_returns=0)
        self.error('VWX_PROJECT_NOT_IDLE', self.acquire)
        self.refresh()
        self.acquire()
        for variant in ({'updated_epoch': 0}, {'pending': True}, {'menu_invocation_active': True},
                        {'posts': 2}, {'completion_stamp': 0}):
            self.refresh(**variant)
            self.error('VWX_PROJECT_NOT_IDLE', self.release)
            self.error('VWX_PROJECT_NOT_IDLE', self.publish)
        self.refresh()
        self.assertFalse(self.release()['active'])

    def test_process_restart_does_not_resume_owned_native_work(self):
        self.acquire()
        self.refresh(process_id=9999)
        self.error('VWX_PROJECT_HOST', self.publish)
        self.assertEqual(self.status()['host_process_id'], 2468)
        self.assertTrue(self.status(TOKEN)['owned'])

    def test_nested_scripts_switches_maintenance_and_sdk_escapes_reject_before_any_member(self):
        self.acquire()
        bad = [('execute_script', {'code': 'mutation'}), ('switch_document', {'name': 'Other'}),
               ('save_document_as', {'path': str(self.base / 'Other.vwx')}),
               ('marionette_recalc', {}), ('bridge_maintenance', {'action': 'quit'}),
               ('project_execute', self.envelope()),
               ('sdk_call', {'name': 'PythonExecute', 'arguments': {'script': 'mutation'}}),
               ('sdk_CallToolByIndex', {'arguments': {'toolIndex': 1}}),
               ('sdk_sequence', {'calls': [{'name': 'DoMenuTextByName', 'arguments': {}}]}),
               ('sdk_sequence', {'calls': [{'name': 'SaveActiveDocument',
                                           'arguments': {'filePath': {'$ref': 0}}}]})]
        for command, params in bad:
            with self.subTest(command=command):
                with self.assertRaises((PROJECT.ProjectError, MAINT.MaintenanceError)):
                    self.publish(params=self.envelope('_batch', {'calls': [
                        {'command': 'draw_rectangle', 'params': {}}, {'command': command, 'params': params}]}))
                self.assertEqual(list((self.ipc / 'jobs').iterdir()), [])
        self.assertFalse((self.base / MAINT.PUBLICATIONS_DIR).exists())

    def test_same_path_typed_save_is_allowed_and_save_as_is_rejected(self):
        self.acquire()
        another = self.base / 'Other.vwx'
        another.write_bytes(b'other fixture')
        self.error('VWX_PROJECT_DOCUMENT', self.publish, params=self.envelope('sdk_call',
            {'name': 'SaveActiveDocument', 'arguments': {'filePath': str(another)}}))
        safe = self.publish(params=self.envelope('sdk_call',
            {'name': 'SaveActiveDocument', 'arguments': {'filePath': str(self.drawing)}}))
        self.assertEqual(safe['command'], 'sdk_call')

    def test_two_clients_with_same_owner_cannot_publish_overlapping_jobs(self):
        self.acquire()
        start = threading.Barrier(3)
        results = []
        def work(cid):
            start.wait()
            try:
                self.publish(cid=cid)
                results.append('published')
            except MAINT.MaintenanceError as error:
                results.append(error.code)
        workers = [threading.Thread(target=work, args=(cid,)) for cid in ('1' * 12, '2' * 12)]
        for worker in workers:
            worker.start()
        start.wait()
        for worker in workers:
            worker.join(5)
        self.assertCountEqual(results, ['published', 'VWX_PROJECT_NOT_IDLE'])
        self.assertEqual(len(list((self.ipc / 'jobs').iterdir())), 1)

    def test_project_and_maintenance_cross_process_race_has_one_owner(self):
        code = """
import json, pathlib, sys, time
sys.path.insert(0, sys.argv[1])
import maintenance
base, drawing, kind = pathlib.Path(sys.argv[2]), sys.argv[3], sys.argv[4]
(base / (kind + '.ready')).write_text('ready')
while not (base / 'go').exists(): time.sleep(0.01)
try:
    if kind == 'project':
        result = maintenance.project_module().acquire(base, 'c'*64, drawing, kind, coordinator=maintenance)
    else: result = maintenance.acquire(base, 'd'*64)
    print(json.dumps({'result': 'acquired'}))
except Exception as error: print(json.dumps({'result': error.code}))
"""
        processes = [subprocess.Popen([sys.executable, '-c', code, str(ROOT / 'mcp-server'),
                     str(self.base), str(self.drawing), kind], stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True) for kind in ('project', 'maintenance')]
        try:
            deadline = time.monotonic() + 10
            while not all((self.base / (kind + '.ready')).exists() for kind in ('project', 'maintenance')):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.02)
            (self.base / 'go').write_text('go', encoding='utf-8')
            results = []
            for process in processes:
                output, errors = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, errors)
                results.append(json.loads(output)['result'])
            self.assertEqual(results.count('acquired'), 1)
            self.assertTrue(set(results) <= {'acquired', 'VWX_PROJECT_HELD', 'VWX_MAINTENANCE_HELD'})
            self.assertNotEqual((self.base / PROJECT.LEASE_FILE).exists(), (self.base / MAINT.LEASE_FILE).exists())
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()  # offline test helpers only, never Vectorworks
                    process.wait()

    def pump(self):
        with patch.object(sys, 'path', sys.path[:]):
            spec = importlib.util.spec_from_file_location('project_pump_test', ROOT / 'vwx-plugin/vwx_pump.py')
            pump = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(pump)
        pump._DIR = str(self.base)
        pump._JOBS = str(self.ipc / 'jobs')
        pump._RESULTS = str(self.ipc / 'results')
        pump._LOG = str(self.base / 'bridge.log')
        return pump

    def test_host_checks_active_path_inside_job_before_mutation(self):
        self.acquire()
        safe = self.publish()
        events = []
        vs = SimpleNamespace(GetFPathName=lambda: events.append('path') or str(self.drawing))
        commands = SimpleNamespace(vs=vs, draw_rectangle=lambda p: events.append('mutation') or {'status': 'ok'})
        pump = self.pump()
        with patch.object(pump, '_get_commands', return_value=commands), patch.object(pump.os, 'getpid', return_value=2468):
            self.assertEqual(pump._dispatch('project_execute', safe)['status'], 'ok')
        self.assertEqual(events, ['path', 'mutation'])

    def test_document_switch_after_publication_consumes_job_without_mutating_wrong_drawing(self):
        self.acquire()
        self.publish()
        other = self.base / 'Other.vwx'
        other.write_bytes(b'other fixture')
        commands = SimpleNamespace(vs=SimpleNamespace(GetFPathName=lambda: str(other)), draw_rectangle=Mock())
        pump = self.pump()
        with patch.object(pump, '_get_commands', return_value=commands), patch.object(pump.os, 'getpid', return_value=2468):
            self.assertTrue(pump._claim_and_run(CID + '.json'))
        commands.draw_rectangle.assert_not_called()
        self.assertFalse((self.ipc / 'jobs' / (CID + '.json')).exists())
        result = json.loads((self.ipc / 'results' / (CID + '.json')).read_text(encoding='utf-8'))
        self.assertEqual(result['code'], 'VWX_PROJECT_DOCUMENT')
        self.assertIs(result['dispatched'], False)

    def test_host_refuses_unowned_legacy_job_without_early_success_ack(self):
        self.acquire()
        job = self.ipc / 'jobs' / (CID + '.json')
        job.write_text(json.dumps({'type': 'marionette_recalc', 'params': {}, '_cid': CID}), encoding='utf-8')
        commands = SimpleNamespace(marionette_recalc=Mock())
        pump = self.pump()
        with patch.object(pump, '_get_commands', return_value=commands):
            self.assertTrue(pump._claim_and_run(job.name))
        commands.marionette_recalc.assert_not_called()
        result = json.loads((self.ipc / 'results' / (CID + '.json')).read_text(encoding='utf-8'))
        self.assertEqual(result['code'], 'VWX_PROJECT_HELD')
        self.assertNotEqual(result.get('status'), 'triggered')

    def test_unreadable_lease_refuses_fire_and_forget_without_success_ack(self):
        job = self.ipc / 'jobs' / (CID + '.json')
        job.write_text(json.dumps({'type': 'marionette_recalc', 'params': {}, '_cid': CID}), encoding='utf-8')
        pump = self.pump()
        with patch.object(pump._project_guard, 'read_lease', side_effect=pump._project_guard.ProjectError(
                'VWX_PROJECT_STATE', 'Lease unreadable')), patch.object(pump, '_dispatch') as dispatch:
            self.assertTrue(pump._claim_and_run(job.name))
        dispatch.assert_not_called()
        result = json.loads((self.ipc / 'results' / (CID + '.json')).read_text(encoding='utf-8'))
        self.assertEqual(result['code'], 'VWX_PROJECT_STATE')
        self.assertFalse(result['dispatched'])
        self.assertNotEqual(result.get('status'), 'triggered')
        self.assertFalse(job.exists())

    def test_old_lease_job_and_wrong_process_cannot_run(self):
        self.acquire()
        lease = json.loads((self.base / PROJECT.LEASE_FILE).read_text(encoding='utf-8'))
        safe = dict(lease_id=lease['lease_id'], expected_path=self.expected, command='draw_rectangle', params={})
        self.error('VWX_PROJECT_HOST', PROJECT.guard.host_operation, self.base, 'project_execute', safe,
                   process_id=9999, get_active_path=lambda: str(self.drawing))
        self.release()
        self.acquire()
        self.error('VWX_PROJECT_STATE', PROJECT.guard.host_operation, self.base, 'project_execute', safe,
                   process_id=2468, get_active_path=lambda: str(self.drawing))

    def test_transport_uncertain_publish_preserves_lease_fence_and_strips_token(self):
        self.acquire()
        ns = fixtures.server_namespace(self.base)
        transport = ns['VwxFileTransport']()
        real_replace = os.replace
        published = []
        def uncertain(source, target):
            if str(source).endswith('.json.tmp'):
                published.append(json.loads(Path(source).read_text(encoding='utf-8')))
                real_replace(source, target)
                Path(target).unlink()  # native claim before an uncertain publisher error
                raise OSError('uncertain atomic publication')
            return real_replace(source, target)
        with patch.object(ns['os'], 'replace', side_effect=uncertain):
            result = transport.send_command('project_execute', self.envelope())
        self.assertEqual(result['code'], 'VWX_PUBLICATION_UNCERTAIN')
        self.assertNotIn('dispatched', result)
        self.assertNotIn(TOKEN, json.dumps(published))
        self.error('VWX_PROJECT_NOT_IDLE', self.release)
        self.assertEqual(len(list((self.base / MAINT.PUBLICATIONS_DIR).iterdir())), 1)


if __name__ == '__main__':
    unittest.main()
