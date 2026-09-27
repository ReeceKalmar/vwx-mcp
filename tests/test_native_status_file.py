"""Compile the real atomic publisher and exercise actual Windows file races."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Real file-sharing tests require Windows and MSVC')
class NativeStatusFileTests(unittest.TestCase):
    def test_atomic_publication_preserves_complete_generations_and_failure_state(self):
        vswhere = Path(os.environ.get('ProgramFiles(x86)', '')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
        if not vswhere.is_file():
            self.skipTest('MSVC discovery tool not installed')
        instances = json.loads(subprocess.check_output(
            [str(vswhere), '-all', '-products', '*', '-format', 'json'], text=True))
        candidates = [Path(item['installationPath']) / 'VC/Tools/MSVC/14.42.34433/bin/Hostx64/x64/cl.exe'
                      for item in instances]
        compiler = next((candidate for candidate in candidates if candidate.is_file()), None)
        if compiler is None:
            self.skipTest('Configured MSVC v143 14.42 compiler not installed')
        msvc = compiler.parents[3]
        kits = Path(os.environ.get('ProgramFiles(x86)', '')) / 'Windows Kits/10'
        versions = sorted((kits / 'Include').glob('10.*'), key=lambda p: tuple(map(int, p.name.split('.'))))
        kit = next((p for p in reversed(versions) if (p / 'ucrt/corecrt.h').is_file()
                    and (p / 'um/Windows.h').is_file()), None)
        if kit is None:
            self.skipTest('Windows SDK headers not installed')
        with tempfile.TemporaryDirectory(prefix='vwx-atomic-status-') as temporary:
            temporary = Path(temporary)
            executable = temporary / 'status-test.exe'
            test_directory = temporary / 'files'
            test_directory.mkdir()
            command = [str(compiler), '/nologo', '/std:c++20', '/EHsc', '/MD', '/utf-8',
                       '/I' + str(msvc / 'include'), '/I' + str(kit / 'ucrt'),
                       '/I' + str(kit / 'um'), '/I' + str(kit / 'shared'),
                       str(ROOT / 'tests/native_status_file.cpp'),
                       '/Fo' + str(temporary / 'status-test.obj'), '/Fe' + str(executable),
                       '/link', '/LIBPATH:' + str(msvc / 'lib/x64'),
                       '/LIBPATH:' + str(kits / 'Lib' / kit.name / 'ucrt/x64'),
                       '/LIBPATH:' + str(kits / 'Lib' / kit.name / 'um/x64'), 'kernel32.lib']
            built = subprocess.run(command, capture_output=True, text=True, cwd=temporary, timeout=90)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(executable), str(test_directory)], capture_output=True,
                                 text=True, cwd=temporary, timeout=45)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            for group in ('unicode_and_exact_bytes', 'locked_failure_preserves_old',
                          'old_handle_generation', 'concurrent_complete_generations',
                          'invalid_parent_preserves_existing'):
                self.assertIn(group + ' passed', ran.stdout)


if __name__ == '__main__':
    unittest.main()
