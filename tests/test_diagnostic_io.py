"""Status read contention recovery only; no native calls or request replay."""
import ast
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


IO = load('diagnostic_unit_tests', 'mcp-server/diagnostic_io.py')
MAINT = load('diagnostic_maintenance_tests', 'mcp-server/maintenance.py')
DELIVERY = load('diagnostic_delivery_tests', 'tools/check_sdk_background_delivery.py')
SUITE = load('diagnostic_suite_tests', 'tools/sdk_regression_suite.py')
with patch.dict(sys.modules, {'sdk_regression_suite': SUITE}):
    CLI = load('diagnostic_cli_tests', 'tools/run_sdk_regression.py')
    with patch.dict(sys.modules, {'run_sdk_regression': CLI}):
        BATCH = load('diagnostic_batch_tests', 'tools/run_sdk_regression_batch.py')


def heartbeat_method():
    tree = ast.parse((ROOT / 'mcp-server/vwx_mcp_server.py').read_text(encoding='utf-8'))
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'VwxFileTransport')
    method = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == 'bridge_state')
    namespace = {'time': time, 'bridge_lease': MAINT, 'VWX_ALIVE_MAX_AGE': 8}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<actual-bridge-state>', 'exec'), namespace)
    return namespace['bridge_state']


BRIDGE_STATE = heartbeat_method()


def scheduler():
    return dict(schema_version=1, sdk_version=3200, scheduler='sdk-named-menu-broker-ack-v4',
                menu_caption='VWX Bridge Start', frame_source='GS_GetMainHWND',
                updated_epoch=1000, process_id=123, timer_active=True, paused=False,
                queued_jobs=0, pending=False, modifiers_pending_restore=False,
                posts=0, runner_completions_observed=0, menu_invocations=0, menu_returns=0,
                runner_stamp=0, completion_stamp=0, foreground_posts=0, background_posts=0,
                trigger_failures=0, acknowledgment_timeouts=0, broker_rejections=0,
                broker_message_pending=False, menu_invocation_active=False,
                frame_available=True, broker_window_available=True, frame_has_win32_menu=False,
                menu_return_available=False, keyboard_state_modified=False, global_input=False,
                focus_changed_by_bridge=False)


class DiagnosticReadTests(unittest.TestCase):
    def test_success_reads_utf8_once_without_sleep_or_transform(self):
        raw = '1000 0\n'
        with patch.object(Path, 'read_text', return_value=raw) as read, patch.object(IO.time, 'sleep') as sleep:
            self.assertEqual(IO.read_diagnostic_text('native.alive'), raw)
        read.assert_called_once_with(encoding='utf-8')
        sleep.assert_not_called()

    def test_permission_contention_recovers_with_at_most_three_delays(self):
        for failures in (1, 2, 3):
            with self.subTest(failures=failures):
                values = [PermissionError('atomic replacement busy')] * failures + ['1000 0']
                with patch.object(Path, 'read_text', side_effect=values) as read, patch.object(IO.time, 'sleep') as sleep:
                    self.assertEqual(IO.read_diagnostic_text(Path('native.alive')), '1000 0')
                self.assertEqual(read.call_count, failures + 1)
                self.assertEqual(sleep.call_args_list, [call(.01)] * failures)

    def test_permanent_permission_error_raises_fourth_error_without_fifth_read(self):
        failures = [PermissionError(str(i)) for i in range(4)]
        with patch.object(Path, 'read_text', side_effect=failures + ['must not reach']) as read, \
                patch.object(IO.time, 'sleep') as sleep:
            with self.assertRaises(PermissionError) as caught:
                IO.read_diagnostic_text('native.scheduler.json')
        self.assertIs(caught.exception, failures[3])
        self.assertEqual(read.call_count, 4)
        self.assertEqual(sleep.call_args_list, [call(.01)] * 3)

    def test_other_errors_are_not_retried_or_reclassified(self):
        errors = (FileNotFoundError('missing'), OSError('I/O failure'),
                  UnicodeDecodeError('utf8', b'\xff', 0, 1, 'invalid'))
        for error in errors:
            with self.subTest(error=type(error).__name__):
                with patch.object(Path, 'read_text', side_effect=[error, 'later']) as read, \
                        patch.object(IO.time, 'sleep') as sleep:
                    with self.assertRaises(type(error)) as caught:
                        IO.read_diagnostic_text('native.alive')
                self.assertIs(caught.exception, error)
                self.assertEqual(read.call_count, 1)
                sleep.assert_not_called()

    def test_retry_stops_if_the_next_attempt_is_missing(self):
        with patch.object(Path, 'read_text', side_effect=[PermissionError(), FileNotFoundError(), 'later']) as read, \
                patch.object(IO.time, 'sleep') as sleep:
            with self.assertRaises(FileNotFoundError):
                IO.read_diagnostic_text('native.alive')
        self.assertEqual(read.call_count, 2)
        sleep.assert_called_once_with(.01)


class DiagnosticIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='vwx-diagnostic-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.ipc = self.base / 'ipc'
        (self.ipc / 'jobs').mkdir(parents=True)
        self.alive = self.ipc / 'native.alive'
        self.state = self.ipc / 'native.scheduler.json'
        self.reset_files()
        self.read_text = Path.read_text

    def reset_files(self):
        self.alive.write_text('1000 0', encoding='utf-8')
        self.state.write_text(json.dumps(scheduler()), encoding='utf-8')

    def readers(self, include_server=True):
        choices = [('maintenance', lambda: MAINT._readiness(self.base, now=1001) == 123),
                   ('batch', lambda: BATCH.bridge_readiness(self.base, now=1001)['ready']),
                   ('delivery', lambda: DELIVERY.read_readiness(self.base, now=1001)['ready'])]
        if include_server:
            def server():
                with patch.object(time, 'time', return_value=1001):
                    return BRIDGE_STATE(SimpleNamespace(alive=str(self.alive)))[0]
            choices.append(('server', server))
        return choices

    def observed(self, reader):
        try:
            return reader()
        except MAINT.MaintenanceError as error:
            self.assertEqual(error.code, 'VWX_MAINTENANCE_NOT_IDLE')
            return False

    def test_all_consumers_recover_each_diagnostic_permission_error(self):
        for name, reader in self.readers():
            targets = [self.alive] if name == 'server' else [self.alive, self.state]
            for target in targets:
                with self.subTest(reader=name, file=target.name):
                    counts = Counter()
                    def read(path, *args, **kwargs):
                        counts[path] += 1
                        if path == target and counts[path] <= 3:
                            raise PermissionError('atomic replacement in progress')
                        return self.read_text(path, *args, **kwargs)
                    with patch.object(Path, 'read_text', new=read), patch.object(time, 'sleep') as sleep:
                        self.assertTrue(reader())
                    self.assertEqual(counts[target], 4)
                    self.assertEqual(sleep.call_args_list, [call(.01)] * 3)
                    self.assertEqual(list((self.ipc / 'jobs').iterdir()), [])

    def test_all_consumers_fail_closed_after_four_permission_errors(self):
        for name, reader in self.readers():
            with self.subTest(reader=name):
                counts = Counter()
                def read(path, *args, **kwargs):
                    counts[path] += 1
                    if path == self.alive:
                        raise PermissionError('permanent denial')
                    return self.read_text(path, *args, **kwargs)
                with patch.object(Path, 'read_text', new=read), patch.object(time, 'sleep') as sleep:
                    self.assertFalse(self.observed(reader))
                self.assertEqual(counts[self.alive], 4)
                self.assertEqual(sleep.call_args_list, [call(.01)] * 3)

    def test_missing_malformed_stale_and_future_heartbeat_never_get_retried(self):
        for raw in (None, '', '1000', '1000 0 extra', 'nan 0', 'inf 0', '1000 2', '900 0', '1100 0', '9' * 400 + ' 0'):
            for name, reader in self.readers():
                with self.subTest(raw=raw, reader=name):
                    self.reset_files()
                    if raw is None:
                        self.alive.unlink()
                    else:
                        self.alive.write_text(raw, encoding='utf-8')
                    counts = Counter()
                    def read(path, *args, **kwargs):
                        counts[path] += 1
                        return self.read_text(path, *args, **kwargs)
                    with patch.object(Path, 'read_text', new=read), patch.object(time, 'sleep') as sleep:
                        self.assertFalse(self.observed(reader))
                    self.assertEqual(counts[self.alive], 1)
                    sleep.assert_not_called()

    def test_scheduler_parse_schema_stale_errors_are_not_retried(self):
        values = ['{', 'null', '[]', '{}', json.dumps(dict(scheduler(), schema_version=True)),
                  json.dumps(dict(scheduler(), sdk_version=3100)),
                  json.dumps(dict(scheduler(), updated_epoch=900))]
        for raw in values:
            for name, reader in self.readers(include_server=False):
                with self.subTest(raw=raw, reader=name):
                    self.reset_files()
                    self.state.write_text(raw, encoding='utf-8')
                    counts = Counter()
                    def read(path, *args, **kwargs):
                        counts[path] += 1
                        return self.read_text(path, *args, **kwargs)
                    with patch.object(Path, 'read_text', new=read), patch.object(time, 'sleep') as sleep:
                        self.assertFalse(self.observed(reader))
                    self.assertEqual(counts[self.state], 1)
                    sleep.assert_not_called()

    def test_lease_permission_error_is_not_routed_through_status_retry(self):
        lease = self.base / MAINT.LEASE_FILE
        lease.write_text('{}', encoding='utf-8')
        with patch.object(Path, 'read_text', side_effect=PermissionError('lease locked')) as read, \
                patch.object(time, 'sleep') as sleep:
            with self.assertRaises(MAINT.MaintenanceError) as caught:
                MAINT._read_lease(self.base)
        self.assertEqual(caught.exception.code, 'VWX_MAINTENANCE_STATE')
        read.assert_called_once_with(encoding='utf-8')
        sleep.assert_not_called()

    def test_absolute_module_loading_works_from_unrelated_directory_without_server_path(self):
        code = ('import importlib.util,sys\n'
                'for path in sys.argv[1:]:\n'
                ' spec=importlib.util.spec_from_file_location("standalone",path)\n'
                ' module=importlib.util.module_from_spec(spec)\n'
                ' spec.loader.exec_module(module)\n'
                ' assert callable(module.read_diagnostic_text)\n')
        completed = subprocess.run([sys.executable, '-B', '-I', '-c', code,
                                    str(ROOT / 'mcp-server/maintenance.py'),
                                    str(ROOT / 'tools/check_sdk_background_delivery.py')],
                                   cwd=self.base, capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == '__main__':
    unittest.main()
