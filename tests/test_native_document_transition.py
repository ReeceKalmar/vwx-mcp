"""Actual deferred native transition callback tests; no installed-host calls."""
import json
import os
from pathlib import Path
import re
import unittest

import test_native_arc_helper as compiler

ROOT = Path(__file__).resolve().parents[1]


class NativeDocumentTransitionTests(unittest.TestCase):
    def test_broker_defers_native_action_until_outer_menu_returns(self):
        source = (ROOT / 'native/Source/Bridge/VwxBridgePalette.cpp').read_text(encoding='utf-8')
        body = source[source.index('static LRESULT CALLBACK MenuBrokerWindowProc(HWND wnd, UINT message, WPARAM token, LPARAM unused)\n{'):]
        begin = body.index('DocumentTransition::BeginMenu(')
        invoke = body.index('gSDK->DoMenuName("VWX Bridge Start", 0)')
        end = body.index('DocumentTransition::EndMenu(')
        self.assertLess(begin, invoke)
        self.assertLess(invoke, end)
        self.assertIn('completed != 0 && completed != gSchedule.stampBefore', body[:end + 200])
        self.assertIn('DocumentTransition::EndMenu(static_cast<std::uint64_t>(token), false)', body)

    def test_native_adapter_has_no_close_input_focus_or_script_path(self):
        source = (ROOT / 'native/Source/Bridge/DocumentTransition.cpp').read_text(encoding='utf-8')
        code = re.sub(r'//[^\n]*|/\*.*?\*/', '', source, flags=re.S)
        self.assertEqual(code.count('SaveActiveDocumentPath('), 1)
        self.assertEqual(code.count('SwitchToOpenFile('), 1)
        self.assertEqual(code.count('OpenDocumentPath('), 1)
        self.assertIn('OpenDocumentPath(fTarget, false)', code)
        for forbidden in ('CloseDocument', 'CloseAllFiles', 'SetForegroundWindow', 'ShowWindow',
                          'SendInput', 'SendMessage', 'PostMessage', 'DoMenuName', 'PythonExecute',
                          'ExecuteScript', 'TerminateProcess'):
            self.assertNotIn(forbidden, code)
        project = (ROOT / 'native/VwxBridge2027.vcxproj').read_text(encoding='utf-8')
        self.assertIn('Source\\Bridge\\DocumentTransition.cpp', project)
        self.assertIn('Source\\Bridge\\DocumentTransitionPolicy.h', project)

    @unittest.skipUnless(os.name == 'nt', 'Actual callback model requires MSVC on Windows')
    def test_compiled_callback_and_deferred_sdk_state_machine(self):
        output = compiler.run_native_model(self, 'native_document_transition.cpp')
        idle, completed = [json.loads(line) for line in output.splitlines() if line]
        self.assertEqual(idle, {'schema_version': 1, 'process_id': 7, 'request_id': '', 'phase': 'idle',
                               'source_path': '', 'target_path': '', 'code': 1, 'dispatched': False,
                               'save_confirmed': False, 'transition_dispatched': False,
                               'source_ref': -1, 'target_ref': -1})
        self.assertEqual(completed['phase'], 'completed')
        self.assertEqual(completed['request_id'], 'a' * 64)
        self.assertEqual(completed['target_path'], 'C:\\Projects\\café 東京 😀 - house.vwx')
        self.assertEqual(completed['code'], 1)
        self.assertTrue(completed['dispatched'])
        self.assertTrue(completed['save_confirmed'])
        self.assertTrue(completed['transition_dispatched'])
        self.assertEqual((completed['source_ref'], completed['target_ref']), (10, 100))


if __name__ == '__main__':
    unittest.main()
