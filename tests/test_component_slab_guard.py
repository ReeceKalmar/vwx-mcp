"""Narrow modern-Slab owner guard; fake resource setters are not native proof."""
import unittest
from unittest.mock import Mock
from test_sdk_commands import command_namespace, sdk_mock


class ModernSlabComponentGuardTests(unittest.TestCase):
    def setUp(self):
        self.ns = command_namespace()
        self.vs = self.ns['vs']

    def bind(self, name, result=None):
        fn = sdk_mock(name, result)
        setattr(self.vs, name, fn)
        return fn

    def fixture(self, kind='material'):
        self.setUp()
        self.kind = kind
        self.types = {'slab': 86, 'hidden-record': 48, 'resource': 19 if kind == 'material' else 97}
        self.bind('GetTypeN').side_effect = self.types.get
        self.bind('GetParametricRecord', 'hidden-record')
        self.bind('GetName').side_effect = lambda h: 'Slab' if h == 'hidden-record' else 'lookalike'
        self.bind('GetRecord').side_effect = AssertionError('Ordinary attached records cannot identify Slab')
        self.bind('GetRField').side_effect = AssertionError('Record fields cannot identify Slab')
        self.bind('GetNumberOfComponents', (True, 1))
        self.ns['_name_obj'] = Mock(return_value='resource')
        self.bind('Name2Index', 42)
        self.bind('Index2Name', 'Finish')
        self.setter = self.bind('SetComponent' + kind.title(), True)
        self.getter = self.bind('GetComponent' + kind.title(), (True, 42))
        self.bind('ResetObject')
        return {'object_id': 'slab', 'index': 1, kind + '_name': 'Finish'}

    def run_command(self, params):
        return self.ns['set_component_' + self.kind](params)

    def rejected(self, params):
        r = self.run_command(params)
        self.assertIn('error', r)
        self.assertIs(r['mutation_dispatched'], False)
        self.setter.assert_not_called()
        self.getter.assert_not_called()
        self.vs.ResetObject.assert_not_called()

    def test_exact_hidden_slab_record_allows_both_typed_resources(self):
        for kind in ('material', 'texture'):
            p = self.fixture(kind)
            r = self.run_command(p)
            self.assertEqual(r, {'status': 'ok', 'resource_index': 42,
                                'parameter_verified': True, 'geometry_verified': False})
            self.vs.GetParametricRecord.assert_called_once_with('slab')
            self.vs.GetName.assert_called_once_with('hidden-record')
            self.vs.GetRecord.assert_not_called()
            self.vs.GetRField.assert_not_called()
            self.setter.assert_called_once_with('slab', 1, 42)
            self.getter.assert_called_once_with('slab', 1)
            self.vs.ResetObject.assert_called_once_with('slab')

    def test_generic_pios_and_case_or_whitespace_lookalikes_reject(self):
        for name in ('Hardscape', 'Landscape Area', 'Space', 'slab', 'SLAB', 'Slab ', '', None, True):
            p = self.fixture()
            self.vs.GetName.side_effect = None
            self.vs.GetName.return_value = name
            self.rejected(p)
            self.vs.GetNumberOfComponents.assert_not_called()

    def test_missing_or_wrong_hidden_record_type_rejects(self):
        for handle in (None, '', False):
            p = self.fixture()
            self.bind('GetParametricRecord', handle)
            self.rejected(p)
            self.vs.GetName.assert_not_called()
        for record_type in (0, 47, 86, None, True, 48.0, '48'):
            p = self.fixture()
            self.types['hidden-record'] = record_type
            self.rejected(p)
            self.vs.GetName.assert_not_called()

    def test_object_name_and_attached_slab_record_cannot_spoof_hidden_record(self):
        p = self.fixture()
        self.vs.GetName.side_effect = lambda h: 'Slab' if h != 'hidden-record' else 'Hardscape'
        self.vs.GetRecord.side_effect = None
        self.vs.GetRecord.return_value = 'attached-slab'
        self.rejected(p)
        self.vs.GetName.assert_called_once_with('hidden-record')
        self.vs.GetRecord.assert_not_called()

    def test_malformed_owner_type_does_not_probe_parametric_record(self):
        for owner_type in (86.0, '86', True, None, 0):
            p = self.fixture()
            self.types['slab'] = owner_type
            self.rejected(p)
            self.vs.GetParametricRecord.assert_not_called()

    def test_hidden_record_identity_exceptions_are_undispatched(self):
        for name in ('GetParametricRecord', 'GetTypeN', 'GetName'):
            p = self.fixture()
            getattr(self.vs, name).side_effect = RuntimeError('identity failure')
            self.rejected(p)

    def test_hidden_slab_still_requires_successful_bounded_component_count(self):
        for count in ((False, 1), (True, 0), (True, True), (1, 1), (True, 32768), None, 1):
            p = self.fixture()
            self.bind('GetNumberOfComponents', count)
            self.rejected(p)
            self.ns['_name_obj'].assert_not_called()

    def test_native_false_remains_dispatched_failure_without_reset_or_retry(self):
        p = self.fixture('texture')
        self.bind('SetComponentTexture', False)
        self.setter = self.vs.SetComponentTexture
        r = self.run_command(p)
        self.assertIn('error', r)
        self.assertIs(r['mutation_dispatched'], True)
        self.setter.assert_called_once_with('slab', 1, 42)
        self.getter.assert_not_called()
        self.vs.ResetObject.assert_not_called()


if __name__ == '__main__':
    unittest.main()
