"""Offline restart-lease races and transport integration; never connect to VW."""
import ast
import copy
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import uuid


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('maintenance_tests', ROOT / 'mcp-server/maintenance.py')
MAINT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MAINT)
TOKEN = 'a' * 64
OTHER = 'b' * 64
CID = '123456789abc'


def server_namespace(base):
    source = ast.parse((ROOT / 'mcp-server/vwx_mcp_server.py').read_text(encoding='utf-8'))
    names = {'VwxFileTransport', 'bridge_maintenance'}
    body = [node for node in source.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    ns = dict(os=os, json=json, logging=logging, threading=threading, time=time, uuid=uuid,
              logger=logging.getLogger('maintenance-test'), bridge_lease=MAINT, _plugin_dir=lambda: str(base),
              VWX_TRANSPORT='file', VWX_SOCKET_TIMEOUT=0, VWX_ALIVE_MAX_AGE=8, VWX_ALIVE_GRACE=0,
              Context=object, vtool=lambda fn: fn, cmd=Mock(side_effect=AssertionError('No host call allowed')))
    exec(compile(ast.Module(body=body, type_ignores=[]), '<maintenance-server>', 'exec'), ns)
    return ns


class BridgeMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.ipc = self.base / 'ipc'
        (self.ipc / 'jobs').mkdir(parents=True)
        (self.ipc / 'results').mkdir()
        (self.ipc / 'pump.stamp').write_text('entry', encoding='utf-8')
        (self.ipc / 'pump.complete.stamp').write_text('completed', encoding='utf-8')
        self.refresh()

    def refresh(self, **changes):
        now = int(time.time())
        (self.ipc / 'native.alive').write_text(str(now) + ' 0', encoding='utf-8')
        self.state = dict(schema_version=1, scheduler='sdk-named-menu-broker-ack-v4', sdk_version=3200,
                          updated_epoch=now, process_id=2468, timer_active=True, paused=False,
                          queued_jobs=0, pending=False, posts=1, runner_completions_observed=1,
                          menu_invocations=1, menu_returns=1, broker_message_pending=False,
                          menu_invocation_active=False, frame_available=True, broker_window_available=True,
                          runner_stamp=MAINT._filetime(self.ipc / 'pump.stamp'),
                          completion_stamp=MAINT._filetime(self.ipc / 'pump.complete.stamp'))
        self.state.update(changes)
        (self.ipc / 'native.scheduler.json').write_text(json.dumps(self.state), encoding='utf-8')

    def error(self, code, call, *args, **kwargs):
        with self.assertRaises(MAINT.MaintenanceError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertIs(caught.exception.response()['dispatched'], False)

    def publish(self, command='draw_rectangle', params=None, cid=CID):
        with MAINT.publication_guard(self.base, command, params or {}, cid):
            (self.ipc / 'jobs' / (cid + '.json')).write_text('{}', encoding='utf-8')

    def test_acquire_persists_hashed_owner_identity_without_exposing_token_and_never_replays(self):
        acquired = MAINT.acquire(self.base, TOKEN)
        self.assertEqual(acquired['host_process_id'], 2468)
        self.assertIs(acquired['owned'], True)
        stored = json.loads((self.base / MAINT.LEASE_FILE).read_text(encoding='utf-8'))
        self.assertEqual(stored['token_sha256'], hashlib.sha256(TOKEN.encode('ascii')).hexdigest())
        self.assertEqual(stored['owner_server_pid'], os.getpid())
        self.assertNotIn(TOKEN, repr(acquired))
        self.assertNotIn('token_sha256', acquired)
        self.error('VWX_MAINTENANCE_HELD', MAINT.acquire, self.base, TOKEN)
        self.error('VWX_MAINTENANCE_HELD', MAINT.acquire, self.base, OTHER)
        self.assertFalse(MAINT.lease_status(self.base)['owned'])
        self.assertFalse(MAINT.lease_status(self.base, OTHER)['owned'])
        self.assertTrue(MAINT.lease_status(self.base, TOKEN)['owned'])

    def test_wrong_token_release_never_deletes_and_no_expiry_or_dead_pid_stealing(self):
        MAINT.acquire(self.base, TOKEN)
        path = self.base / MAINT.LEASE_FILE
        lease = json.loads(path.read_text(encoding='utf-8'))
        lease.update(created_epoch=0, owner_server_pid=2147483647)
        path.write_text(json.dumps(lease), encoding='utf-8')
        before = path.read_bytes()
        self.error('VWX_MAINTENANCE_TOKEN', MAINT.release, self.base, OTHER)
        self.assertEqual(path.read_bytes(), before)
        self.error('VWX_MAINTENANCE_HELD', MAINT.acquire, self.base, OTHER)
        self.assertEqual(MAINT.release(self.base, TOKEN)['active'], False)
        self.assertFalse(path.exists())
        self.assertTrue((self.base / MAINT.GATE_FILE).exists(), 'The OS lock inode must persist')
        self.error('VWX_MAINTENANCE_TOKEN', MAINT.release, self.base, TOKEN)

    def test_missing_or_malformed_tokens_do_not_change_lease_or_publish(self):
        for token in ('', 'a'*63, 'A'*64, 'g'*64, 'a'*65, None, True, ['a'*64]):
            with self.subTest(token=token):
                self.error('VWX_MAINTENANCE_TOKEN', MAINT.acquire, self.base, token)
                self.assertFalse((self.base / MAINT.LEASE_FILE).exists())

    def test_malformed_or_partial_lease_fails_closed_and_remains_untouched(self):
        MAINT.acquire(self.base, TOKEN)
        path = self.base / MAINT.LEASE_FILE
        original = json.loads(path.read_text(encoding='utf-8'))
        bad = [None, [], {}, {'token_sha256': 'a'*64}, dict(original, schema_version=True),
               dict(original, token_sha256='bad'), dict(original, host_process_id=True),
               dict(original, owner_server_pid=0), dict(original, created_epoch=float('nan')),
               dict(original, unexpected=1)]
        for value in bad:
            with self.subTest(value=value):
                path.write_text(json.dumps(value), encoding='utf-8')
                before = path.read_bytes()
                for fn, args in ((MAINT.acquire, (TOKEN,)), (MAINT.release, (TOKEN,)), (MAINT.lease_status, ())):
                    self.error('VWX_MAINTENANCE_STATE', fn, self.base, *args)
                self.error('VWX_MAINTENANCE_STATE', self.publish)
                self.assertEqual(path.read_bytes(), before)
        path.write_text('{', encoding='utf-8')
        self.error('VWX_MAINTENANCE_STATE', MAINT.lease_status, self.base)
        self.assertEqual(list((self.ipc / 'jobs').iterdir()), [])

    def test_lease_survives_ipc_recreation_and_does_not_change_original_host_identity(self):
        MAINT.acquire(self.base, TOKEN)
        for file in self.ipc.iterdir():
            if file.is_file():
                file.unlink()
        self.assertTrue(MAINT.lease_status(self.base, TOKEN)['owned'])
        self.refresh(process_id=9999, runner_stamp=0, completion_stamp=0, posts=0,
                     runner_completions_observed=0, menu_invocations=0, menu_returns=0)
        self.assertEqual(MAINT.lease_status(self.base, TOKEN)['host_process_id'], 2468)
        # New host status is allowed; native wrappers enforce save/quit PID.
        self.publish('bridge_maintenance', {'action': 'status', 'token': TOKEN}, cid='f'*12)

    def test_stale_future_paused_or_malformed_heartbeat_prevents_acquisition(self):
        for text in ('0 0', str(int(time.time())+60)+' 0', str(int(time.time()))+' 1', 'NaN 0', '0', '', '1 0 extra'):
            with self.subTest(text=text):
                (self.ipc / 'native.alive').write_text(text, encoding='utf-8')
                self.error('VWX_MAINTENANCE_NOT_IDLE', MAINT.acquire, self.base, TOKEN)
                self.assertFalse((self.base / MAINT.LEASE_FILE).exists())

    def test_incomplete_busy_or_unacknowledged_scheduler_prevents_acquisition(self):
        variants = [dict(updated_epoch=0), dict(updated_epoch=True), dict(process_id=True),
                    dict(paused=True), dict(timer_active=False), dict(pending=True), dict(queued_jobs=1),
                    dict(broker_message_pending=True), dict(menu_invocation_active=True),
                    dict(frame_available=False), dict(broker_window_available=False), dict(schema_version=True),
                    dict(sdk_version=3100), dict(scheduler='legacy'), dict(menu_returns=0),
                    dict(runner_completions_observed=0), dict(posts=2), dict(queued_jobs=False),
                    dict(menu_invocations=2), dict(runner_stamp=0), dict(completion_stamp=0)]
        for change in variants:
            with self.subTest(change=change):
                self.refresh(**change)
                self.error('VWX_MAINTENANCE_NOT_IDLE', MAINT.acquire, self.base, TOKEN)
        for key in ('pending', 'menu_invocation_active', 'completion_stamp', 'process_id'):
            self.refresh()
            state = copy.deepcopy(self.state)
            del state[key]
            (self.ipc / 'native.scheduler.json').write_text(json.dumps(state), encoding='utf-8')
            self.error('VWX_MAINTENANCE_NOT_IDLE', MAINT.acquire, self.base, TOKEN)

    def test_direct_outer_stamp_rejects_stale_idle_snapshot(self):
        entry = self.ipc / 'pump.stamp'
        before = entry.stat().st_mtime_ns
        os.utime(entry, ns=(before+1_000_000_000, before+1_000_000_000))
        self.error('VWX_MAINTENANCE_NOT_IDLE', MAINT.acquire, self.base, TOKEN)
        self.refresh()
        self.error('VWX_MAINTENANCE_NOT_IDLE', MAINT.acquire, self.base, TOKEN)

    def test_pending_json_working_tmp_and_unrecognized_queue_files_all_block(self):
        for name in ('job.json', 'job.json.working', 'job.json.tmp', 'unknown'):
            with self.subTest(name=name):
                path = self.ipc / 'jobs' / name
                path.write_text('{}', encoding='utf-8')
                self.error('VWX_MAINTENANCE_NOT_IDLE', MAINT.acquire, self.base, TOKEN)
                self.assertTrue(path.exists())
                path.unlink()

    def test_consumed_or_uncertain_publication_blocks_even_with_empty_queue_and_idle_snapshot(self):
        self.publish()
        (self.ipc / 'jobs' / (CID+'.json')).unlink()
        marker = self.base / MAINT.PUBLICATIONS_DIR / (CID+'.json')
        self.error('VWX_MAINTENANCE_NOT_IDLE', MAINT.acquire, self.base, TOKEN)
        self.assertTrue(marker.exists())
        # Only an authoritative result/unclaimed discard authorizes this call.
        MAINT.finish_publication(self.base, CID)
        self.assertTrue(MAINT.acquire(self.base, TOKEN)['owned'])

    def test_all_native_commands_block_during_lease_except_exact_owner_maintenance(self):
        MAINT.acquire(self.base, TOKEN)
        for command, params in [('ping', {}), ('sdk_call', {'name': 'GetVersionEx'}),
                                ('draw_rectangle', {'token': TOKEN}), ('execute_script', {'token': TOKEN}),
                                ('_batch', {'calls': []})]:
            with self.subTest(command=command):
                self.error('VWX_MAINTENANCE_HELD', self.publish, command, params)
        for action in ('status', 'save', 'quit'):
            self.error('VWX_MAINTENANCE_TOKEN', self.publish, 'bridge_maintenance', {'action': action, 'token': OTHER})
            with MAINT.publication_guard(self.base, 'bridge_maintenance', {'action': action, 'token': TOKEN,
                                          'expected_path': 'C:/disposable.vwx'}, CID):
                pass
        self.assertFalse((self.base / MAINT.PUBLICATIONS_DIR).exists())
        self.assertEqual(list((self.ipc / 'jobs').iterdir()), [])

    def test_maintenance_requires_lease_and_only_three_native_actions(self):
        self.error('VWX_MAINTENANCE_TOKEN', self.publish, 'bridge_maintenance', {'action': 'quit', 'token': TOKEN})
        MAINT.acquire(self.base, TOKEN)
        for action in ('acquire', 'release', 'lease_status', '', 'unknown'):
            self.error('VWX_MAINTENANCE_CONTEXT', self.publish, 'bridge_maintenance', {'action': action, 'token': TOKEN})
        self.error('VWX_MAINTENANCE_CONTEXT', self.publish, 'bridge_maintenance', {'action': 'quit', 'token': TOKEN, 'force': True})

    def test_nested_maintenance_rejected_before_publication_with_or_without_lease(self):
        for acquired in (False, True):
            if acquired:
                MAINT.acquire(self.base, TOKEN)
            for action in ('status', 'save', 'quit', 'release'):
                call = {'command': 'bridge_maintenance', 'params': {'action': action, 'token': TOKEN}}
                for nested in (call, {'command': '_batch', 'params': {'calls': [call]}}):
                    self.error('VWX_MAINTENANCE_CONTEXT', self.publish, '_batch', {'calls': [
                        {'command': 'draw_rectangle', 'params': {}}, nested]})
        self.assertEqual(list((self.ipc / 'jobs').iterdir()), [])
        self.assertFalse((self.base / MAINT.PUBLICATIONS_DIR).exists())

    def test_ordinary_publication_and_acquisition_are_serialized_with_uncertain_record(self):
        entered, release = threading.Event(), threading.Event()
        results = []
        def publish():
            with MAINT.publication_guard(self.base, 'ping', {}, CID):
                entered.set()
                release.wait(2)
        worker = threading.Thread(target=publish)
        worker.start()
        self.assertTrue(entered.wait(2))
        def acquire():
            try:
                MAINT.acquire(self.base, TOKEN)
            except MAINT.MaintenanceError as error:
                results.append(error.code)
        competitor = threading.Thread(target=acquire)
        competitor.start()
        release.set()
        worker.join(3)
        competitor.join(3)
        self.assertEqual(results, ['VWX_MAINTENANCE_NOT_IDLE'])

    def test_acquisition_wins_gate_and_competing_publisher_cannot_publish(self):
        entered, release = threading.Event(), threading.Event()
        original = MAINT._readiness
        results = []
        def readiness(*args, **kwargs):
            entered.set()
            release.wait(2)
            return original(*args, **kwargs)
        with patch.object(MAINT, '_readiness', side_effect=readiness):
            worker = threading.Thread(target=lambda: MAINT.acquire(self.base, TOKEN))
            worker.start()
            self.assertTrue(entered.wait(2))
            def publish():
                try:
                    self.publish()
                except MAINT.MaintenanceError as error:
                    results.append(error.code)
            competitor = threading.Thread(target=publish)
            competitor.start()
            release.set()
            worker.join(3)
            competitor.join(3)
        self.assertEqual(results, ['VWX_MAINTENANCE_HELD'])
        self.assertFalse((self.base / MAINT.PUBLICATIONS_DIR).exists())

    def test_gate_excludes_another_process_without_deleting_lock_file(self):
        code = "import sys;sys.path.insert(0,sys.argv[1]);import maintenance\ntry:\n with maintenance.publish_gate(sys.argv[2],timeout=.15): print('unexpected')\nexcept maintenance.MaintenanceError as e: print(e.code)"
        with MAINT.publish_gate(self.base):
            child = subprocess.run([sys.executable, '-c', code, str(ROOT/'mcp-server'), str(self.base)],
                                   capture_output=True, text=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.strip(), 'VWX_MAINTENANCE_BUSY')
        self.assertTrue((self.base / MAINT.GATE_FILE).exists())

    def test_owner_lease_blocks_independent_server_process(self):
        MAINT.acquire(self.base, TOKEN)
        code = "import sys;sys.path.insert(0,sys.argv[1]);import maintenance\ntry:\n with maintenance.publication_guard(sys.argv[2],'ping',{},'123456789abc'): print('unexpected')\nexcept maintenance.MaintenanceError as e: print(e.code)"
        child = subprocess.run([sys.executable, '-c', code, str(ROOT/'mcp-server'), str(self.base)],
                               capture_output=True, text=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.strip(), 'VWX_MAINTENANCE_HELD')

    def test_transport_unclaimed_discard_clears_marker_but_claimed_timeout_keeps_it(self):
        ns = server_namespace(self.base)
        transport = ns['VwxFileTransport']()
        result = transport.send_command('ping')
        self.assertEqual(result['code'], 'VW_JOB_UNCLAIMED')
        self.assertEqual(list((self.base / MAINT.PUBLICATIONS_DIR).iterdir()), [])
        def claim(path):
            Path(path).unlink()
            return False
        transport._discard = claim
        result = transport.send_command('draw_rectangle')
        self.assertEqual(result['code'], 'VW_DISPATCH_STUCK')
        self.assertEqual(len(list((self.base / MAINT.PUBLICATIONS_DIR).iterdir())), 1)
        self.error('VWX_MAINTENANCE_NOT_IDLE', MAINT.acquire, self.base, TOKEN)

    def test_transport_actual_result_clears_marker_and_preserves_result(self):
        ns = server_namespace(self.base)
        ns['VWX_SOCKET_TIMEOUT'] = 1
        transport = ns['VwxFileTransport']()
        original = transport._read_result
        def completed(cid):
            for job in (self.ipc / 'jobs').glob('*.json'):
                job.unlink()
            (self.ipc / 'results' / (cid+'.json')).write_text('{"status":"ok","value":42}', encoding='utf-8')
            return original(cid)
        transport._read_result = completed
        self.assertEqual(transport.send_command('ping'), {'status': 'ok', 'value': 42})
        self.assertEqual(list((self.base / MAINT.PUBLICATIONS_DIR).iterdir()), [])

    def test_transport_publication_failure_proof_clears_marker_but_uncertainty_does_not(self):
        ns = server_namespace(self.base)
        transport = ns['VwxFileTransport']()
        with patch.object(os, 'replace', side_effect=OSError('rename denied')):
            failed = transport.send_command('ping')
        self.assertEqual(failed['code'], 'VWX_PUBLICATION_FAILED')
        self.assertIs(failed['dispatched'], False)
        self.assertEqual(list((self.base / MAINT.PUBLICATIONS_DIR).iterdir()), [])
        replace = os.replace
        def uncertain(source, destination):
            replace(source, destination)
            Path(destination).unlink()  # simulate consumption, not a host call
            raise OSError('acknowledgment lost after publication')
        with patch.object(os, 'replace', side_effect=uncertain):
            result = transport.send_command('draw_rectangle')
        self.assertEqual(result['code'], 'VWX_PUBLICATION_UNCERTAIN')
        self.assertNotIn('dispatched', result)
        self.assertEqual(len(list((self.base / MAINT.PUBLICATIONS_DIR).iterdir())), 1)

    def test_transport_checks_lease_before_writing_any_job_and_still_allows_local_poll(self):
        ns = server_namespace(self.base)
        transport = ns['VwxFileTransport']()
        MAINT.acquire(self.base, TOKEN)
        result = transport.send_command('ping')
        self.assertEqual(result['code'], 'VWX_MAINTENANCE_HELD')
        self.assertIs(result['dispatched'], False)
        self.assertEqual(list((self.ipc / 'jobs').iterdir()), [])
        self.assertEqual(transport.send_command('poll', {'cid': CID})['status'], 'pending')

    def test_poll_traversal_and_malformed_ids_never_access_any_result_path(self):
        ns = server_namespace(self.base)
        transport = ns['VwxFileTransport']()
        MAINT.acquire(self.base, TOKEN)
        lease_path = self.base / MAINT.LEASE_FILE
        lease_before = lease_path.read_bytes()
        unrelated = self.base / 'unrelated.json'
        unrelated.write_text('{"keep":true}', encoding='utf-8')
        invalid = ['../../bridge.maintenance', '..\\..\\bridge.maintenance', '../unrelated',
                   str(self.base / 'bridge.maintenance'), 'C:\\bridge.maintenance', '/tmp/result',
                   'C:result', '123456789abc:stream', '123456789ab\x00', '', 'abc', 'a'*11, 'a'*13,
                   'ABCDEF123456', True, False, None, 123456789012, 123456789012.0, [], {}]
        for cid in invalid:
            with self.subTest(cid=cid), patch.object(os.path, 'exists', side_effect=AssertionError('Invalid CID touched filesystem')):
                result = transport.send_command('poll', {'cid': cid})
                self.assertEqual(result['code'], 'VWX_INVALID_CID')
                self.assertIs(result['dispatched'], False)
                self.assertNotIn('result', result)
                with self.assertRaises(MAINT.MaintenanceError):
                    transport._read_result(cid)
        for params in (None, {}, [], 'bad', True):
            with self.subTest(params=params):
                self.assertEqual(transport.send_command('poll', params)['code'], 'VWX_INVALID_CID')
        self.assertEqual(lease_path.read_bytes(), lease_before)
        self.assertEqual(unrelated.read_text(encoding='utf-8'), '{"keep":true}')

    def test_valid_poll_reads_exact_result_clears_marker_and_preserves_unrelated_files(self):
        ns = server_namespace(self.base)
        transport = ns['VwxFileTransport']()
        with MAINT.publication_guard(self.base, 'ping', {}, CID):
            pass
        marker = self.base / MAINT.PUBLICATIONS_DIR / (CID+'.json')
        result_path = self.ipc / 'results' / (CID+'.json')
        result_path.write_text('{"status":"ok","value":42}', encoding='utf-8')
        other = self.ipc / 'results' / ('f'*12+'.json')
        other.write_text('{"keep":true}', encoding='utf-8')
        result = transport.send_command('poll', {'cid': CID})
        self.assertEqual(result, {'status': 'done', 'cid': CID, 'result': {'status': 'ok', 'value': 42}})
        self.assertFalse(result_path.exists())
        self.assertFalse(marker.exists())
        self.assertEqual(other.read_text(encoding='utf-8'), '{"keep":true}')
        self.assertEqual(transport.send_command('poll', {'cid': CID})['status'], 'pending')

    def test_typed_local_tool_actions_never_call_host_and_native_actions_use_exact_envelope(self):
        ns = server_namespace(self.base)
        tool = ns['bridge_maintenance']
        self.assertTrue(json.loads(tool(None, 'acquire', TOKEN))['owned'])
        self.assertTrue(json.loads(tool(None, 'lease_status', TOKEN))['active'])
        self.assertFalse(json.loads(tool(None, 'release', TOKEN))['active'])
        ns['cmd'].assert_not_called()
        ns['cmd'] = Mock(return_value='{"status":"ok"}')
        for action in ('status', 'save', 'quit'):
            self.assertEqual(json.loads(tool(None, action, TOKEN, 'C:/reviewed.vwx'))['status'], 'ok')
            ns['cmd'].assert_called_with('bridge_maintenance', {'action': action, 'token': TOKEN, 'expected_path': 'C:/reviewed.vwx'})
        ns['cmd'].reset_mock()
        self.assertEqual(json.loads(tool(None, 'unknown'))['code'], 'VWX_MAINTENANCE_CONTEXT')
        ns['cmd'].assert_not_called()

    def test_background_policy_rejects_nested_quit_before_first_batch_step(self):
        spec = importlib.util.spec_from_file_location('maintenance_background', ROOT / 'mcp-server/background_policy.py')
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        request = {'calls': [{'command': 'draw_rectangle', 'params': {}},
                            {'command': 'bridge_maintenance', 'params': {'action': 'quit', 'token': TOKEN}}]}
        result = policy.check('_batch', request)
        self.assertEqual(result['code'], 'VWX_MAINTENANCE_CONTEXT')
        self.assertEqual(result['blocked_step'], 1)
        self.assertIsNone(policy.check('bridge_maintenance', {'action': 'status', 'token': TOKEN}))


if __name__ == '__main__':
    unittest.main()
