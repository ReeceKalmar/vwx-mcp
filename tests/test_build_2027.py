"""Offline build discovery/preflight tests; never start a real native build."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('build_2027_tests', ROOT / 'tools/build_2027.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class Build2027Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='vwx-build-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.sdk = self.directory / 'SDK with spaces'
        for name in BUILD.SDK_FILES:
            file = self.sdk / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'placeholder')
        self.header = self.sdk / BUILD.SDK_FILES[0]
        self.header.write_text('#define SDK_VERSION /* public SDK annotation */ 3200\n', encoding='utf-8')
        self.program_files = self.directory / 'Program Files (x86)'
        self.vswhere = self.program_files / 'Microsoft Visual Studio/Installer/vswhere.exe'
        self.vswhere.parent.mkdir(parents=True)
        self.vswhere.touch()
        self.environment = {'ProgramFiles(x86)': str(self.program_files)}

    def installation(self, version):
        root = self.directory / ('VS ' + version)
        for name in ('MSBuild/Current/Bin/MSBuild.exe', 'MSBuild/Microsoft/VC/v170/Microsoft.Cpp.Default.props',
                     'MSBuild/Microsoft/VC/v170/Microsoft.Cpp.targets',
                     'VC/Tools/MSVC/14.42.34433/bin/Hostx64/x64/cl.exe'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        (root / 'MSBuild/Microsoft/VC/v170/Platforms/x64/PlatformToolsets/v143').mkdir(parents=True)
        return {'installationVersion': version, 'installationPath': str(root)}

    def test_official_inline_annotation_and_spaces_in_sdk_path(self):
        self.assertEqual(BUILD.validate_sdk(self.sdk), self.sdk.resolve())

    def test_missing_resource_tool_is_rejected_before_build(self):
        (self.sdk / 'SDKLib/ToolsWin/BuildVWR/7z.dll').unlink()
        with patch.object(BUILD.subprocess, 'call') as launch, patch.object(BUILD.sys, 'platform', 'win32'):
            with contextlib.redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit):
                BUILD.main(['--sdk', str(self.sdk)])
            self.assertIn('7z.dll', error.getvalue())
            launch.assert_not_called()

    def test_wrong_version_cannot_hide_behind_comment_or_duplicate_definition(self):
        for header in ('#define SDK_VERSION 3100 // update to 3200\n',
                       '// #define SDK_VERSION 3200\n#define SDK_VERSION 3100\n',
                       '#define SDK_VERSION 3200\n#define SDK_VERSION 3100\n'):
            with self.subTest(header=header):
                self.header.write_text(header, encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'SDK_VERSION'):
                    BUILD.validate_sdk(self.sdk)

    def test_discovery_uses_numeric_versions_and_requires_complete_targets(self):
        old, new, incomplete = [self.installation(v) for v in ('17.9.1', '17.10.2', '18.0.0')]
        (Path(incomplete['installationPath']) / 'MSBuild/Microsoft/VC/v170/Microsoft.Cpp.targets').unlink()
        with patch.object(BUILD.subprocess, 'check_output', return_value=json.dumps([old, new, incomplete])):
            msbuild, targets = BUILD.discover_toolchain(self.environment)
        self.assertEqual(msbuild, Path(new['installationPath']) / 'MSBuild/Current/Bin/MSBuild.exe')
        self.assertEqual(targets, Path(new['installationPath']) / 'MSBuild/Microsoft/VC/v170')

    def test_missing_vswhere_and_malformed_discovery_have_actionable_errors(self):
        with self.assertRaisesRegex(ValueError, 'ProgramFiles'):
            BUILD.discover_toolchain({})
        for returned in ('not JSON', '{}', '[{}]', '[{"installationVersion": 18}]'):
            with self.subTest(returned=returned), patch.object(BUILD.subprocess, 'check_output', return_value=returned):
                with self.assertRaisesRegex(ValueError, 'discover Visual Studio'):
                    BUILD.discover_toolchain(self.environment)
        self.vswhere.unlink()
        with self.assertRaisesRegex(ValueError, 'vswhere.exe'):
            BUILD.discover_toolchain(self.environment)

    def test_discovery_failure_and_missing_compiler_do_not_launch_build(self):
        with patch.object(BUILD.subprocess, 'check_output', side_effect=subprocess.CalledProcessError(1, 'vswhere')):
            with self.assertRaisesRegex(ValueError, 'discover Visual Studio'):
                BUILD.discover_toolchain(self.environment)
        with patch.object(BUILD.subprocess, 'check_output', return_value='[]'):
            with self.assertRaisesRegex(ValueError, '14.42.34433'):
                BUILD.discover_toolchain(self.environment)

    def test_build_argument_boundaries_environment_and_return_code(self):
        installation = self.installation('18.0.1')
        environment = dict(self.environment, VWSDK2027=str(self.sdk), Path='one', PATH='two')
        with patch.object(BUILD.sys, 'platform', 'win32'), patch.object(BUILD.os, 'environ', environment), \
                patch.object(BUILD.subprocess, 'check_output', return_value=json.dumps([installation])), \
                patch.object(BUILD.subprocess, 'call', return_value=17) as launch:
            self.assertEqual(BUILD.main([]), 17)
        command = launch.call_args.args[0]
        self.assertIn('/p:VWSDK2027=' + str(self.sdk), command)
        self.assertIn('/p:Configuration=Release', command)
        self.assertIn('/p:Platform=x64', command)
        self.assertEqual(command[1], str(ROOT / 'native/VwxBridge2027.vcxproj'))
        self.assertEqual(launch.call_args.kwargs['cwd'], ROOT)
        self.assertEqual(launch.call_args.kwargs['env']['PATH'], 'two')
        self.assertNotIn('Path', launch.call_args.kwargs['env'])
        self.assertEqual(environment['Path'], 'one')

    def test_other_platform_fails_without_executing_tools(self):
        with patch.object(BUILD.sys, 'platform', 'linux'), patch.object(BUILD.subprocess, 'check_output') as discover:
            with contextlib.redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit):
                BUILD.main(['--sdk', str(self.sdk)])
        self.assertIn('requires Windows', error.getvalue())
        discover.assert_not_called()


if __name__ == '__main__':
    unittest.main()
