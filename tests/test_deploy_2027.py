"""Run the deployment script against disposable files and a mocked process list."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PYTHON_FILES = ('commands.py', 'vwx_pump.py', 'BridgeStart_MenuCommand.py', 'vs_index.json',
                'vs_index_meta.json', 'sdk_catalog.json', 'sdk_generated.py', 'sdk_runtime.py', 'sdk_sequences.py')


@unittest.skipUnless(os.name == 'nt', 'Windows deployment requires PowerShell')
class Deploy2027Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='vwx-deploy-test-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.repo = self.directory / 'checkout with spaces'
        self.roaming = self.directory / 'roaming'
        self.plugins = self.roaming / 'Nemetschek/Vectorworks/2027/Plug-ins'
        self.python = self.plugins / 'VWX-MCP'
        self.script = self.repo / 'bridge/deploy_2027.ps1'
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / 'bridge/deploy_2027.ps1', self.script)
        self.sources = {}
        for name in PYTHON_FILES + ('VwxBridge.vlb', 'VwxBridge.vwr'):
            source = self.repo / ('vwx-plugin' if name in PYTHON_FILES else 'native/Output/2027/Release') / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(('new ' + name).encode('utf-8'))
            target = (self.python if name in PYTHON_FILES else self.plugins) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(('old ' + name).encode('utf-8'))
            self.sources[name] = source
        self.sources['vs_index_meta.json'].write_text(json.dumps({'sdk_version': 3200}), encoding='utf-8')
        self.job = self.python / 'ipc/jobs/previous-job.json'
        self.job.parent.mkdir(parents=True)
        self.job.write_bytes(b'preserve; never replay')
        self.backups = self.plugins.parent / 'MCP-Backups'

    def execute(self, running='0', prelude='', appdata=None):
        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"
        code = """$ErrorActionPreference = 'Stop'
$global:TestProcessChecks = 0
function Get-Process {
    param([string]$Name, $ErrorAction)
    $global:TestProcessChecks += 1
    if ($env:VWX_TEST_RUNNING -eq '1' -or ($env:VWX_TEST_RUNNING -eq 'second' -and $global:TestProcessChecks -eq 2)) {
        [pscustomobject]@{ Id = 123 }
    }
}
""" + prelude + '\n& ' + quote(self.script)
        environment = dict(os.environ, APPDATA=str(self.roaming if appdata is None else appdata), VWX_TEST_RUNNING=running)
        return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'RemoteSigned', '-Command', code],
                              env=environment, cwd=self.directory, capture_output=True, text=True, timeout=30)

    def assert_unmodified(self):
        self.assertEqual(self.job.read_bytes(), b'preserve; never replay')
        self.assertFalse(self.backups.exists())
        for name in self.sources:
            target = (self.python if name in PYTHON_FILES else self.plugins) / name
            self.assertEqual(target.read_bytes(), ('old ' + name).encode('utf-8'))

    def test_complete_deployment_backs_up_all_files_and_quarantines_queue(self):
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        backups = list(self.backups.iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'ipc/jobs/previous-job.json').read_bytes(), b'preserve; never replay')
        self.assertEqual(list((self.python / 'ipc/jobs').iterdir()), [])
        self.assertTrue((self.python / 'ipc/results').is_dir())
        for name, source in self.sources.items():
            target = (self.python if name in PYTHON_FILES else self.plugins) / name
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual((backups[0] / name).read_bytes(), ('old ' + name).encode('utf-8'))

    def test_missing_last_source_preserves_all_files_and_existing_queue(self):
        self.sources['VwxBridge.vwr'].unlink()
        result = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Deployment source missing', result.stderr)
        self.assert_unmodified()

    def test_short_appdata_alias_preserves_backup_and_queue_confinement(self):
        import ctypes
        from ctypes import wintypes
        get_short_path = ctypes.WinDLL('kernel32', use_last_error=True).GetShortPathNameW
        get_short_path.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        get_short_path.restype = wintypes.DWORD
        long_path = str(self.roaming.resolve())
        length = get_short_path(long_path, None, 0)
        self.assertGreater(length, 0, ctypes.get_last_error())
        buffer = ctypes.create_unicode_buffer(length)
        self.assertEqual(get_short_path(long_path, buffer, length), length - 1)
        if buffer.value.casefold() == long_path.casefold():
            self.skipTest('The test volume does not provide a distinct 8.3 alias')
        self.assertEqual(Path(buffer.value).resolve(), self.roaming.resolve())
        result = self.execute(appdata=buffer.value)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        backups = list(self.backups.iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'ipc/jobs/previous-job.json').read_bytes(), b'preserve; never replay')
        self.assertEqual(list((self.python / 'ipc/jobs').iterdir()), [])
        for name, source in self.sources.items():
            target = (self.python if name in PYTHON_FILES else self.plugins) / name
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual((backups[0] / name).read_bytes(), ('old ' + name).encode('utf-8'))

    def test_running_host_or_host_started_during_preflight_blocks_all_writes(self):
        for running in ('1', 'second'):
            with self.subTest(running=running):
                result = self.execute(running)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Close', result.stderr)
                self.assert_unmodified()

    def test_reparse_destination_is_rejected_before_backup_or_queue_move(self):
        redirected = self.directory / 'redirected'
        self.python.rename(redirected)
        quote = lambda p: "'" + str(p).replace("'", "''") + "'"
        prelude = 'New-Item -ItemType Junction -Path ' + quote(self.python) + ' -Target ' + quote(redirected) + ' | Out-Null'
        result = self.execute(prelude=prelude)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('reparse point', result.stderr)
        self.assert_unmodified()


if __name__ == '__main__':
    unittest.main()
