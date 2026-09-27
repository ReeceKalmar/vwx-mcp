"""Compile the production scripting callback against an independent offline SDK model."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'native/Source/Bridge/BridgeVSFunctions.cpp'


def run_native_model(case, source):
    vswhere = Path(os.environ.get('ProgramFiles(x86)', '')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    if not vswhere.is_file():
        case.skipTest('MSVC discovery tool not installed')
    instances = json.loads(subprocess.check_output(
        [str(vswhere), '-all', '-products', '*', '-format', 'json'], text=True))
    compilers = [Path(instance['installationPath']) / 'VC/Tools/MSVC/14.42.34433/bin/Hostx64/x64/cl.exe'
                 for instance in instances]
    compiler = next((path for path in compilers if path.is_file()), None)
    if compiler is None:
        case.skipTest('Configured MSVC v143 14.42 compiler not installed')
    msvc = compiler.parents[3]
    kits = Path(os.environ.get('ProgramFiles(x86)', '')) / 'Windows Kits/10'
    versions = sorted((kits / 'Include').glob('10.*'), key=lambda path: tuple(map(int, path.name.split('.'))))
    kit = next((path for path in reversed(versions) if (path / 'ucrt/corecrt.h').is_file()), None)
    if kit is None:
        case.skipTest('Windows SDK C runtime headers not installed')
    with tempfile.TemporaryDirectory(prefix='vwx-native-model-') as temporary:
        executable = Path(temporary) / 'model-test.exe'
        command = [str(compiler), '/nologo', '/std:c++20', '/EHsc', '/MD',
                   '/I' + str(ROOT / 'tests/native_arc_test_sdk'),
                   '/I' + str(msvc / 'include'), '/I' + str(kit / 'ucrt'),
                   str(ROOT / 'tests' / source),
                   '/Fo' + str(Path(temporary) / 'model-test.obj'), '/Fe' + str(executable),
                   '/link', '/LIBPATH:' + str(msvc / 'lib/x64'),
                   '/LIBPATH:' + str(kits / 'Lib' / kit.name / 'ucrt/x64'),
                   '/LIBPATH:' + str(kits / 'Lib' / kit.name / 'um/x64'), 'kernel32.lib']
        result = subprocess.run(command, capture_output=True, text=True, cwd=temporary)
        case.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        ran = subprocess.run([str(executable)], capture_output=True, text=True, cwd=temporary)
        case.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        return ran.stdout


class NativeArcHelperTests(unittest.TestCase):
    def test_registered_in_existing_sdk_module_and_release_project(self):
        module = (ROOT / 'native/Source/ModuleMain.cpp').read_text(encoding='utf-8')
        project = (ROOT / 'native/VwxBridge2027.vcxproj').read_text(encoding='utf-8')
        self.assertIn('REGISTER_Extension<VwxBridge::CExtBridgeVSFunctions>( GROUPID_ExtensionVSFunctions,', module)
        self.assertIn('Source\\Bridge\\BridgeVSFunctions.cpp', project)
        self.assertIn('Source\\Bridge\\ArcAnglesPolicy.h', project)

    def test_helper_has_one_sdk_setter_and_no_runner_or_replacement_path(self):
        source = SOURCE.read_text(encoding='utf-8')
        code = re.sub(r'//[^\n]*|/\*.*?\*/', '', source, flags=re.S)
        self.assertEqual(code.count('GS_SetArcAnglesN('), 1)
        for forbidden in ('SetArc(', 'CreateArc', 'DoMenuName', 'PostMessage', 'SetTimer',
                          'PythonExecute', 'ExecuteScript', 'PythonBeginContext', 'DeleteObject',
                          'SetForegroundWindow', 'SendInput', 'CallPluginLibrary'):
            self.assertNotIn(forbidden, code)
        # Retain the SDK-tag/type assertions even when fake boundaries compile.
        for assertion in ('kHandleArgType == ArcAngles::kHandleArgument',
                          'kRealArgType == ArcAngles::kRealArgument',
                          'kArcNode == ArcAngles::kArcObjectType'):
            self.assertIn('static_assert(' + assertion + ')', source)

    @unittest.skipUnless(os.name == 'nt', 'Compiled callback tests require MSVC on Windows')
    def test_production_callback_guards_dispatch_and_no_replay(self):
        run_native_model(self, 'native_arc_helper.cpp')


if __name__ == '__main__':
    unittest.main()
