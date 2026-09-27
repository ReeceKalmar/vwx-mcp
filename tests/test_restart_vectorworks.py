"""Independent phase/fault model of maintenance; never launches Vectorworks."""
import asyncio
import importlib.util
from pathlib import Path
import unittest
import tempfile
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('maintenance_controller', ROOT / 'tools/restart_vectorworks.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
DOC = r'C:\Test\Garden.vwx'


def status(pid=50):
    return {'status': 'ok', 'helper_revision': 1, 'process_id': pid, 'count': 1,
            'open_documents': [{'path': DOC, 'file_ref': 2, 'active': True, 'in_memory_only': False}]}


class RestartTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.actions, self.events = [], []
        self.host = Mock()
        self.process = self.host.open_process.return_value
        self.process.exited.return_value = True
        self.host.all_exited.return_value = True
        self.host.ready.return_value = True
        self.host.launch.return_value = 51
        self.host.deploy.return_value = 'backup-and-hashes-confirmed'
        self.replies = {}
        self.status_calls = 0

    async def send(self, params):
        self.assertEqual(params['token'], 'b' * 64)
        self.assertEqual(params['expected_path'], DOC)
        action = params['action']
        self.actions.append(action)
        if action in self.replies:
            result = self.replies[action]
            if isinstance(result, Exception):
                raise result
            return result
        if action == 'acquire':
            return {'status': 'ok', 'host_process_id': 50, 'action': 'acquire', 'active': True, 'owned': True}
        if action == 'release':
            return {'status': 'ok', 'action': 'release', 'active': False, 'owned': False}
        if action == 'status':
            self.status_calls += 1
            return status(51 if self.status_calls == 3 else 50)
        if action == 'save':
            return {'status': 'ok', 'action': 'save', 'process_id': 50, 'dispatched': True,
                    'native_status': 1, 'path': DOC}
        return {'status': 'ok', 'dispatched': True}

    async def run_flow(self):
        async def no_sleep(seconds):
            pass
        return await module.restart(self.send, self.host, document=DOC, token='b' * 64,
                                    journal=lambda event, **data: self.events.append((event, data)),
                                    timeout=1, sleep=no_sleep)

    def no_deploy(self):
        self.host.deploy.assert_not_called()
        self.host.launch.assert_not_called()
        self.assertNotIn('release', self.actions)

    async def test_success_order_and_held_process_handle(self):
        result = await self.run_flow()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(self.actions, ['acquire', 'status', 'save', 'status', 'quit', 'status', 'release'])
        self.host.open_process.assert_called_once_with(50)
        self.process.close.assert_called_once()
        self.host.deploy.assert_called_once()
        self.host.launch.assert_called_once_with(DOC)
        self.assertEqual(self.host.verify_installed.call_count, 2)
        self.assertFalse(result['lease_retained'])
        self.assertEqual([data['action'] for event, data in self.events if event == 'intent'].count('quit'), 1)

    async def test_failed_acquisition_cannot_send_any_native_request(self):
        self.replies['acquire'] = {'status': 'error', 'error': 'busy'}
        result = await self.run_flow()
        self.assertEqual(self.actions, ['acquire'])
        self.assertEqual(result['phase'], 'acquire')
        self.no_deploy()

    async def test_bad_initial_inventory_stops_before_save(self):
        self.replies['status'] = status()
        self.replies['status']['open_documents'].append(dict(self.replies['status']['open_documents'][0]))
        result = await self.run_flow()
        self.assertEqual(result['phase'], 'inventory')
        self.assertNotIn('save', self.actions)
        self.no_deploy()

    async def test_process_path_verification_failure_prevents_save(self):
        self.host.open_process.side_effect = ValueError('different exe')
        result = await self.run_flow()
        self.assertEqual(result['phase'], 'inventory')
        self.assertNotIn('save', self.actions)
        self.no_deploy()

    async def test_save_failure_and_lost_save_response_never_retry_or_quit(self):
        for response in ({'status': 'error', 'error': 'save failed'}, TimeoutError('lost save reply')):
            with self.subTest(response=response):
                self.setUp()
                self.replies['save'] = response
                result = await self.run_flow()
                self.assertEqual(result['phase'], 'save')
                self.assertEqual(self.actions.count('save'), 1)
                self.assertNotIn('quit', self.actions)
                self.assertTrue(result['lease_retained'])
                self.no_deploy()

    async def test_save_success_label_without_exact_native_proof_is_rejected(self):
        for field, value in [('dispatched', 1), ('native_status', True), ('process_id', 51),
                             ('process_id', 50.0), ('path', 'wrong.vwx'), ('error', '')]:
            with self.subTest(field=field):
                self.setUp()
                self.replies['save'] = {'status': 'ok', 'action': 'save', 'process_id': 50,
                                        'dispatched': True, 'native_status': 1, 'path': DOC, field: value}
                result = await self.run_flow()
                self.assertEqual(result['status'], 'stopped')
                self.assertNotIn('quit', self.actions)
                self.no_deploy()

    async def test_drawing_changes_after_save_prevents_quit(self):
        original = self.send
        async def changed(params):
            result = await original(params)
            if params['action'] == 'status' and self.status_calls == 2:
                result['open_documents'][0]['path'] = r'C:\Test\Other.vwx'
            return result
        self.send = changed
        result = await self.run_flow()
        self.assertEqual(result['status'], 'stopped')
        self.assertNotIn('quit', self.actions)
        self.no_deploy()

    async def test_quit_without_response_can_proceed_only_after_actual_exit(self):
        self.replies['quit'] = TimeoutError('process exited before response')
        result = await self.run_flow()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(self.actions.count('quit'), 1)

    async def test_quit_predispatch_rejection_prevents_deployment_even_if_host_exits(self):
        self.replies['quit'] = {'status': 'error', 'dispatched': False, 'error': 'unsaved extra document'}
        result = await self.run_flow()
        self.assertEqual(result['phase'], 'quit')
        self.no_deploy()

    async def test_quit_response_does_not_substitute_for_process_exit(self):
        self.process.exited.return_value = False
        result = await self.run_flow()
        self.assertEqual(result['phase'], 'exit')
        self.assertEqual(self.actions.count('quit'), 1)
        self.no_deploy()
        self.process.close.assert_called_once()

    async def test_child_processes_block_deployment(self):
        self.host.all_exited.return_value = False
        result = await self.run_flow()
        self.assertEqual(result['phase'], 'exit')
        self.no_deploy()

    async def test_source_change_prevents_deployment(self):
        self.host.verify_sources.side_effect = ValueError('changed')
        result = await self.run_flow()
        self.assertEqual(result['phase'], 'deploy')
        self.no_deploy()

    async def test_deployment_failure_does_not_launch(self):
        self.host.deploy.side_effect = OSError('copy failed')
        result = await self.run_flow()
        self.assertEqual(result['phase'], 'deploy')
        self.host.deploy.assert_called_once()
        self.host.launch.assert_not_called()

    async def test_hash_mismatch_does_not_launch(self):
        self.host.verify_installed.side_effect = ValueError('mismatch')
        result = await self.run_flow()
        self.assertEqual(result['phase'], 'deploy')
        self.host.launch.assert_not_called()

    async def test_missing_heartbeat_does_not_claim_success_or_release(self):
        self.host.ready.return_value = False
        result = await self.run_flow()
        self.assertEqual(result['phase'], 'startup')
        self.assertTrue(result['lease_retained'])
        self.assertNotIn('release', self.actions)
        self.host.launch.assert_called_once()

    async def test_other_process_heartbeat_cannot_complete(self):
        self.host.launch.return_value = 52
        result = await self.run_flow()
        self.assertEqual(result['phase'], 'startup')
        self.assertNotIn('release', self.actions)

    async def test_failed_release_does_not_claim_finished(self):
        self.replies['release'] = {'status': 'error', 'error': 'lease differs'}
        result = await self.run_flow()
        self.assertEqual(result['phase'], 'release')
        self.assertEqual(result['status'], 'stopped')

    async def test_acquire_and_release_need_ownership_proof(self):
        for action in ('acquire', 'release'):
            with self.subTest(action=action):
                self.setUp()
                self.replies[action] = {'status': 'ok', 'host_process_id': 50}
                result = await self.run_flow()
                self.assertEqual(result['status'], 'stopped')
                self.assertEqual(result['phase'], action)

    async def test_lost_acquire_response_reports_unknown_lease(self):
        self.replies['acquire'] = TimeoutError('response lost after lease write')
        result = await self.run_flow()
        self.assertEqual(result['lease_retained'], 'unknown')
        self.assertEqual(self.actions, ['acquire'])
        self.no_deploy()

    async def test_cancellation_does_not_replay_or_release(self):
        original = self.send
        async def cancel(params):
            if params['action'] == 'save':
                raise asyncio.CancelledError()
            return await original(params)
        self.send = cancel
        with self.assertRaises(asyncio.CancelledError):
            await self.run_flow()
        self.assertEqual(self.events[-1][0], 'cancelled')
        self.process.close.assert_called_once()
        self.no_deploy()


class InventoryTests(unittest.TestCase):
    def test_inventory_rejects_malformed_types_and_wrong_identity(self):
        mutations = [('helper_revision', True), ('process_id', True), ('count', True),
                     ('count', 2), ('status', 'error'), ('error', ''), ('open_documents', {}), ('process_id', 0)]
        for field, value in mutations:
            data = status()
            data[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                module.inventory(data, DOC, 50)
        for field, value in [('active', 1), ('in_memory_only', 0), ('file_ref', True), ('path', None)]:
            data = status()
            data['open_documents'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                module.inventory(data, DOC)

    def test_windows_path_case_is_normalized(self):
        self.assertEqual(module.inventory(status(), 'c:/TEST/garden.vwx', 50), 50)


class DeploymentTests(unittest.TestCase):
    def test_file_deployment_preserves_queue_old_binary_and_maintenance_lease(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plugin = root / '2027/Plug-ins/VWX-MCP'
            (plugin / 'ipc/jobs').mkdir(parents=True)
            (plugin / 'ipc/jobs/old.working').write_text('uncertain job', encoding='utf-8')
            (plugin / 'bridge.maintenance.json').write_text('lease remains', encoding='utf-8')
            source = root / 'build/VwxBridge.vlb'
            source.parent.mkdir()
            source.write_bytes(b'new built binary')
            installed = plugin.parent / source.name
            installed.write_bytes(b'prior binary')
            host = object.__new__(module.WindowsHost)
            host.plugin_dir = plugin
            host.pairs = [(source, installed)]
            host.expected = {source.name: host.hash(source)}
            host.all_exited = Mock(return_value=True)
            host.powershell = Mock(side_effect=AssertionError('Deployment must not invoke script execution'))
            result = host.deploy()
            backup = Path(result['backup'])
            self.assertEqual((backup/source.name).read_bytes(), b'prior binary')
            self.assertEqual((backup/'ipc/jobs/old.working').read_text(), 'uncertain job')
            self.assertEqual(installed.read_bytes(), b'new built binary')
            self.assertEqual((plugin/'bridge.maintenance.json').read_text(), 'lease remains')
            self.assertEqual(list((plugin/'ipc/jobs').iterdir()), [])
            self.assertTrue((plugin/'ipc/results').is_dir())
            host.powershell.assert_not_called()

    def test_live_process_or_changed_source_prevents_archive_and_copy(self):
        for running in (True, False):
            with self.subTest(running=running), tempfile.TemporaryDirectory() as temporary:
                host=object.__new__(module.WindowsHost)
                host.plugin_dir=Path(temporary)/'2027/Plug-ins/VWX-MCP'
                host.plugin_dir.mkdir(parents=True)
                host.all_exited=Mock(return_value=not running)
                host.verify_sources=Mock(side_effect=ValueError('source changed'))
                with self.assertRaises(ValueError): host.deploy()
                self.assertFalse((host.plugin_dir.parent.parent/'MCP-Backups').exists())



if __name__ == '__main__':
    unittest.main()
