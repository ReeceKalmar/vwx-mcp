"""Offline runner regressions; no Vectorworks process or installed files used."""
import importlib.util
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
MENU = ROOT / 'vwx-plugin/BridgeStart_MenuCommand.py'


class MenuRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / 'Nemetschek/Vectorworks/2027/Plug-ins'
        self.env = {'APPDATA': self.temp.name, 'VWX_VW_VERSION': '2027'}
        self.vs = ModuleType('vs')
        self.vs.GetVersion = lambda: (32, 0, 0, 2)
        self.path_patch = patch.object(sys, 'path', sys.path[:])
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

    def install(self, name='VWX-MCP'):
        directory = self.base / name
        directory.mkdir(parents=True, exist_ok=True)
        for filename in ('vwx_pump.py', 'commands.py'):
            (directory / filename).write_text('# fixture\n', encoding='utf-8')
        return directory

    def pump(self, directory):
        module = ModuleType('vwx_pump')
        module.__file__ = str(directory / 'vwx_pump.py')
        module._vwx_loaded_mtime = os.path.getmtime(module.__file__)
        module.pump_all = Mock()
        return module

    def run_menu(self, pump):
        with patch.dict(os.environ, self.env, clear=True), \
                patch.dict(sys.modules, {'vs': self.vs, 'vwx_pump': pump}):
            return runpy.run_path(str(MENU))

    def test_prefers_canonical_installation_when_both_exist(self):
        canonical = self.install()
        self.install('VW-MCP')
        pump = self.pump(canonical)
        self.assertEqual(self.run_menu(pump)['_dir'], str(canonical))
        pump.pump_all.assert_called_once_with()

    def test_skips_incomplete_canonical_installation(self):
        canonical = self.install()
        (canonical / 'commands.py').unlink()
        legacy = self.install('VW-MCP')
        self.assertEqual(self.run_menu(self.pump(legacy))['_dir'], str(legacy))

    def test_honors_explicit_complete_directory(self):
        self.install()
        custom = self.install('custom')
        self.env['VWX_PLUGIN_DIR'] = str(custom)
        self.assertEqual(self.run_menu(self.pump(custom))['_dir'], str(custom))

    def test_invalid_explicit_directory_never_falls_back(self):
        canonical = self.install()
        self.env['VWX_PLUGIN_DIR'] = str(self.base / 'missing')
        pump = self.pump(canonical)
        with self.assertRaisesRegex(RuntimeError, 'complete bridge installation'):
            self.run_menu(pump)
        pump.pump_all.assert_not_called()

    def test_rejects_wrong_host_before_dispatch(self):
        pump = self.pump(self.install())
        self.vs.GetVersion = lambda: (31, 0, 0, 2)
        with self.assertRaisesRegex(RuntimeError, 'host is 2026'):
            self.run_menu(pump)
        pump.pump_all.assert_not_called()

    def test_rejects_pump_cached_from_another_installation(self):
        self.install()
        pump = self.pump(self.install('VW-MCP'))
        with self.assertRaisesRegex(RuntimeError, 'different bridge is already loaded'):
            self.run_menu(pump)
        pump.pump_all.assert_not_called()

    def test_nested_menu_does_not_reload_and_reset_reentry_guard(self):
        pump = self.pump(self.install())
        pump._pumping = True
        pump._vwx_loaded_mtime = -1
        with patch('importlib.reload') as reload_module:
            self.run_menu(pump)
        reload_module.assert_not_called()
        self.assertTrue(pump._pumping)


class PumpLoadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path_patch = patch.object(sys, 'path', sys.path[:])
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        spec = importlib.util.spec_from_file_location('pump_fixture', ROOT / 'vwx-plugin/vwx_pump.py')
        self.pump = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.pump)
        self.pump._DIR = self.temp.name
        for name, relative in {'_IPC': 'ipc', '_JOBS': 'ipc/jobs',
                               '_RESULTS': 'ipc/results', '_STAMP': 'ipc/pump.stamp',
                               '_LOG': 'bridge.log'}.items():
            setattr(self.pump, name, str(Path(self.temp.name) / relative))
        self.pump._housekeep()

    def test_commands_cached_from_another_bridge_cannot_dispatch(self):
        commands = ModuleType('commands')
        commands.__file__ = str(Path(self.temp.name) / 'wrong/commands.py')
        commands.draw_rectangle = Mock()
        with patch.dict(sys.modules, {'commands': commands}):
            result = self.pump._dispatch('draw_rectangle', {})
        self.assertIn('different commands module', result['error'])
        commands.draw_rectangle.assert_not_called()

    def test_fire_and_forget_records_start_and_ack_before_dispatch(self):
        job = Path(self.pump._JOBS) / '0001.json'
        job.write_text(json.dumps({'_cid': '0001', 'type': 'marionette_recalc', 'params': {}}))
        calls = []

        def dispatch(command, params):
            self.assertFalse(job.exists())
            self.assertIn('START cid=0001 cmd=marionette_recalc', Path(self.pump._LOG).read_text())
            result = json.loads((Path(self.pump._RESULTS) / '0001.json').read_text())
            self.assertEqual(result['status'], 'triggered')
            calls.append(command)

        self.pump._dispatch = dispatch
        self.assertEqual(self.pump.pump_all(), 1)
        self.assertEqual(calls, ['marionette_recalc'])

    def job(self):
        path = Path(self.pump._JOBS) / 'completion-test.json'
        path.write_text(json.dumps({'_cid': 'completion-test', 'type': 'fixture', 'params': {}}))
        return path

    def completion(self):
        return Path(self.pump._IPC) / 'pump.complete.stamp'

    def test_completion_stamp_is_after_outer_execution_and_guard_reset(self):
        self.job()
        original_write = self.pump._write_json
        events = []
        def write(path, value):
            if Path(path) == self.completion():
                self.assertFalse(self.pump._pumping)
                events.append('completed')
            return original_write(path, value)
        def dispatch(*args):
            self.assertTrue(self.pump._pumping)
            self.assertFalse(self.completion().exists())
            events.append('dispatched')
            return {'ok': True}
        self.pump._dispatch = dispatch
        with patch.object(self.pump, '_write_json', write):
            self.assertEqual(self.pump.pump_all(), 1)
        self.assertEqual(events, ['dispatched', 'completed'])
        stamp = json.loads(self.completion().read_text())
        self.assertEqual(stamp['schema_version'], 1)
        self.assertIsInstance(stamp['completed_ns'], int)
        self.assertFalse(self.completion().with_suffix('.stamp.tmp').exists())

    def test_nested_invocation_does_not_acknowledge_running_outer_job(self):
        self.job()
        self.completion().write_text('previous completion')
        def dispatch(*args):
            self.assertEqual(self.pump.pump_all(), 0)
            self.assertTrue(self.pump._pumping)
            self.assertEqual(self.completion().read_text(), 'previous completion')
            return {'ok': True}
        self.pump._dispatch = dispatch
        self.pump.pump_all()
        self.assertNotEqual(self.completion().read_text(), 'previous completion')

    def test_outer_failure_acknowledges_end_without_replaying_consumed_job(self):
        job = self.job()
        self.pump._dispatch = Mock(side_effect=SystemExit('outer failure'))
        with self.assertRaisesRegex(SystemExit, 'outer failure'):
            self.pump.pump_all()
        self.assertFalse(self.pump._pumping)
        self.assertFalse(job.exists())
        self.assertTrue(self.completion().is_file())

    def test_empty_outer_invocation_updates_completion_for_a_delayed_trigger(self):
        with patch.object(self.pump.time, 'time_ns', side_effect=[123, 456]):
            self.assertEqual(self.pump.pump_all(), 0)
            self.assertEqual(json.loads(self.completion().read_text())['completed_ns'], 123)
            self.assertEqual(self.pump.pump_all(), 0)
            self.assertEqual(json.loads(self.completion().read_text())['completed_ns'], 456)

    def test_completion_io_failure_does_not_hide_original_exception(self):
        self.job()
        self.pump._dispatch = Mock(side_effect=SystemExit('original failure'))
        with patch.object(self.pump, '_write_json', side_effect=OSError('stamp unavailable')), \
                patch.object(self.pump, '_log') as log:
            with self.assertRaisesRegex(SystemExit, 'original failure'):
                self.pump.pump_all()
        self.assertFalse(self.pump._pumping)
        self.assertTrue(any('completion stamp' in call.args[0] for call in log.call_args_list))


if __name__ == '__main__':
    unittest.main()
