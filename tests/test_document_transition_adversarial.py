"""Independent corruption and prepublication checks for deferred transitions."""
import copy
import json
import unittest

import test_document_transition as transition_fixture


MAINT = transition_fixture.MAINT
TOKEN = transition_fixture.TOKEN
TARGET = transition_fixture.TARGET


class TransitionAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.new_fixture()

    def new_fixture(self):
        self.fixture = transition_fixture.TransitionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def confirmed(self):
        self.fixture.publish()
        self.assertEqual(self.fixture.invoke()['phase'], 'staged')
        self.fixture.complete()
        self.assertIs(self.fixture.invoke('transition_confirm')['confirmed'], True)
        self.fixture.fixture.refresh()
        return json.loads(self.fixture.file('confirmed').read_text(encoding='utf-8'))

    def cannot_release(self):
        with self.assertRaises(MAINT.MaintenanceError):
            MAINT.release(self.fixture.base, TOKEN)
        self.assertTrue((self.fixture.base / MAINT.LEASE_FILE).is_file())

    def test_confirmation_cannot_claim_one_reference_for_two_distinct_paths(self):
        receipt = self.confirmed()
        receipt['source_file_ref'] = receipt['target_file_ref'] = 7
        self.fixture.file('confirmed').write_text(json.dumps(receipt), encoding='utf-8')
        self.cannot_release()

    def test_confirmation_source_reference_must_match_consumed_dispatch(self):
        receipt = self.confirmed()
        receipt['source_file_ref'] = 900
        self.fixture.file('confirmed').write_text(json.dumps(receipt), encoding='utf-8')
        self.cannot_release()

    def test_confirmation_does_not_replace_missing_dispatch_evidence(self):
        self.confirmed()
        self.fixture.file('dispatch').unlink()
        self.cannot_release()

    def test_confirmation_embedded_intent_requires_exact_integer_types(self):
        receipt = self.confirmed()
        for field, value in (('schema_version', True), ('schema_version', 1.0),
                             ('process_id', float(receipt['intent']['process_id']))):
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(receipt)
                changed['intent'][field] = value
                self.fixture.file('confirmed').write_text(json.dumps(changed), encoding='utf-8')
                self.cannot_release()

    def test_dispatch_request_identity_is_rechecked_before_release(self):
        self.confirmed()
        dispatch = json.loads(self.fixture.file('dispatch').read_text(encoding='utf-8'))
        dispatch['intent']['request_id'] = 'e' * 64
        self.fixture.file('dispatch').write_text(json.dumps(dispatch), encoding='utf-8')
        self.cannot_release()

    def test_invalid_unicode_cannot_create_a_partial_publication_intent(self):
        for target in ('C:\\Tests\\Garden\ud800.vwx', 'C:\\Tests\\Garden\udfff.vwx'):
            with self.subTest(target=repr(target)):
                self.new_fixture()
                with self.assertRaises(MAINT.MaintenanceError):
                    self.fixture.publish(target_path=target)
                self.assertFalse(self.fixture.file('intent').exists())

    def test_invalid_drive_and_unc_server_are_rejected_before_publication(self):
        for target in (r'1:\Tests\Garden.vwx', r'\\.\share\Garden.vwx',
                       r'\\server:\share\Garden.vwx', r'\\server\share.\Garden.vwx'):
            with self.subTest(target=target):
                self.new_fixture()
                with self.assertRaises(MAINT.MaintenanceError):
                    self.fixture.publish(target_path=target)
                self.assertFalse(self.fixture.file('intent').exists())

    def test_unicode_emoji_and_real_unc_paths_remain_publishable(self):
        for target in ('C:\\Tests\\庭園 🌳.vwx', r'\\server\share\Garden - B.vwx'):
            with self.subTest(target=target):
                self.new_fixture()
                intent = json.loads(self.fixture.publish(target_path=target))
                self.assertEqual(intent['target_path'], target.lower())

    def test_blank_basename_and_utf16_overlong_path_rejected_before_intent(self):
        for target in ('C:\\.vwx', 'C:\\' + '🌳' * 17000 + '.vwx'):
            with self.subTest(characters=len(target)):
                self.new_fixture()
                with self.assertRaises(MAINT.MaintenanceError):
                    self.fixture.publish(target_path=target)
                self.assertFalse(self.fixture.file('intent').exists())

    def test_existing_target_reference_must_match_dispatch_when_releasing(self):
        self.fixture.before.append(self.fixture.doc(TARGET, 9, False))
        self.fixture.inventory['count'] = 2
        receipt = self.confirmed()
        receipt['target_file_ref'] = 909
        self.fixture.file('confirmed').write_text(json.dumps(receipt), encoding='utf-8')
        self.cannot_release()

    def test_new_target_reference_cannot_collide_with_another_preserved_document(self):
        other = self.fixture.doc(r'c:\drawings\resident - c.vwx', 14, False)
        self.fixture.before.append(other)
        self.fixture.inventory['count'] = 2
        self.fixture.publish()
        self.fixture.invoke()
        self.fixture.complete()
        self.fixture.inventory['open_documents'].append(other)
        self.fixture.inventory['count'] = 3
        self.assertIs(self.fixture.invoke('transition_confirm')['confirmed'], True)
        receipt = json.loads(self.fixture.file('confirmed').read_text(encoding='utf-8'))
        receipt['target_file_ref'] = 14
        self.fixture.file('confirmed').write_text(json.dumps(receipt), encoding='utf-8')
        self.cannot_release()

    def test_dispatch_document_rows_require_complete_unambiguous_saved_source_identity(self):
        self.confirmed()
        original = json.loads(self.fixture.file('dispatch').read_text(encoding='utf-8'))
        source = original['before'][0]
        malformed = [[], [None], [dict(source, file_ref=True)], [dict(source, file_ref=2.0)],
                     [dict(source, file_ref=2147483648)], [dict(source, active=1)],
                     [dict(source, active=False)], [dict(source, in_memory_only=True)],
                     [dict(source, unexpected=1)], [dict(source, path=TARGET)],
                     [source, dict(source, file_ref=16, active=False)],
                     [source, dict(source, path=TARGET, active=False)],
                     [source, dict(source, path=TARGET, file_ref=16, active=True)]]
        for before in malformed:
            with self.subTest(before=before):
                changed = dict(original, before=before)
                self.fixture.file('dispatch').write_text(json.dumps(changed), encoding='utf-8')
                self.cannot_release()

    def test_duplicate_json_evidence_fields_are_rejected(self):
        self.confirmed()
        raw = self.fixture.file('confirmed').read_text(encoding='utf-8')
        self.fixture.file('confirmed').write_text(raw[:-1] + ', "outcome":"completed"}', encoding='utf-8')
        self.cannot_release()

    def test_oversized_dispatch_evidence_is_rejected_before_file_creation_or_native_stage(self):
        path = 'c:\\' + '\\'.join(['庭' * 40] * 8) + '\\drawing_{:03d}.vwx'
        self.fixture.before.extend(self.fixture.doc(path.format(i), i + 10, False) for i in range(253))
        self.fixture.inventory['count'] = len(self.fixture.before)
        self.fixture.publish()
        intent = json.loads(self.fixture.file('intent').read_text(encoding='utf-8'))
        evidence = {'schema_version': 1, 'intent': intent, 'before': self.fixture.before}
        self.assertLessEqual(len(self.fixture.before), 256)
        self.assertGreater(len(json.dumps(evidence, ensure_ascii=False).encode('utf-8')), 262144)
        response = self.fixture.invoke()
        self.assertEqual(response['status'], 'error')
        self.assertIs(response['dispatched'], False)
        self.assertIn('262144', response['error'])
        self.assertFalse(self.fixture.file('dispatch').exists())
        self.fixture.vs.VWXDocStage.assert_not_called()
        self.assertTrue(self.fixture.file('intent').exists(), 'Do not erase the already-published intent')

    def test_dispatch_size_limit_counts_utf8_bytes_instead_of_code_points(self):
        path = 'c:\\' + '\\'.join(['庭' * 40] * 8) + '\\drawing_{:03d}.vwx'
        self.fixture.before.extend(self.fixture.doc(path.format(i), i + 10, False) for i in range(253))
        self.fixture.inventory['count'] = len(self.fixture.before)
        self.fixture.publish()
        intent = json.loads(self.fixture.file('intent').read_text(encoding='utf-8'))
        evidence = json.dumps({'schema_version': 1, 'intent': intent, 'before': self.fixture.before},
                              ensure_ascii=False)
        self.assertLess(len(evidence), 262144)
        self.assertGreater(len(evidence.encode('utf-8')), 262144)
        self.assertEqual(self.fixture.invoke()['status'], 'error')
        self.fixture.vs.VWXDocStage.assert_not_called()
        self.assertFalse(self.fixture.file('dispatch').exists())

    def test_unopened_target_at_native_inventory_capacity_is_rejected_before_stage(self):
        self.fixture.before.extend(self.fixture.doc('c:\\drawings\\other_%03d.vwx' % i, i + 10, False)
                                   for i in range(255))
        self.fixture.inventory['count'] = 256
        self.fixture.publish()
        response = self.fixture.invoke()
        self.assertEqual(response['code'], 'VWX_DOCUMENT_TRANSITION_CAPACITY')
        self.assertIs(response['dispatched'], False)
        self.fixture.vs.VWXDocStage.assert_not_called()
        self.assertFalse(self.fixture.file('dispatch').exists())

    def test_existing_target_at_capacity_can_stage_without_increasing_inventory(self):
        self.fixture.before.extend(self.fixture.doc('c:\\drawings\\other_%03d.vwx' % i, i + 10, False)
                                   for i in range(254))
        self.fixture.before.append(self.fixture.doc(TARGET, 300, False))
        self.fixture.inventory['count'] = 256
        self.fixture.publish()
        self.assertEqual(self.fixture.invoke()['phase'], 'staged')
        self.fixture.vs.VWXDocStage.assert_called_once()

    def test_unopened_target_with_one_remaining_inventory_slot_can_stage(self):
        self.fixture.before.extend(self.fixture.doc('c:\\drawings\\other_%03d.vwx' % i, i + 10, False)
                                   for i in range(254))
        self.fixture.inventory['count'] = 255
        self.fixture.publish()
        self.assertEqual(self.fixture.invoke()['phase'], 'staged')
        self.fixture.vs.VWXDocStage.assert_called_once()

    def test_maximum_supported_intent_paths_leave_space_for_confirmation(self):
        # Both paths use the full accepted UTF-16 bound and three-byte UTF-8
        # characters. This exceeds ordinary Windows component limits on purpose:
        # it bounds serialized receipts for every accepted path, without opening it.
        source = 'c:\\' + '庭' * (32767 - 7) + '.vwx'
        target = 'c:\\' + '园' * (32767 - 7) + '.vwx'
        self.fixture.before[:] = [self.fixture.doc(source, 2147483646, True)]
        self.fixture.inventory['count'] = 1
        self.fixture.publish(expected_path=source, target_path=target)
        intent = json.loads(self.fixture.file('intent').read_text(encoding='utf-8'))
        receipt = {'schema_version': 1, 'intent': intent, 'outcome': 'completed',
                   'source_file_ref': 2147483646, 'target_file_ref': 2147483647}
        self.assertLessEqual(len(json.dumps(receipt, ensure_ascii=False).encode('utf-8')), 262144)
        # Duplicating the source in dispatch is larger; refuse before staging.
        self.assertEqual(self.fixture.invoke(expected_path=source, target_path=target)['status'], 'error')
        self.fixture.vs.VWXDocStage.assert_not_called()
        self.assertFalse(self.fixture.file('dispatch').exists())


if __name__ == '__main__':
    unittest.main()
