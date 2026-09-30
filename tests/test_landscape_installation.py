"""Read-only installation diagnostics against isolated fake source/install trees."""
import ast
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('landscape_installation', ROOT / 'tools/check_landscape_installation.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class LandscapeInstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='vwx-installation-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / 'repo'
        self.appdata = self.root.parent / 'AppData'
        self.plugin = self.appdata / 'Nemetschek/Vectorworks/2027/Plug-ins/VWX-MCP'
        self.plugin.mkdir(parents=True)
        for name in CHECK.PYTHON_FILES:
            data = ('# inert source for ' + name + '\n').encode()
            self.write(self.root / 'vwx-plugin' / name, data)
            self.write(self.plugin / name, data)
        index = b'{}\n'
        identity = dict(CHECK.SDK_IDENTITY, index_sha256=hashlib.sha256(index).hexdigest())
        for base in (self.root / 'vwx-plugin', self.plugin):
            self.write(base / 'vs_index.json', index)
            self.write(base / 'vs_index_meta.json', json.dumps(identity).encode())
        for name in CHECK.SERVER_FILES:
            self.write(self.root / 'mcp-server' / name, b'raise RuntimeError("must never import server")\n')
        self.write(self.root / 'mcp-server/requirements.txt', b'fastmcp==4.0.3\npillow>=11.0\n')
        for name in CHECK.NATIVE_FILES:
            self.write(self.plugin.parent / name, ('fake ' + name).encode())

    @staticmethod
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    @staticmethod
    def versions(name):
        return {'fastmcp': '4.0.3', 'Pillow': '11.3.0'}[name]

    def report(self, **kwargs):
        settings = {'repo': self.root, 'plugin_dir': self.plugin,
                    'environment': {}, 'python_version': (3, 12, 9), 'package_version': self.versions}
        settings.update(kwargs)
        return CHECK.check_installation(**settings)

    def test_matching_python_and_native_build_files_pass_without_host_readiness_claim(self):
        for name in CHECK.NATIVE_FILES:
            self.write(self.root / 'native/Output/2027/Release' / name,
                       (self.plugin.parent / name).read_bytes())
        report = self.report()
        self.assertTrue(report['ok'], report['errors'])
        self.assertEqual(report['warnings'], [])
        self.assertEqual(report['plugin_dir'], str(self.plugin.resolve()))
        self.assertFalse(report['host_readiness']['checked'])
        self.assertFalse(report['modified_installation'])
        self.assertTrue(all(row['status'] == 'ok' for row in report['checks']))

    def test_native_artifacts_without_local_build_are_present_but_identity_unverified(self):
        report = self.report()
        self.assertTrue(report['ok'])
        self.assertEqual([row['code'] for row in report['warnings']], ['NATIVE_BUILD_UNAVAILABLE'] * 2)
        self.assertEqual([row['status'] for row in report['checks'] if row['component'].endswith(('.vlb', '.vwr'))],
                         ['present_without_local_build'] * 2)

    def test_missing_project_guard_and_outdated_takeoff_companion_fail(self):
        (self.plugin / 'project_guard.py').unlink()
        self.write(self.plugin / 'landscape_takeoff.py', b'# old module\n')
        report = self.report()
        self.assertFalse(report['ok'])
        self.assertIn(('INSTALLED_MISSING', 'installed/project_guard.py'),
                      [(row['code'], row['component']) for row in report['errors']])
        self.assertIn(('INSTALLED_MISMATCH', 'installed/landscape_takeoff.py'),
                      [(row['code'], row['component']) for row in report['errors']])

    def test_missing_native_resource_is_not_hidden_by_valid_python_files(self):
        (self.plugin.parent / 'VwxBridge.vwr').unlink()
        report = self.report()
        self.assertFalse(report['ok'])
        self.assertIn('NATIVE_MISSING', [row['code'] for row in report['errors']])

    def test_native_mismatch_is_measured_against_local_build_when_available(self):
        self.write(self.root / 'native/Output/2027/Release/VwxBridge.vlb', b'another build')
        report = self.report()
        self.assertFalse(report['ok'])
        failure = next(row for row in report['checks'] if row['component'] == 'installed/VwxBridge.vlb')
        self.assertEqual(failure['status'], 'mismatch')
        self.assertNotEqual(failure['source_sha256'], failure['installed_sha256'])

    def test_empty_native_or_source_artifacts_fail(self):
        self.write(self.plugin.parent / 'VwxBridge.vlb', b'')
        self.write(self.root / 'vwx-plugin/landscape_takeoff.py', b'')
        report = self.report()
        self.assertFalse(report['ok'])
        self.assertIn('NATIVE_UNREADABLE', [row['code'] for row in report['errors']])
        self.assertIn('SOURCE_UNREADABLE', [row['code'] for row in report['errors']])

    def test_source_only_needs_no_host_install_or_appdata(self):
        report = self.report(source_only=True, plugin_dir=self.root.parent / 'does-not-exist')
        self.assertTrue(report['ok'], report['errors'])
        self.assertIsNone(report['plugin_dir'])
        self.assertEqual(report['mode'], 'source_only')
        self.assertEqual(report['warnings'], [])
        self.assertFalse(any(row['component'].startswith('installed/') for row in report['checks']))

    def test_plugin_path_resolution_matches_explicit_then_environment_then_appdata(self):
        explicit = self.report(environment={'VWX_PLUGIN_DIR': str(self.root / 'wrong')})
        self.assertTrue(explicit['ok'])
        self.assertEqual(explicit['plugin_dir_origin'], 'argument')
        supplied = self.report(plugin_dir=None, environment={'VWX_PLUGIN_DIR': str(self.plugin), 'APPDATA': 'wrong'})
        self.assertTrue(supplied['ok'])
        self.assertEqual(supplied['plugin_dir_origin'], 'VWX_PLUGIN_DIR')
        inferred = self.report(plugin_dir=None, environment={'APPDATA': str(self.appdata)})
        self.assertTrue(inferred['ok'])
        self.assertEqual(inferred['plugin_dir_origin'], 'APPDATA_2027')
        self.assertEqual(inferred['plugin_dir'], supplied['plugin_dir'])

    def test_bad_explicit_plugin_path_does_not_fall_back_to_a_good_default(self):
        report = self.report(plugin_dir=self.root / 'wrong', environment={'APPDATA': str(self.appdata)})
        self.assertFalse(report['ok'])
        self.assertEqual(report['plugin_dir_origin'], 'argument')
        self.assertEqual(report['plugin_dir'], str((self.root / 'wrong').resolve()))

    def test_unresolved_plugin_path_is_actionable_and_non_success(self):
        report = self.report(plugin_dir=None, environment={})
        self.assertFalse(report['ok'])
        self.assertIn('PLUGIN_DIR_UNRESOLVED', [row['code'] for row in report['errors']])

    def test_wrong_python_missing_pillow_and_wrong_fastmcp_are_separate_errors(self):
        def versions(name):
            if name == 'Pillow':
                raise CHECK.metadata.PackageNotFoundError(name)
            return '4.0.2'
        report = self.report(source_only=True, python_version=(3, 14, 7), package_version=versions)
        self.assertFalse(report['ok'])
        self.assertEqual({row['component'] for row in report['errors'] if row['code'] == 'RUNTIME_DEPENDENCY'},
                         {'python', 'fastmcp', 'pillow'})

    def test_metadata_diagnostic_does_not_echo_exception_or_arbitrary_version_content(self):
        secret = 'fake-local-token-do-not-echo'
        def versions(name):
            if name == 'fastmcp':
                raise RuntimeError(secret)
            return '12.0.0\n' + secret
        report = self.report(source_only=True, package_version=versions)
        self.assertFalse(report['ok'])
        self.assertNotIn(secret, json.dumps(report))

    def test_wrong_sdk_identity_and_index_hash_are_rejected(self):
        original = json.loads((self.root / 'vwx-plugin/vs_index_meta.json').read_bytes())
        for changes in ({'sdk_version': 3100}, {'vectorworks_year': 2026}, {'sdk_build': 1},
                        {'function_count': 3098.0}, {'index_sha256': '0' * 64}):
            with self.subTest(changes=changes):
                self.write(self.root / 'vwx-plugin/vs_index_meta.json', json.dumps(dict(original, **changes)).encode())
                report = self.report(source_only=True)
                self.assertFalse(report['ok'])
                self.assertIn('SDK_METADATA', [row['code'] for row in report['errors']])

    def test_changed_requirement_pin_is_reported_even_with_current_runtime(self):
        self.write(self.root / 'mcp-server/requirements.txt', b'fastmcp>=4\npillow>=11.0\n')
        report = self.report(source_only=True)
        self.assertFalse(report['ok'])
        self.assertIn('REQUIREMENTS_PIN', [row['code'] for row in report['errors']])

    def test_checker_reads_no_leases_credentials_queues_or_native_code(self):
        secret = 'fake-owner-token-never-read'
        ignored = [self.plugin / 'bridge.project.json', self.plugin / 'bridge.maintenance.json',
                   self.plugin / 'CredentialsVwxMcp.json', self.plugin / 'ipc/jobs/job.json']
        for path in ignored:
            self.write(path, secret.encode())
        before = {path: path.read_bytes() for path in self.root.parent.rglob('*') if path.is_file()}
        original = Path.read_bytes
        def guarded_read(path):
            self.assertNotIn(path, ignored)
            return original(path)
        with patch.object(Path, 'read_bytes', guarded_read), \
                patch('subprocess.run', side_effect=AssertionError('no process execution')), \
                patch('socket.socket', side_effect=AssertionError('no host connection')):
            report = self.report(environment={'API_KEY': secret})
        after = {path: path.read_bytes() for path in self.root.parent.rglob('*') if path.is_file()}
        self.assertTrue(report['ok'])
        self.assertEqual(before, after)
        self.assertNotIn(secret, json.dumps(report))

    def test_checker_manifest_matches_the_deployment_controller(self):
        tree = ast.parse((ROOT / 'tools/restart_vectorworks.py').read_text(encoding='utf-8'))
        declaration = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                           and any(isinstance(target, ast.Name) and target.id == 'PYTHON_FILES' for target in node.targets))
        self.assertEqual(CHECK.PYTHON_FILES, ast.literal_eval(declaration))

    def test_cli_json_returns_nonzero_on_mismatch_and_zero_on_source_only(self):
        self.write(self.plugin / 'landscape_takeoff.py', b'# outdated\n')
        for arguments, expected in ((['--json', '--plugin-dir', str(self.plugin)], 1),
                                    (['--json', '--source-only'], 0)):
            output = io.StringIO()
            with patch.object(CHECK, 'ROOT', self.root), patch.object(CHECK.sys, 'version_info', (3, 12, 9)), \
                    patch.object(CHECK.metadata, 'version', self.versions), redirect_stdout(output):
                result = CHECK.main(arguments)
            report = json.loads(output.getvalue())
            self.assertEqual(result, expected)
            self.assertEqual(report['ok'], expected == 0)
            self.assertFalse(report['host_readiness']['checked'])


if __name__ == '__main__':
    unittest.main()
