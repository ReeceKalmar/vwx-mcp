"""Offline verification of the actual native maintenance callback and JSON ABI."""
import json
import os
from pathlib import Path
import re
import unittest

import test_native_arc_helper as compiler


ROOT = Path(__file__).resolve().parents[1]


class NativeMaintenanceTests(unittest.TestCase):
    def test_only_public_prompt_preserving_quit_is_present(self):
        source = (ROOT / 'native/Source/Bridge/BridgeVSFunctions.cpp').read_text(encoding='utf-8')
        code = re.sub(r'//[^\n]*|/\*.*?\*/', '', source, flags=re.S)
        self.assertEqual(code.count('CloseAllFilesAndQuitVectorworks('), 1)
        self.assertIn('CloseAllFilesAndQuitVectorworks(true, false)', code)
        self.assertEqual(code.count('SaveActiveDocumentPath('), 1)
        self.assertIn('SaveActiveDocumentPath(fActiveFile) == noError', code)
        for forbidden in ('TerminateProcess', 'ExitProcess', 'PostQuitMessage', 'DoMenuName',
                          'DoMenuTextByName', 'SendMessage', 'PostMessage', 'SetForegroundWindow',
                          'SwitchToOpenFile', 'IsInMemoryOnly == false'):
            self.assertNotIn(forbidden, code)

    @unittest.skipUnless(os.name == 'nt', 'Production callback compile model requires MSVC on Windows')
    def test_actual_callback_state_machine_and_unicode_snapshot(self):
        output = compiler.run_native_model(self, 'native_maintenance_helper.cpp')
        snapshots = [json.loads(line) for line in output.splitlines() if line]
        self.assertEqual(snapshots, [
            {'status': 'ok', 'process_id': 7, 'count': 1, 'open_documents': [
                {'path': 'C:\\Projects\\café 東京 😀.vwx', 'file_ref': 10,
                 'active': True, 'in_memory_only': False}]},
            {'status': 'ok', 'process_id': 7, 'count': 1, 'open_documents': [
                {'path': 'Untitled "quote"\tline\n', 'file_ref': 10,
                 'active': True, 'in_memory_only': True}]},
            {'status': 'error', 'process_id': 7, 'code': -101}])


if __name__ == '__main__':
    unittest.main()
