"""Offline SDK inventory identity checks; never inspect or control the desktop."""
import ast
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
FIRST = r'C:\Projects\Kimberly 1027 N 390 E - 3D Model v2027.vwx'
SECOND = r'C:\Other Projects\Kimberly 1027 N 390 E - 3D Model v2027.vwx'


def document(path=FIRST, file_ref=7, active=True, in_memory_only=False):
    return dict(path=path, file_ref=file_ref, active=active, in_memory_only=in_memory_only)


def inventory(*documents):
    return dict(status='ok', process_id=os.getpid(), count=len(documents), open_documents=list(documents))


class DocumentInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((ROOT / 'vwx-plugin/commands.py').read_text(encoding='utf-8'))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in {'_native_document_inventory', 'list_documents'}]
        cls.code = compile(ast.Module(body=functions, type_ignores=[]), '<document-inventory>', 'exec')

    def setUp(self):
        self.revision = Mock(return_value=1)
        self.snapshot = Mock(return_value=json.dumps(inventory(document())))
        self.forbidden = Mock(side_effect=AssertionError('No legacy title or desktop fallback'))
        self.vs = SimpleNamespace(VWXMaintRevision=self.revision, VWXMaintSnapshot=self.snapshot,
                                  GetFName=self.forbidden, GetFPathName=self.forbidden)
        self.namespace = dict(vs=self.vs, os=os, json=json, _dokumentfenster=self.forbidden,
                              _win32=self.forbidden, _safe=self.forbidden)
        exec(self.code, self.namespace)

    def call(self, value=None):
        if value is not None:
            self.snapshot.return_value = json.dumps(value)
        return self.namespace['list_documents']({})

    def reject(self, value, code='VWX_DOCUMENT_INVENTORY_INVALID'):
        response = self.call(value)
        self.assertEqual(response['status'], 'error')
        self.assertEqual(response['code'], code)
        self.assertNotIn('count', response)
        self.assertNotIn('anzahl', response)
        self.assertNotIn('open_documents', response)
        self.assertNotIn('dokumente', response)
        self.forbidden.assert_not_called()

    def test_hyphenated_basename_is_not_truncated_or_derived_from_window_title(self):
        response = self.call()
        self.assertEqual(response['status'], 'ok')
        self.assertEqual(response['count'], 1)
        self.assertEqual(response['anzahl'], 1)
        self.assertEqual(response['active_path'], FIRST)
        self.assertEqual(response['active_file_ref'], 7)
        self.assertEqual(response['aktiv'], 'Kimberly 1027 N 390 E - 3D Model v2027.vwx')
        self.assertEqual(response['open_documents'], [document()])
        self.assertEqual(response['dokumente'], [dict(document(), datei=response['aktiv'], aktiv=True)])
        self.assertEqual(response['source'], 'native-sdk-open-files')
        self.assertEqual(response['process_id'], os.getpid())
        self.assertEqual(response['helper_revision'], 1)
        for key in ('hwnd', 'titel', 'aktiv_widerspruch', 'geraten'):
            self.assertNotIn(key, response['dokumente'][0])
        self.revision.assert_called_once_with()
        self.snapshot.assert_called_once_with()
        self.forbidden.assert_not_called()

    def test_unicode_emoji_and_watermark_words_are_exact_filename_content(self):
        path = 'C:\\Projects\\Jardín - 日本庭園 🌳 - WATERMARKED FILE.vwx'
        response = self.call(inventory(document(path)))
        self.assertEqual(response['active_path'], path)
        self.assertEqual(response['aktiv'], 'Jardín - 日本庭園 🌳 - WATERMARKED FILE.vwx')
        self.assertEqual(response['open_documents'][0]['path'], path)

    def test_duplicate_basenames_have_distinct_full_paths_and_native_active_identity(self):
        response = self.call(inventory(document(active=False), document(SECOND, file_ref=11)))
        self.assertEqual(response['count'], 2)
        self.assertEqual(response['active_path'], SECOND)
        self.assertEqual(response['active_file_ref'], 11)
        self.assertEqual([row['aktiv'] for row in response['dokumente']], [False, True])
        self.assertEqual(response['dokumente'][0]['datei'], response['dokumente'][1]['datei'])
        self.assertEqual([row['path'] for row in response['dokumente']], [FIRST, SECOND])

    def test_empty_inventory_stays_empty_without_inventing_the_active_document(self):
        response = self.call(inventory())
        self.assertEqual(response['status'], 'ok')
        self.assertEqual(response['count'], 0)
        self.assertEqual(response['anzahl'], 0)
        self.assertEqual(response['open_documents'], [])
        self.assertEqual(response['dokumente'], [])
        self.assertEqual(response['active_path'], '')
        self.assertEqual(response['aktiv'], '')
        self.assertIsNone(response['active_file_ref'])
        self.forbidden.assert_not_called()

    def test_multiple_unsaved_documents_can_have_empty_paths_but_distinct_references(self):
        docs = [document('', file_ref=0, active=False, in_memory_only=True),
                document('', file_ref=8, in_memory_only=True)]
        response = self.call(inventory(*docs))
        self.assertEqual(response['status'], 'ok')
        self.assertEqual(response['count'], 2)
        self.assertEqual(response['active_file_ref'], 8)
        self.assertEqual(response['active_path'], '')
        self.assertEqual(response['open_documents'], docs)
        self.assertEqual([row['datei'] for row in response['dokumente']], ['', ''])
        self.assertTrue(all(row['in_memory_only'] for row in response['open_documents']))

    def test_unsaved_native_file_identifier_and_unc_paths_are_preserved(self):
        for path, memory_only in ((r'C:\Temporary\Unnamed.vwx', True),
                                  (r'\\server\share\Garden - East.vwx', False),
                                  ('C:/Projects/Garden.vwt', False)):
            with self.subTest(path=path):
                response = self.call(inventory(document(path, in_memory_only=memory_only)))
                self.assertEqual(response['status'], 'ok')
                self.assertEqual(response['active_path'], path)
                self.assertEqual(response['open_documents'][0]['in_memory_only'], memory_only)

    def test_missing_or_noncallable_helpers_fail_without_title_fallback(self):
        for name in ('VWXMaintRevision', 'VWXMaintSnapshot'):
            for missing in (True, False):
                with self.subTest(name=name, missing=missing):
                    original = getattr(self.vs, name)
                    if missing:
                        delattr(self.vs, name)
                    else:
                        setattr(self.vs, name, 1)
                    self.reject(inventory(document()), 'VWX_DOCUMENT_INVENTORY_UNAVAILABLE')
                    setattr(self.vs, name, original)
        self.snapshot.assert_not_called()
        self.revision.assert_not_called()

    def test_revision_requires_integer_one_and_precedes_snapshot(self):
        for value in (True, False, 1.0, '1', None, 0, -1, 2):
            with self.subTest(revision=value):
                self.revision.return_value = value
                self.reject(inventory(document()), 'VWX_DOCUMENT_INVENTORY_UNAVAILABLE')
        self.snapshot.assert_not_called()

    def test_helper_exceptions_do_not_trigger_retries_or_fallback(self):
        self.revision.side_effect = RuntimeError('no UI context')
        self.reject(inventory(document()))
        self.revision.assert_called_once_with()
        self.snapshot.assert_not_called()
        self.revision.side_effect = None
        self.snapshot.side_effect = RuntimeError('inventory unavailable')
        self.reject(inventory(document()))
        self.snapshot.assert_called_once_with()

    def test_raw_nontext_invalid_json_and_duplicate_fields_are_rejected(self):
        raw_values = [None, True, 1, {}, [], '{', 'null', '[]', 'false',
                      '{"status":"error","process_id":%d,"code":-103}' % os.getpid(),
                      json.dumps(inventory(document()))[:-1] + ',"count":1}',
                      json.dumps(inventory(document())).replace('"active": true',
                                                                '"active": false,"active": true')]
        for raw in raw_values:
            with self.subTest(raw=raw):
                self.snapshot.return_value = raw
                response = self.call()
                self.assertEqual(response['status'], 'error')
                self.assertEqual(response['code'], 'VWX_DOCUMENT_INVENTORY_INVALID')
                self.assertNotIn('open_documents', response)
        self.forbidden.assert_not_called()

    def test_wrong_process_count_status_and_container_types_are_rejected(self):
        original = inventory(document())
        changes = [dict(process_id=os.getpid() + 1), dict(process_id=True), dict(process_id=0),
                   dict(process_id=float(os.getpid())), dict(process_id=str(os.getpid())),
                   dict(status='error'), dict(status=True), dict(count=0), dict(count=-1),
                   dict(count=True), dict(count=1.0), dict(count='1'), dict(open_documents={}),
                   dict(open_documents=None), dict(count=2)]
        for change in changes:
            with self.subTest(change=change):
                self.reject(dict(original, **change))
        for key in original:
            with self.subTest(missing=key):
                candidate = copy.deepcopy(original)
                del candidate[key]
                self.reject(candidate)

    def test_native_inventory_limit_is_enforced(self):
        docs = [document(r'C:\Tests\%d.vwx' % i, file_ref=i, active=i == 0) for i in range(257)]
        self.assertEqual(self.call(inventory(*docs[:256]))['count'], 256)
        self.reject(inventory(*docs))

    def test_malformed_rows_and_booleans_in_integer_slots_are_rejected(self):
        changes = [dict(path=None), dict(path=True), dict(file_ref=True), dict(file_ref=False),
                   dict(file_ref=-1), dict(file_ref=2147483648), dict(file_ref=7.0), dict(file_ref='7'),
                   dict(active=1), dict(active='true'), dict(in_memory_only=0), dict(in_memory_only=None)]
        for change in changes:
            with self.subTest(change=change):
                self.reject(inventory(dict(document(), **change)))
        for key in document():
            with self.subTest(missing=key):
                row = document()
                del row[key]
                self.reject(inventory(row))
        for row in (None, True, 7, [], 'document'):
            with self.subTest(row=row):
                self.reject(inventory(row))

    def test_missing_saved_path_relative_paths_controls_and_unpaired_surrogates_are_rejected(self):
        paths = ['', 'Garden.vwx', r'C:Garden.vwx', r'\Projects\Garden.vwx',
                 '/Projects/Garden.vwx', 'C:\\', 'C:\\Garden\x00.vwx',
                 'C:\\Garden\n.vwx', 'C:\\Garden\ud800.vwx', 'C:\\Garden\udfff.vwx']
        for path in paths:
            with self.subTest(path=repr(path)):
                self.reject(inventory(document(path)))

    def test_device_paths_alternate_streams_invalid_drives_and_ambiguous_suffixes_are_rejected(self):
        paths = [r'\\?\C:\Garden.vwx', r'\\.\C:\Garden.vwx', r'C:\Garden.vwx:stream',
                 r'1:\Garden.vwx', r'C:\Garden*.vwx', r'C:\Garden?.vwx', r'C:\Garden|.vwx',
                 'C:\\Garden.vwx ', 'C:\\Garden.vwx.', r'C:\Folder.\Garden.vwx']
        for path in paths:
            with self.subTest(path=path):
                self.reject(inventory(document(path)))

    def test_duplicate_references_or_normalized_saved_paths_are_rejected(self):
        self.reject(inventory(document(active=False), document(SECOND)))
        for duplicate in (FIRST, FIRST.upper(), FIRST.replace('\\', '/'),
                          r'C:\Projects\Child\..\Kimberly 1027 N 390 E - 3D Model v2027.vwx'):
            with self.subTest(duplicate=duplicate):
                self.reject(inventory(document(active=False), document(duplicate, file_ref=19)))

    def test_nonempty_inventory_requires_exactly_one_active_document(self):
        self.reject(inventory(document(active=False)))
        self.reject(inventory(document(active=False), document(SECOND, file_ref=13, active=False)))
        self.reject(inventory(document(), document(SECOND, file_ref=13)))


if __name__ == '__main__':
    unittest.main()
