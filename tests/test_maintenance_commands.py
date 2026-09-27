"""Offline lease, inventory and durable no-replay checks for maintenance.

Only the command's AST is evaluated. No Vectorworks module is imported and no
real app/file inventory is inspected: all native helpers and the plug-in path
are isolated doubles. Receipt assertions are independent of command internals.
"""
import ast
import builtins
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'ab' * 32
DIGEST = hashlib.sha256(TOKEN.encode('ascii')).hexdigest()
PID = 4242
DRAWING = r'C:\Drawings\Disposable Model.vwx'
NORMAL_PATH = r'c:\drawings\disposable model.vwx'


class MaintenanceCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((ROOT / 'vwx-plugin/commands.py').read_text(encoding='utf-8'))
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == 'bridge_maintenance']
        if len(nodes) != 1:
            raise AssertionError('Expected exactly one bridge_maintenance command')
        cls.code = compile(ast.Module(body=nodes, type_ignores=[]), '<maintenance command>', 'exec')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='vwx-maintenance-command-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.prefix = self.base / ('bridge.maintenance.' + DIGEST)
        self.lease = {'schema_version': 1, 'token_sha256': DIGEST, 'host_process_id': PID}
        self.inventory = {'status': 'ok', 'process_id': PID, 'count': 1,
                          'open_documents': [{'file_ref': 1, 'path': DRAWING,
                                              'active': True, 'in_memory_only': False}]}
        self.vs = SimpleNamespace(VWXMaintRevision=Mock(return_value=1),
                                  VWXMaintSnapshot=Mock(side_effect=lambda: json.dumps(self.inventory)),
                                  VWXMaintSave=Mock(return_value=1), VWXMaintQuit=Mock(return_value=1))
        self.fake_os = SimpleNamespace(path=os.path, getpid=Mock(return_value=PID),
                                       fsync=Mock(wraps=os.fsync))
        self.ns = {'vs': self.vs, 'os': self.fake_os, 'json': json, 're': re,
                   '__file__': str(self.base / 'commands.py')}
        exec(self.code, self.ns)
        self.write_lease()

    def write_lease(self):
        (self.base / 'bridge.maintenance.json').write_text(json.dumps(self.lease), encoding='utf-8')

    def path(self, suffix):
        return Path(str(self.prefix) + suffix)

    def receipt(self):
        return {'process_id': PID, 'path': NORMAL_PATH, 'file_ref': 1}

    def invoke(self, action='status', **values):
        envelope = {'action': action, 'token': TOKEN}
        if action != 'status':
            envelope['expected_path'] = DRAWING
        envelope.update(values)
        return self.ns['bridge_maintenance'](envelope)

    def assert_unsubmitted(self, response, code=None):
        self.assertEqual(response.get('status'), 'error', response)
        self.assertIn('error', response)
        self.assertIs(response['dispatched'], False)
        if code:
            self.assertEqual(response['code'], code, response)
        self.vs.VWXMaintSave.assert_not_called()
        self.vs.VWXMaintQuit.assert_not_called()

    def assert_no_mutation_files(self):
        self.assertEqual([path.name for path in self.base.iterdir()], ['bridge.maintenance.json'])

    def test_status_is_read_only_and_reports_current_valid_inventory_and_revision(self):
        response = self.invoke()
        self.assertEqual(response, dict(self.inventory, helper_revision=1))
        self.vs.VWXMaintRevision.assert_called_once_with()
        self.vs.VWXMaintSnapshot.assert_called_once_with()
        self.vs.VWXMaintSave.assert_not_called()
        self.vs.VWXMaintQuit.assert_not_called()
        self.fake_os.fsync.assert_not_called()
        self.assert_no_mutation_files()

    def test_status_can_describe_extra_or_unsaved_documents_without_mutating(self):
        self.inventory['open_documents'].append({'file_ref': 3, 'path': '',
                                                 'active': False, 'in_memory_only': True})
        self.inventory['count'] = 2
        response = self.invoke()
        self.assertEqual(response.get('status'), 'ok', response)
        self.assertEqual(response['open_documents'], self.inventory['open_documents'])
        self.vs.VWXMaintSave.assert_not_called()
        self.vs.VWXMaintQuit.assert_not_called()
        self.assert_no_mutation_files()

    def test_invalid_envelopes_never_read_native_inventory(self):
        bad = [None, [], 'status', {}, {'action': 'status'},
               {'action': 'save', 'token': TOKEN, 'force': True},
               {'action': 'restart', 'token': TOKEN}, {'action': [], 'token': TOKEN}]
        for token in (None, True, 3, '', 'a'*63, 'a'*65, TOKEN.upper(), 'g'*64, '../'*22):
            bad.append({'action': 'status', 'token': token})
        for envelope in bad:
            with self.subTest(envelope=envelope):
                self.assert_unsubmitted(self.ns['bridge_maintenance'](envelope))
        self.vs.VWXMaintRevision.assert_not_called()
        self.vs.VWXMaintSnapshot.assert_not_called()
        self.assert_no_mutation_files()

    def test_lease_token_requires_exact_schema_hash_and_ownership(self):
        bad = [None, [], {}, {'schema_version': True, 'token_sha256': DIGEST},
               {'schema_version': 1.0, 'token_sha256': DIGEST},
               {'schema_version': 2, 'token_sha256': DIGEST},
               {'schema_version': 1, 'token_sha256': None},
               {'schema_version': 1, 'token_sha256': '0'*64},
               {'schema_version': 1, 'token_sha256': DIGEST.upper()}]
        for lease in bad:
            with self.subTest(lease=lease):
                self.lease = lease
                self.write_lease()
                self.assert_unsubmitted(self.invoke(), 'VWX_MAINTENANCE_LEASE')
        self.vs.VWXMaintRevision.assert_not_called()
        self.vs.VWXMaintSnapshot.assert_not_called()

    def test_missing_or_malformed_lease_never_contacts_native_helpers(self):
        path = self.base / 'bridge.maintenance.json'
        for source in ('{broken', '', '{"schema_version":'):
            path.write_text(source, encoding='utf-8')
            self.assert_unsubmitted(self.invoke())
        path.unlink()
        self.assert_unsubmitted(self.invoke())
        self.vs.VWXMaintRevision.assert_not_called()

    def test_private_abi_requires_callable_helpers_and_exact_integer_revision(self):
        for name in ('VWXMaintRevision', 'VWXMaintSnapshot'):
            original = getattr(self.vs, name)
            for value in (None, 1, 'function'):
                setattr(self.vs, name, value)
                self.assert_unsubmitted(self.invoke(), 'VWX_MAINTENANCE_UNSUPPORTED')
            setattr(self.vs, name, original)
        for value in (None, True, False, 1.0, '1', 0, 2, -1, [], {}):
            self.vs.VWXMaintRevision.return_value = value
            self.assert_unsubmitted(self.invoke(), 'VWX_MAINTENANCE_UNSUPPORTED')
        self.vs.VWXMaintSnapshot.assert_not_called()

    def test_native_snapshot_errors_and_malformed_json_are_not_inventory_success(self):
        self.vs.VWXMaintSnapshot.side_effect = None
        values = [None, [], {}, 3, '{bad json', '', 'null', '[]', '"ok"',
                  json.dumps({'status': 'error', 'code': -1}),
                  json.dumps(dict(self.inventory, status='error'))]
        for value in values:
            with self.subTest(value=value):
                self.vs.VWXMaintSnapshot.return_value = value
                self.assert_unsubmitted(self.invoke())
        self.assert_no_mutation_files()

    def test_snapshot_count_process_and_container_types_are_validated(self):
        for field, value in [('process_id', PID+1), ('process_id', float(PID)),
                             ('process_id', True), ('process_id', None),
                             ('count', True), ('count', 1.0), ('count', -1), ('count', 2),
                             ('open_documents', None), ('open_documents', {}),
                             ('status', True), ('status', 'OK')]:
            with self.subTest(field=field, value=value):
                original = self.inventory[field]
                self.inventory[field] = value
                self.assert_unsubmitted(self.invoke(), 'VWX_MAINTENANCE_RESULT')
                self.inventory[field] = original

    def test_save_requires_exact_absolute_vwx_path(self):
        for path in (None, '', True, 3, 'relative.vwx', r'C:relative.vwx',
                     r'C:\Drawings\Other.vwx', r'C:\Drawings\bad.txt', DRAWING+'\x00'):
            with self.subTest(path=path):
                self.assert_unsubmitted(self.invoke('save', expected_path=path))
        self.assert_no_mutation_files()

    def test_save_requires_sole_active_saved_document_and_exact_reference_type(self):
        baseline = copy.deepcopy(self.inventory)
        cases = [([], 'VWX_MAINTENANCE_DOCUMENT'), ([None], 'VWX_MAINTENANCE_RESULT'),
                 ([dict(baseline['open_documents'][0]), dict(baseline['open_documents'][0])],
                  'VWX_MAINTENANCE_DOCUMENT')]
        for field, value in [('active', False), ('active', 1), ('in_memory_only', True),
                             ('in_memory_only', 0), ('file_ref', True), ('file_ref', 1.0),
                             ('file_ref', None), ('path', ''), ('path', None),
                             ('path', r'C:\Drawings\Other.vwx')]:
            altered = copy.deepcopy(baseline['open_documents'][0])
            altered[field] = value
            malformed = ((field in ('active', 'in_memory_only') and type(value) is not bool)
                         or (field == 'file_ref' and type(value) is not int)
                         or (field == 'path' and type(value) is not str))
            cases.append(([altered], 'VWX_MAINTENANCE_RESULT' if malformed else 'VWX_MAINTENANCE_DOCUMENT'))
        for documents, code in cases:
            with self.subTest(documents=documents):
                self.inventory['open_documents'] = documents
                self.inventory['count'] = len(documents)
                self.assert_unsubmitted(self.invoke('save'), code)
        self.assert_no_mutation_files()

    def test_status_does_not_present_malformed_document_rows_as_valid_inventory(self):
        for document in (None, [], {}, {'file_ref': True, 'path': DRAWING, 'active': True,
                                        'in_memory_only': False}):
            with self.subTest(document=document):
                self.inventory['open_documents'] = [document]
                self.assert_unsubmitted(self.invoke(), 'VWX_MAINTENANCE_RESULT')
        self.assert_no_mutation_files()

    def test_lease_pid_pins_mutations_to_original_host(self):
        for value in (PID+1, float(PID), True, None, str(PID)):
            with self.subTest(pid=value):
                self.lease['host_process_id'] = value
                self.write_lease()
                self.assert_unsubmitted(self.invoke('save'), 'VWX_MAINTENANCE_DOCUMENT')
        self.assert_no_mutation_files()

    def test_missing_save_helper_does_not_consume_intent(self):
        self.vs.VWXMaintSave = None
        response = self.invoke('save')
        self.assertEqual(response['code'], 'VWX_MAINTENANCE_UNSUPPORTED')
        self.assertIs(response['dispatched'], False)
        self.vs.VWXMaintQuit.assert_not_called()
        self.assert_no_mutation_files()

    def test_save_persists_fsynced_intent_before_exact_once_native_call_then_receipt(self):
        def save(path):
            self.assertEqual(path, DRAWING)
            self.assertEqual(json.loads(self.path('.save.intent.json').read_text()), self.receipt())
            self.assertFalse(self.path('.saved.json').exists())
            self.assertEqual(self.fake_os.fsync.call_count, 1)
            return 1
        self.vs.VWXMaintSave.side_effect = save
        response = self.invoke('save')
        self.assertEqual(response, {'status': 'ok', 'action': 'save', 'process_id': PID,
                                    'path': DRAWING, 'dispatched': True,
                                    'exit_confirmed': False, 'native_status': 1})
        self.vs.VWXMaintSave.assert_called_once_with(DRAWING)
        self.vs.VWXMaintQuit.assert_not_called()
        self.assertEqual(json.loads(self.path('.saved.json').read_text()), self.receipt())
        self.assertEqual(self.fake_os.fsync.call_count, 2)
        self.assertNotIn(TOKEN, repr(response))
        self.assertNotIn(TOKEN, self.path('.save.intent.json').read_text())

    def test_path_comparison_normalizes_case_and_separators_but_passes_exact_original(self):
        path = 'C:/DRAWINGS/./Disposable Model.VWX'
        response = self.invoke('save', expected_path=path)
        self.assertEqual(response.get('status'), 'ok', response)
        self.vs.VWXMaintSave.assert_called_once_with(path)
        self.assertEqual(json.loads(self.path('.saved.json').read_text())['path'], NORMAL_PATH)

    def test_native_save_nonacceptance_never_creates_confirmed_receipt(self):
        for index, value in enumerate((0, -1, -2, -4, 2, True, False, 1.0, '1', None, [], {})):
            with self.subTest(value=value):
                # A fresh token models independent authorized attempts, never
                # deletion/reuse of the consumed token under test.
                token = format(index+1, '064x')
                digest = hashlib.sha256(token.encode()).hexdigest()
                self.lease['token_sha256'] = digest
                self.write_lease()
                self.vs.VWXMaintSave.return_value = value
                response = self.invoke('save', token=token)
                self.assertEqual(response['code'], 'VWX_MAINTENANCE_NATIVE', response)
                self.assertIs(response['dispatched'], True)
                prefix = self.base / ('bridge.maintenance.'+digest)
                self.assertTrue(Path(str(prefix)+'.save.intent.json').exists())
                self.assertFalse(Path(str(prefix)+'.saved.json').exists())
        self.assertEqual(self.vs.VWXMaintSave.call_count, 12)
        self.vs.VWXMaintQuit.assert_not_called()

    def test_save_and_quit_each_consume_intent_once_without_automatic_replay(self):
        self.assertEqual(self.invoke('save')['status'], 'ok')
        repeated = self.invoke('save')
        self.assertEqual(repeated['code'], 'VWX_MAINTENANCE_CONSUMED')
        self.assertIs(repeated['dispatched'], False)
        self.vs.VWXMaintSave.assert_called_once()
        first_quit = self.invoke('quit')
        self.assertEqual(first_quit['status'], 'ok', first_quit)
        self.assertIs(first_quit['exit_confirmed'], False)
        self.assertEqual(json.loads(self.path('.quit.intent.json').read_text()), self.receipt())
        repeated = self.invoke('quit')
        self.assertEqual(repeated['code'], 'VWX_MAINTENANCE_CONSUMED')
        self.assertIs(repeated['dispatched'], False)
        self.vs.VWXMaintQuit.assert_called_once_with(DRAWING)

    def test_native_exception_preserves_durable_consumed_intent_and_no_save_receipt(self):
        self.vs.VWXMaintSave.side_effect = RuntimeError('unknown after native save attempt')
        response = self.invoke('save')
        self.assertEqual(response['code'], 'VWX_MAINTENANCE_UNCONFIRMED')
        self.assertIs(response['dispatched'], True)
        self.assertTrue(self.path('.save.intent.json').exists())
        self.assertFalse(self.path('.saved.json').exists())
        self.vs.VWXMaintSave.side_effect = None
        repeated = self.invoke('save')
        self.assertEqual(repeated['code'], 'VWX_MAINTENANCE_CONSUMED')
        self.assertIs(repeated['dispatched'], False)
        self.vs.VWXMaintSave.assert_called_once()
        denied_quit = self.invoke('quit')
        self.assertIs(denied_quit['dispatched'], False)
        self.vs.VWXMaintQuit.assert_not_called()

    def test_fsync_failure_before_dispatch_preserves_intent_and_prevents_retry(self):
        self.fake_os.fsync.side_effect = OSError('cannot durably flush intent')
        self.assert_unsubmitted(self.invoke('save'))
        self.assertTrue(self.path('.save.intent.json').exists())
        self.fake_os.fsync.side_effect = None
        self.assert_unsubmitted(self.invoke('save'), 'VWX_MAINTENANCE_CONSUMED')
        self.assertFalse(self.path('.saved.json').exists())

    def test_receipt_write_failure_after_native_save_stays_dispatched_unconfirmed(self):
        def opened(path, mode='r', *args, **kwargs):
            if str(path).endswith('.saved.json') and mode == 'x':
                raise OSError('receipt unavailable')
            return builtins.open(path, mode, *args, **kwargs)
        self.ns['open'] = opened
        response = self.invoke('save')
        self.assertEqual(response['code'], 'VWX_MAINTENANCE_UNCONFIRMED')
        self.assertIs(response['dispatched'], True)
        self.assertTrue(self.path('.save.intent.json').exists())
        self.assertFalse(self.path('.saved.json').exists())
        self.vs.VWXMaintSave.assert_called_once()
        self.assertEqual(self.invoke('save')['code'], 'VWX_MAINTENANCE_CONSUMED')
        self.vs.VWXMaintSave.assert_called_once()

    def test_quit_without_confirmed_save_or_with_malformed_receipt_never_dispatches(self):
        self.assert_unsubmitted(self.invoke('quit'))
        bad = [None, [], {}, {'process_id': PID, 'path': NORMAL_PATH},
               dict(self.receipt(), process_id=PID+1), dict(self.receipt(), process_id=float(PID)),
               dict(self.receipt(), file_ref=True), dict(self.receipt(), file_ref=1.0),
               dict(self.receipt(), file_ref=2), dict(self.receipt(), path=r'c:\drawings\other.vwx'),
               dict(self.receipt(), unexpected=True)]
        for saved in bad:
            with self.subTest(saved=saved):
                self.path('.saved.json').write_text(json.dumps(saved), encoding='utf-8')
                self.assert_unsubmitted(self.invoke('quit'))
                self.assertFalse(self.path('.quit.intent.json').exists())
        self.path('.saved.json').write_text('{broken', encoding='utf-8')
        self.assert_unsubmitted(self.invoke('quit'))

    def test_quit_rechecks_inventory_and_rejects_changed_reference_path_or_pid(self):
        self.assertEqual(self.invoke('save')['status'], 'ok')
        self.vs.VWXMaintSave.reset_mock()
        baseline = copy.deepcopy(self.inventory)
        mutations = [('file_ref', 2), ('path', r'C:\Drawings\Renamed.vwx'), ('active', False),
                     ('in_memory_only', True)]
        for field, value in mutations:
            with self.subTest(field=field):
                self.inventory = copy.deepcopy(baseline)
                self.inventory['open_documents'][0][field] = value
                expected = value if field == 'path' else DRAWING
                self.assert_unsubmitted(self.invoke('quit', expected_path=expected))
        self.inventory = copy.deepcopy(baseline)
        self.inventory['process_id'] = PID+1
        self.assert_unsubmitted(self.invoke('quit'))
        self.fake_os.getpid.return_value = PID+1
        self.assert_unsubmitted(self.invoke('quit'))
        self.inventory = copy.deepcopy(baseline)
        self.fake_os.getpid.return_value = PID
        self.inventory['open_documents'].append(dict(baseline['open_documents'][0], file_ref=2))
        self.inventory['count'] = 2
        self.assert_unsubmitted(self.invoke('quit'))
        self.assertFalse(self.path('.quit.intent.json').exists())

    def test_quit_error_or_exception_consumes_intent_without_claiming_process_exit(self):
        self.assertEqual(self.invoke('save')['status'], 'ok')
        self.vs.VWXMaintQuit.side_effect = RuntimeError('quit request outcome unknown')
        response = self.invoke('quit')
        self.assertEqual(response['code'], 'VWX_MAINTENANCE_UNCONFIRMED')
        self.assertIs(response['dispatched'], True)
        self.assertNotIn('exit_confirmed', response)
        self.assertTrue(self.path('.quit.intent.json').exists())
        repeated = self.invoke('quit')
        self.assertEqual(repeated['code'], 'VWX_MAINTENANCE_CONSUMED')
        self.assertIs(repeated['dispatched'], False)
        self.vs.VWXMaintQuit.assert_called_once_with(DRAWING)

    def test_native_read_failures_cannot_consume_mutation_intents(self):
        for name in ('VWXMaintRevision', 'VWXMaintSnapshot'):
            helper = getattr(self.vs, name)
            prior = helper.side_effect
            helper.side_effect = RuntimeError('native read failed')
            self.assert_unsubmitted(self.invoke('save'))
            helper.side_effect = prior
        self.assert_no_mutation_files()


if __name__ == '__main__':
    unittest.main()
