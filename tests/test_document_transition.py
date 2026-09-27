"""Offline publication races, no-replay records and independent document checks."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import test_bridge_maintenance as lease_tests


ROOT = Path(__file__).resolve().parents[1]
MAINT = lease_tests.MAINT
TOKEN = 'cd' * 32
DIGEST = hashlib.sha256(TOKEN.encode('ascii')).hexdigest()
SOURCE = r'c:\drawings\resident - a.vwx'
TARGET = r'c:\drawings\resident - b.vwx'
PID = 2468


class TransitionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = lease_tests.BridgeMaintenanceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.base = self.fixture.base
        MAINT.acquire(self.base, TOKEN)
        self.lease = json.loads((self.base / MAINT.LEASE_FILE).read_text())
        self.before = [self.doc(SOURCE, 2, True)]
        self.inventory = dict(status='ok', process_id=PID, count=1, open_documents=self.before,
                              helper_revision=1)
        self.native = dict(schema_version=1, process_id=PID, request_id=DIGEST, phase='completed',
                           source_path=SOURCE, target_path=TARGET, code=1, dispatched=True,
                           save_confirmed=True, transition_dispatched=True, source_ref=2, target_ref=9)
        self.vs = SimpleNamespace(VWXDocRevision=Mock(return_value=1), VWXDocStage=Mock(return_value=1),
                                  VWXDocStatus=Mock(side_effect=lambda: json.dumps(self.native)))
        tree = ast.parse((ROOT / 'vwx-plugin/commands.py').read_text(encoding='utf-8'))
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == '_bridge_document_transition']
        fake_os = SimpleNamespace(path=os.path, fsync=os.fsync, getpid=lambda: PID)
        self.ns = dict(vs=self.vs, os=fake_os, json=json, re=re,
                       _native_document_inventory=lambda: copy.deepcopy(self.inventory))
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<transition>', 'exec'), self.ns)

    @staticmethod
    def doc(path, ref, active):
        return dict(path=path, file_ref=ref, active=active, in_memory_only=False)

    def file(self, suffix):
        return self.base / ('bridge.maintenance.' + DIGEST + '.transition.' + suffix + '.json')

    def publish(self, **changes):
        params = dict(action='transition', token=TOKEN, expected_path=SOURCE, target_path=TARGET)
        params.update(changes)
        with MAINT.publication_guard(self.base, 'bridge_maintenance', params, 'abcd01234567'):
            return self.file('intent').read_bytes()

    def invoke(self, action='transition', **changes):
        params = dict(action=action, token=TOKEN, expected_path=SOURCE, target_path=TARGET)
        params.update(changes)
        return self.ns['_bridge_document_transition'](params, self.lease, DIGEST, str(self.base))

    def complete(self):
        self.inventory.update(count=2, open_documents=[self.doc(SOURCE, 2, False), self.doc(TARGET, 9, True)])

    def test_publication_intent_precedes_queue_and_blocks_early_release(self):
        self.publish()
        self.assertFalse(self.file('dispatch').exists())
        with self.assertRaises(MAINT.MaintenanceError) as caught:
            MAINT.release(self.base, TOKEN)
        self.assertEqual(caught.exception.code, 'VWX_DOCUMENT_TRANSITION_PENDING')
        self.assertTrue((self.base / MAINT.LEASE_FILE).exists())

    def test_server_never_republishes_same_transition_even_before_native_dispatch(self):
        first = self.publish()
        with self.assertRaises(MAINT.MaintenanceError) as caught:
            self.publish()
        self.assertEqual(caught.exception.code, 'VWX_DOCUMENT_TRANSITION_CONSUMED')
        self.assertEqual(self.file('intent').read_bytes(), first)

    def test_paths_are_exact_distinct_saved_windows_paths_before_any_intent(self):
        for path in ('relative.vwx', r'C:relative.vwx', r'\relative.vwx', SOURCE,
                     r'C:\a\..\b.vwx', r'C:\a\b.vwx:stream', r'\\?\C:\b.vwx',
                     r'C:\b.vwxw', '', SOURCE+'\x00', None, True):
            with self.subTest(path=path), self.assertRaises(MAINT.MaintenanceError):
                self.publish(target_path=path)
            self.assertFalse(self.file('intent').exists())

    def test_foreign_host_or_busy_runner_cannot_publish_transition(self):
        for changes in ({'process_id': PID+1}, {'menu_invocation_active': True}, {'pending': True}):
            with self.subTest(changes=changes):
                self.fixture.refresh(**changes)
                with self.assertRaises(MAINT.MaintenanceError):
                    self.publish()
                self.assertFalse(self.file('intent').exists())

    def test_save_or_quit_cannot_compete_with_staged_transition(self):
        self.publish()
        for action in ('save', 'quit'):
            with self.assertRaises(MAINT.MaintenanceError) as caught:
                with MAINT.publication_guard(self.base, 'bridge_maintenance',
                        {'action': action, 'token': TOKEN, 'expected_path': SOURCE}, 'abcd01234567'):
                    self.fail('A conflicting mutation was published')
            self.assertEqual(caught.exception.code, 'VWX_DOCUMENT_TRANSITION_PENDING')

    def test_stage_requires_durable_intent_before_entering_private_callback(self):
        self.assertEqual(self.invoke()['status'], 'error')
        self.vs.VWXDocStage.assert_not_called()
        self.publish()
        def stage(source, target, request):
            record = json.loads(self.file('dispatch').read_text())
            self.assertEqual(record['before'], self.before)
            self.assertEqual(record['intent']['request_id'], request)
            self.assertEqual((source, target), (SOURCE, TARGET))
            return 1
        self.vs.VWXDocStage.side_effect = stage
        result = self.invoke()
        self.assertEqual(result['phase'], 'staged')
        self.assertIs(result['completed'], False)
        self.assertFalse(self.file('confirmed').exists())
        self.assertEqual(self.invoke()['code'], 'VWX_DOCUMENT_TRANSITION_CONSUMED')
        self.vs.VWXDocStage.assert_called_once()

    def test_stage_refuses_changed_source_unsaved_documents_and_path_mismatch(self):
        self.publish()
        initial = copy.deepcopy(self.inventory)
        for doc in (self.doc(TARGET, 2, True), dict(self.before[0], active=False),
                    dict(self.before[0], in_memory_only=True)):
            self.inventory['open_documents'] = [doc]
            self.assertEqual(self.invoke()['status'], 'error')
            self.assertFalse(self.file('dispatch').exists())
        self.inventory = initial
        self.assertEqual(self.invoke(target_path=r'C:\other.vwx')['status'], 'error')
        self.vs.VWXDocStage.assert_not_called()

    def test_missing_or_wrong_abi_does_not_consume_native_dispatch(self):
        self.publish()
        for value in (None, True, '1', 1.0, 2, -1):
            self.vs.VWXDocRevision.return_value = value
            self.assertEqual(self.invoke()['code'], 'VWX_DOCUMENT_TRANSITION_UNSUPPORTED')
        self.assertFalse(self.file('dispatch').exists())
        self.vs.VWXDocStage.assert_not_called()

    def test_lost_native_response_consumes_attempt_and_preserves_lease(self):
        self.publish()
        self.vs.VWXDocStage.side_effect = RuntimeError('response lost')
        result = self.invoke()
        self.assertEqual(result['code'], 'VWX_DOCUMENT_TRANSITION_UNCONFIRMED')
        self.assertIs(result['dispatched'], True)
        self.assertEqual(self.invoke()['code'], 'VWX_DOCUMENT_TRANSITION_CONSUMED')
        self.vs.VWXDocStage.assert_called_once()
        with self.assertRaises(MAINT.MaintenanceError):
            MAINT.release(self.base, TOKEN)

    def test_completed_native_status_alone_cannot_release_or_confirm_wrong_inventory(self):
        self.publish()
        self.invoke()
        status = self.invoke('transition_status')
        self.assertIs(status['confirmed'], False)
        self.assertEqual(self.invoke('transition_confirm')['code'], 'VWX_DOCUMENT_TRANSITION_IDENTITY')
        self.assertFalse(self.file('confirmed').exists())

    def test_confirmation_checks_every_preserved_document_and_active_target(self):
        self.before.append(self.doc(r'c:\drawings\other.vwx', 3, False))
        self.inventory['count'] = 2
        self.publish()
        self.invoke()
        expected = [self.doc(SOURCE, 2, False), self.doc(r'c:\drawings\other.vwx', 3, False),
                    self.doc(TARGET, 9, True)]
        for rows in (expected[1:], [expected[0], expected[2]],
                     [dict(expected[0], file_ref=5), *expected[1:]],
                     [*expected, self.doc(r'c:\extra.vwx', 20, False)],
                     [dict(expected[0], active=True), expected[1], dict(expected[2], active=False)]):
            with self.subTest(rows=rows):
                self.inventory.update(count=len(rows), open_documents=rows)
                self.assertEqual(self.invoke('transition_confirm')['status'], 'error')
                self.assertFalse(self.file('confirmed').exists())
        self.inventory.update(count=3, open_documents=expected)
        self.assertIs(self.invoke('transition_confirm')['confirmed'], True)
        self.assertIs(self.invoke('transition_confirm')['confirmed'], True, 'Independent read-only confirmation may repeat')
        self.fixture.refresh()
        self.assertIs(MAINT.release(self.base, TOKEN)['active'], False)

    def test_malformed_or_wrong_native_identity_and_uncertain_outcomes_never_confirm(self):
        self.publish()
        self.invoke()
        self.complete()
        original = copy.deepcopy(self.native)
        for field, value in (('schema_version', True), ('process_id', PID+1), ('process_id', True),
                             ('request_id', 'a'*64), ('source_path', TARGET), ('target_path', SOURCE),
                             ('phase', 'executing'), ('phase', 'uncertain'), ('phase', 'failed'),
                             ('code', True), ('code', -1), ('dispatched', False), ('dispatched', 1),
                             ('save_confirmed', False), ('transition_dispatched', False),
                             ('source_ref', True), ('source_ref', 8), ('target_ref', 2)):
            with self.subTest(field=field, value=value):
                self.native = dict(original, **{field: value})
                self.assertEqual(self.invoke('transition_confirm')['status'], 'error')
                self.assertFalse(self.file('confirmed').exists())

    def test_release_requires_fresh_idle_same_host_even_with_valid_confirmation(self):
        self.publish()
        self.invoke()
        self.complete()
        self.assertIs(self.invoke('transition_confirm')['confirmed'], True)
        for changes in ({'process_id': PID+1}, {'menu_invocation_active': True}, {'pending': True}):
            self.fixture.refresh(**changes)
            with self.assertRaises(MAINT.MaintenanceError):
                MAINT.release(self.base, TOKEN)
            self.assertTrue((self.base / MAINT.LEASE_FILE).exists())
        self.fixture.refresh()
        self.assertIs(MAINT.release(self.base, TOKEN)['active'], False)

    def test_forged_malformed_or_mismatched_receipts_cannot_release(self):
        self.publish()
        self.invoke()
        self.complete()
        self.invoke('transition_confirm')
        original = json.loads(self.file('confirmed').read_text())
        for changed in ({}, dict(original, schema_version=True), dict(original, intent={}),
                        dict(original, outcome='staged'), dict(original, target_file_ref=True),
                        dict(original, source_file_ref=-1)):
            self.file('confirmed').write_text(json.dumps(changed), encoding='utf-8')
            with self.assertRaises(MAINT.MaintenanceError):
                MAINT.release(self.base, TOKEN)
            self.assertTrue((self.base / MAINT.LEASE_FILE).exists())


if __name__ == '__main__':
    unittest.main()
