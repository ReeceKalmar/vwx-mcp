"""Static boundaries for native scheduling; actual Python menu-command delivery needs VW."""
import re
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'native/Source/Bridge/VwxBridgePalette.cpp'


def function_body(source, signature):
    start = source.index('{', source.index(signature))
    depth = 1
    end = start + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start + 1:end - 1]


class NativeSchedulingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding='utf-8')

    def test_native_sources_cannot_inject_global_input_take_focus_or_change_keys(self):
        forbidden = re.compile(r'\b(?:keybd_event|mouse_event|SendInput|SetForegroundWindow|SetFocus|AttachThreadInput|SetKeyboardState)\s*\(')
        for path in (ROOT / 'native/Source').rglob('*'):
            if path.suffix in ('.h', '.cpp'):
                with self.subTest(path=path):
                    self.assertIsNone(forbidden.search(path.read_bytes().decode('latin-1')))
        for keyboard_path in ('WM_KEYDOWN', 'WM_KEYUP', 'PostBackgroundHotkey', 'GetKeyboardState', 'RestoreKeyState'):
            self.assertNotIn(keyboard_path, self.source)

    def test_every_trigger_posts_menu_command_after_pending_and_modal_guards(self):
        body = function_body(self.source, 'static void TriggerPump()')
        self.assertEqual(body.count('PostBackgroundMenuCommand()'), 1)
        self.assertLess(body.index('gSchedule.CanPost()'), body.index('PostBackgroundMenuCommand()'))
        self.assertLess(body.index('ModalDialogOpen()'), body.index('PostBackgroundMenuCommand()'))
        self.assertIn('gSchedule.Posted(', body)
        self.assertNotIn('SendMessage', body)

    def test_timer_posts_only_private_one_use_broker_token(self):
        body = function_body(self.source, 'static bool PostBackgroundMenuCommand()')
        self.assertLess(body.index('gMenuBroker.CanQueue()'), body.index('gMenuBroker.Reserve()'))
        self.assertLess(body.index('BackgroundInvocationAllowed()'), body.index('PostMessageW('))
        self.assertLess(body.index('gMenuBroker.Reserve()'), body.index('PostMessageW('))
        self.assertIn('PostMessageW(gMenuBrokerWindow, kInvokeNamedMenuMessage, static_cast<WPARAM>(token), 0)', body)
        self.assertIn('gMenuBroker.PostFailed(token)', body)
        self.assertEqual(body.count('PostMessageW('), 1)
        self.assertNotIn('SendMessage', body)
        self.assertNotIn('DoMenuName(', body)
        self.assertNotIn('WM_COMMAND', self.source)
        self.assertNotIn('MenuCommandLookup', self.source)

    def test_frame_process_thread_and_interactive_state_are_checked_before_post_and_delivery(self):
        body = function_body(self.source, 'static bool BackgroundInvocationAllowed()')
        for guard in ('processId != GetCurrentProcessId()', 'threadId != GetCurrentThreadId()',
                      'threadId != gHostUiThread', 'gPumpTimer == 0 || gPaused', 'IsWindowVisible(wnd)',
                      'IsIconic(wnd)', 'IsWindowEnabled(wnd)', 'GetGUIThreadInfo(threadId, &threadInfo)',
                      'GUI_INMENUMODE', 'GUI_SYSTEMMENUMODE', 'GUI_POPUPMENUMODE', 'GUI_INMOVESIZE',
                      'ModalDialogOpen()', 'gSDK == nullptr'):
            self.assertIn(guard, body)
        self.assertNotIn('GetMenu(', body)
        post = function_body(self.source, 'static bool PostBackgroundMenuCommand()')
        delivery = function_body(self.source, 'static LRESULT CALLBACK MenuBrokerWindowProc(HWND wnd, UINT message, WPARAM token, LPARAM unused)\n{')
        self.assertLess(post.index('BackgroundInvocationAllowed()'), post.index('PostMessageW('))
        self.assertLess(delivery.index('BackgroundInvocationAllowed()'), delivery.index('gSDK->DoMenuName('))

    def test_authoritative_frame_and_private_broker_initialized_before_timer(self):
        init = function_body(self.source, 'static bool InitializeMenuBroker()')
        self.assertIn('gVwMainWnd = GS_GetMainHWND(gCBP)', init)
        self.assertIn('gHostUiThread != GetCurrentThreadId()', init)
        self.assertIn('existing.lpfnWndProc != MenuBrokerWindowProc', init)
        self.assertIn('existing.hInstance != module', init)
        self.assertIn('HWND_MESSAGE', init)
        self.assertNotIn('GetWindowText', self.source)
        self.assertNotIn('FindVwMainWindow', self.source)
        start = function_body(self.source, 'void VwxBridge_StartPumpTimer()')
        self.assertLess(start.index('InitializeMenuBroker()'), start.index('SetTimer('))
        stop = function_body(self.source, 'void VwxBridge_StopPumpTimer()')
        self.assertIn('if (DestroyWindow(broker))\n\t\t\tgMenuBroker.TargetDestroyed();', stop)
        self.assertIn('gMenuBrokerWindow = broker;', stop)
        self.assertNotIn('gSchedule =', stop)
        self.assertNotIn('gSchedule.pending = false', self.source)

    def test_broker_consumes_token_and_rechecks_fresh_queue_runner_before_sdk_menu(self):
        body = function_body(self.source, 'static LRESULT CALLBACK MenuBrokerWindowProc(HWND wnd, UINT message, WPARAM token, LPARAM unused)\n{')
        call = body.index('gSDK->DoMenuName("VWX Bridge Start", 0)')
        for guard in ('wnd != gMenuBrokerWindow', 'unused != 0', 'GetCurrentThreadId() != gHostUiThread',
                      'gMenuBroker.BeginDelivery(', 'gTimerCallbackActive || !gSchedule.pending',
                      'CountJobs(pluginDir)', 'gLastQueue <= 0', 'gRunnerStamp != gPostedRunnerStamp',
                      'gCompletionStamp != gSchedule.stampBefore',
                      'RunnerMayBeActive(gRunnerStamp, gCompletionStamp)'):
            self.assertLess(body.index(guard), call)
        self.assertIn('~DeliveryGuard() { gMenuBroker.EndDelivery(); }', body)
        self.assertEqual(self.source.count('gSDK->DoMenuName('), 1)
        self.assertLess(body.index('++gMenuInvocations'), call)
        self.assertGreater(body.index('++gMenuReturns'), call)
        self.assertIn('catch (...)', body)
        for no_forged_success in ('gSchedule.Observe(', 'gSchedule.pending =', 'PostMessage', 'WriteRunnerStamp'):
            self.assertNotIn(no_forged_success, body)

    def test_timer_reentry_guard_preserves_menu_runner_execution_boundary(self):
        body = function_body(self.source, 'static void CALLBACK PumpTimerProc(HWND, UINT, UINT_PTR timerId, DWORD)')
        self.assertIn('|| gTimerCallbackActive', body)
        self.assertIn('|| gMenuBroker.active', body)
        self.assertLess(body.index('gTimerCallbackActive = true'), body.index('gSchedule.Observe('))
        self.assertIn('~CallbackGuard() { gTimerCallbackActive = false; }', body)
        self.assertLess(body.index('gSchedule.Observe('), body.index('TriggerPump()'))
        self.assertIn('gLastQueue > 0 && !gPaused', body)
        self.assertNotIn('DoMenuName(', body)
        code = re.sub(r'//[^\n]*|/\*.*?\*/', '', self.source, flags=re.S)
        for forbidden in ('ExecuteScript', 'PythonExecute', 'PythonBeginContext', 'CallPluginLibrary',
                          'DoMenuTextByName', 'SendMessage', 'SendMessageW', 'SendMessageA'):
            self.assertIsNone(re.search(r'\b' + forbidden + r'\s*\(', code))

    def test_post_uses_fresh_completion_baseline_and_defers_active_outer_runner(self):
        body = function_body(self.source, 'static bool PostBackgroundMenuCommand()')
        for filename in ('pump.stamp', 'pump.complete.stamp'):
            read = body.index('ReadRunnerStamp(pluginDir, "' + filename + '")')
            self.assertLess(body.index('BackgroundInvocationAllowed()'), read)
            self.assertLess(read, body.index('PostMessageW('))
        self.assertLess(body.index('RunnerMayBeActive(gRunnerStamp, gCompletionStamp)'), body.index('PostMessageW('))

    def test_diagnostics_distinguish_posts_from_completion_and_write_atomically(self):
        status = function_body(self.source, 'static nlohmann::json SchedulerStatus()\n{')
        for key in ('background_posts', 'foreground_posts', 'runner_completions_observed', 'pending',
                    'last_trigger_state', 'acknowledgment_timeouts', 'evidence_scope', 'frame_source',
                    'frame_has_win32_menu', 'broker_message_pending', 'menu_invocation_active',
                    'menu_invocations', 'menu_returns', 'broker_rejections', 'keyboard_state_modified'):
            self.assertIn('status["' + key + '"]', status)
        self.assertIn('sdk-named-menu-broker-ack-v4', status)
        self.assertIn('status["modifiers_pending_restore"] = false;', status)
        self.assertIn('status["keyboard_state_modified"] = false;', status)
        write = function_body(self.source, 'static void WriteSchedulerStatus(const TXString& pluginDir)\n{')
        self.assertIn('native.scheduler.json', write)
        self.assertIn('WriteAtomicStatusFile(path.GetWCharPtr(), SchedulerStatus().dump())', write)
        heartbeat = function_body(self.source, 'static void WriteAlive(')
        self.assertIn('WriteAtomicStatusFile(path.GetWCharPtr(), data)', heartbeat)
        for published_writer in (write, heartbeat):
            self.assertNotIn('_wfopen', published_writer)
            self.assertNotIn('fwrite', published_writer)
        publisher = (SOURCE.parent / 'AtomicStatusFile.h').read_text(encoding='utf-8')
        self.assertIn('MOVEFILE_REPLACE_EXISTING', publisher)
        self.assertLess(publisher.index('fclose(file)'), publisher.index('MoveFileExW('))
        self.assertIn('written && closed', publisher)
        timer = function_body(self.source, 'static void CALLBACK PumpTimerProc(HWND, UINT, UINT_PTR timerId, DWORD)')
        self.assertIn('gSchedule.Observe(gCompletionStamp,', timer)
        self.assertNotIn('gSchedule.Observe(gRunnerStamp,', timer)
    @unittest.skipUnless(os.name == 'nt', 'Native scheduler compile assertions require MSVC on Windows')
    def test_production_scheduler_policy_compiles_all_behavior_assertions(self):
        vswhere = Path(os.environ.get('ProgramFiles(x86)', '')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
        if not vswhere.is_file():
            self.skipTest('MSVC discovery tool not installed')
        instances = json.loads(subprocess.check_output(
            [str(vswhere), '-all', '-products', '*', '-format', 'json'], text=True))
        compilers = [Path(instance['installationPath']) / 'VC/Tools/MSVC/14.42.34433/bin/Hostx64/x64/cl.exe'
                     for instance in instances]
        compiler = next((path for path in compilers if path.is_file()), None)
        if compiler is None:
            self.skipTest('Configured MSVC v143 14.42 compiler not installed')
        with tempfile.TemporaryDirectory(prefix='vwx-native-policy-') as temporary:
            result = subprocess.run([str(compiler), '/nologo', '/std:c++20', '/constexpr:steps10000000', '/c',
                                     str(ROOT / 'tests/native_schedule_policy.cpp'),
                                     '/Fo' + str(Path(temporary) / 'policy.obj')],
                                    capture_output=True, text=True, cwd=temporary)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((Path(temporary) / 'policy.obj').is_file())


if __name__ == '__main__':
    unittest.main()
