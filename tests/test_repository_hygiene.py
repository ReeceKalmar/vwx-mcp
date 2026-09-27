"""Real isolated Git repositories exercise publication boundaries; no host calls."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('repository_hygiene_tests', ROOT / 'tools/check_repository.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class RepositoryHygieneTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='vwx-publication-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git('init', '-q')

    def git(self, *arguments):
        return subprocess.run(['git', '-C', str(self.root), *arguments], check=True,
                              capture_output=True, text=True)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def errors(self):
        return CHECK.check_repository(self.root)

    def test_missing_inline_image_and_reference_links_report_locations(self):
        self.write('README.md', '[one](missing.md)\n![two](assets/missing.png)\n[three]: gone.md\n')
        errors = self.errors()
        self.assertEqual(len(errors), 3)
        self.assertTrue(any('README.md:1:' in error and 'missing.md' in error for error in errors))
        self.assertTrue(any('README.md:2:' in error and 'assets/missing.png' in error for error in errors))
        self.assertTrue(any('README.md:3:' in error and 'gone.md' in error for error in errors))

    def test_valid_encoded_and_parent_links_with_fences_urls_and_anchors(self):
        self.write('A document.md', 'Content\n')
        self.write('docs/README.md', '[good](../A%20document.md#section)\n'
                   '[angle](<../A document.md>)\n[anchor](#here)\n[web](https://example.com/no.md)\n'
                   '```md\n[not a link](missing.md)\n```\n~~~\n![example](gone.png)\n~~~\n'
                   '`[inline example](missing.md)`\n    [indented code](missing.md)\n')
        self.assertEqual(self.errors(), [])

    def test_zero_and_unicode_whitespace_files_and_empty_directory(self):
        self.write('empty.txt', '')
        self.write('blank.txt', '\ufeff \t\n\u2003')
        (self.root / 'unused').mkdir()
        errors = self.errors()
        self.assertEqual(len(errors), 3)
        self.assertTrue(any('empty.txt: empty' in error for error in errors))
        self.assertTrue(any('blank.txt: empty' in error for error in errors))
        self.assertIn('unused/: empty nonignored directory', errors)

    def test_ignored_runtime_outputs_empty_directories_and_credentials_are_skipped(self):
        self.write('.gitignore', '.audit/\nnative/Output/\n__pycache__/\nCredentials*.json\n')
        self.write('.audit/private.vwx', '')
        self.write('CredentialsPrivate.json', 'private-data-not-printed')
        (self.root / 'native/Output/unused').mkdir(parents=True)
        (self.root / '__pycache__').mkdir()
        self.assertEqual(self.errors(), [])

    def test_deleted_tracked_file_is_skipped_but_a_reference_to_it_is_not(self):
        gone = self.write('gone.md', 'Old content\n')
        self.git('add', 'gone.md')
        gone.unlink()
        self.assertEqual(self.errors(), [])
        self.write('README.md', '[gone](gone.md)\n')
        self.assertTrue(any('missing Markdown target gone.md' in error for error in self.errors()))

    def test_ignored_file_is_not_a_valid_published_link_target(self):
        self.write('.gitignore', 'private.md\n')
        self.write('private.md', 'Not public\n')
        self.write('README.md', '[private](private.md)\n')
        self.assertTrue(any('target is not publishable: private.md' in error for error in self.errors()))

    def test_private_credentials_and_binaries_report_paths_without_contents(self):
        self.write('native/CredentialsVwxMcp.example.json', '{"developer":"EXAMPLE"}\n')
        secret = 'private-string-that-must-not-be-printed'
        self.write('native/CredentialsActual.json', secret)
        self.write('drawing.vwx', 'binary drawing placeholder')
        self.write('archive.zip', 'archive placeholder')
        self.write('plugin.vlb', 'compiled plugin placeholder')
        errors = self.errors()
        self.assertEqual(len(errors), 4)
        self.assertTrue(any('CredentialsActual.json:' in error for error in errors))
        self.assertFalse(any('example.json:' in error or secret in error for error in errors))

    def test_tracked_files_remain_checked_even_after_added_to_gitignore(self):
        self.write('drawing.vwx', 'drawing')
        self.git('add', 'drawing.vwx')
        self.write('.gitignore', '*.vwx\n')
        self.assertTrue(any('drawing.vwx:' in error for error in self.errors()))

    def test_outside_markdown_target_is_refused_even_when_file_exists(self):
        self.write('README.md', '[outside](../somewhere.md)\n')
        self.assertTrue(any('outside-repository' in error for error in self.errors()))

    def test_root_directory_link_is_valid_but_ignored_directory_and_drive_link_are_not(self):
        self.write('.gitignore', '.audit/\n')
        self.write('.audit/result.json', '{}\n')
        self.write('docs/README.md', '[root](../)\n[private](../.audit/)\n[local](C:/private/file.md)\n')
        errors = self.errors()
        self.assertEqual(len(errors), 2)
        self.assertTrue(any(':2:' in error and 'not publishable' in error for error in errors))
        self.assertTrue(any(':3:' in error and 'nonportable' in error for error in errors))

    def test_reparse_directory_is_never_read_or_traversed(self):
        self.write('linked/secret.md', 'private')
        original_reparse = CHECK._reparse
        original_read = Path.read_bytes
        def reparse(path):
            return path == self.root / 'linked' or original_reparse(path)
        def read(path):
            if 'linked' in path.parts:
                self.fail('Checker traversed a reparse directory')
            return original_read(path)
        with patch.object(CHECK, '_reparse', side_effect=reparse), patch.object(Path, 'read_bytes', new=read):
            errors = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn('linked/secret.md: cannot safely inspect', errors[0])

    def test_real_symlink_is_never_followed(self):
        self.write('target.md', 'Safe content\n')
        link = self.root / 'alias.md'
        try:
            os.symlink(self.root / 'target.md', link)
        except (OSError, NotImplementedError):
            self.skipTest('Creating symlinks is unavailable on this host')
        self.assertTrue(any('alias.md: cannot safely inspect' in error for error in self.errors()))


if __name__ == '__main__':
    unittest.main()
