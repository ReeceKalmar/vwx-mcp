"""Bounded resource traversal with a native-style stop-on-True callback fake."""
import unittest
import uuid
from unittest.mock import Mock
from test_sdk_commands import command_namespace, sdk_mock


class ResourceTraversalTests(unittest.TestCase):
    def setUp(self):
        self.ns = command_namespace()
        self.vs = self.ns['vs']
        self.nodes = {}
        self.children = {}
        self.first_override = {}
        self.streams = {}
        self.visits = []
        self.flags = []
        self.starts = []
        self.node('root', 16, 'layer')
        self.node('layer', 31, None)
        self.bind('GetTypeN').side_effect = lambda h: self.nodes.get(h, {}).get('type', 0)
        self.bind('GetObjectUuid').side_effect = lambda h: self.nodes.get(h, {}).get('uuid')
        self.bind('GetParent').side_effect = lambda h: self.nodes[h]['parent']
        self.bind('FInGroup').side_effect = self.first
        self.bind('FInSymDef').side_effect = self.first
        self.bind('ForEachObjectInList').side_effect = self.iterate
        self.bind('GetName').side_effect = lambda h: h
        self.bind('GetSymDefSubType', 0)
        self.ns['_name_obj'] = lambda name: 'root'
        self.ns['_pio_name'] = lambda h: 'Plant'

    def bind(self, name, result=None):
        fn = sdk_mock(name, result)
        setattr(self.vs, name, fn)
        return fn

    def node(self, name, kind=3, parent='root'):
        self.nodes[name] = {'type': kind, 'parent': parent,
                            'uuid': str(uuid.uuid5(uuid.NAMESPACE_URL, 'resource-test/' + name))}
        if parent is not None:
            self.children.setdefault(parent, []).append(name)
        return name

    def first(self, h):
        if h in self.first_override:
            return self.first_override[h]
        return next(iter(self.children.get(h, ())), None)

    def iterate(self, callback, obj_options, traversal_options, first):
        self.assertEqual((obj_options, traversal_options), (0, 0))
        self.starts.append(first)
        values = self.streams.get(first)
        if values is None:
            siblings = self.children[self.nodes[first]['parent']]
            values = iter(siblings[siblings.index(first):])
        else:
            values = iter(values() if callable(values) else values)
        for obj in values:
            self.visits.append(obj)
            flag = callback(obj)
            self.flags.append(flag)
            self.assertIs(type(flag), bool)
            if flag is True:
                break
            if len(self.visits) > 5000:
                self.fail('Native fake exceeded its safety tripwire')

    def count(self, **kwargs):
        return self.ns['_deep_count']('root', **kwargs)

    def test_nil_and_empty_containers_never_start_iterator(self):
        self.assertEqual(self.ns['_deep_count'](None), 0)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.starts, [])

    def test_flat_children_continue_false_until_normal_end(self):
        self.node('a'); self.node('b'); self.node('c')
        self.assertEqual(self.count(), 3)
        self.assertEqual(self.flags, [False, False, False])

    def test_wide_lazy_list_stops_on_true_at_cap(self):
        self.node('a')
        def many():
            for i in range(1000000):
                h = self.node('wide-' + str(i))
                yield h
        self.streams['a'] = many
        self.assertEqual(self.count(cap=7), 7)
        self.assertEqual(len(self.visits), 7)
        self.assertEqual(self.flags, [False] * 6 + [True])

    def test_cap_zero_performs_no_host_lookup(self):
        self.assertEqual(self.count(cap=0), 0)
        self.vs.GetTypeN.assert_not_called()
        self.vs.FInSymDef.assert_not_called()

    def test_invalid_bounds_reject_without_host_access(self):
        for kwargs in ({'cap': -1}, {'cap': True}, {'cap': 2.0},
                       {'max_depth': -1}, {'max_depth': True}, {'max_depth': 1.0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.count(**kwargs)
        self.vs.GetTypeN.assert_not_called()

    def test_empty_group_parent_escape_is_rejected_before_native_traversal(self):
        self.node('outside', parent='layer')
        self.first_override['root'] = 'outside'
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.starts, [])

    def test_missing_or_nil_container_uuid_fails_closed_before_first_lookup(self):
        for raw in (None, '', 'bad-uuid', '00000000-0000-0000-0000-000000000000'):
            self.nodes['root']['uuid'] = raw
            self.assertEqual(self.count(), 0)
        self.vs.FInSymDef.assert_not_called()

    def test_foreign_parent_midlist_stops_before_remaining_siblings(self):
        self.node('a'); self.node('b'); self.node('foreign', parent='layer')
        self.streams['a'] = ['a', 'foreign', 'b']
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.visits, ['a', 'foreign'])
        self.assertEqual(self.flags, [False, True])

    def test_repeated_or_nil_callback_stops_without_recount(self):
        for repeated in ('a', None):
            self.setUp(); self.node('a'); self.node('b')
            self.streams['a'] = ['a', repeated, 'b']
            self.assertEqual(self.count(), 1)
            self.assertEqual(len(self.visits), 2)
            self.assertEqual(self.flags, [False, True])

    def test_self_and_ancestor_cycle_never_traverse_repeated_root(self):
        self.first_override['root'] = 'root'
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.starts, [])
        self.setUp(); self.node('g', 11); self.first_override['g'] = 'root'
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.starts, ['g'])

    def test_depth_limit_preserves_immediate_children_at_depth_zero(self):
        self.node('g1', 11); self.node('g2', 86, 'g1'); self.node('leaf', 3, 'g2')
        self.assertEqual(self.count(max_depth=0), 1)
        self.assertEqual(self.count(max_depth=1), 2)
        self.assertEqual(self.count(max_depth=2), 3)

    def test_large_depth_is_iterative_and_still_obeys_global_cap(self):
        parent = 'root'
        for i in range(1200):
            parent = self.node('g' + str(i), 11, parent)
        self.assertEqual(self.count(cap=1001, max_depth=2000), 1001)
        self.assertEqual(len(self.visits), 1001)
        self.assertIs(self.flags[-1], True)

    def test_nested_wide_branch_cannot_overrun_cap_on_ancestor_resume(self):
        self.node('group', 11); self.node('sibling')
        for i in range(20): self.node('leaf' + str(i), parent='group')
        self.assertEqual(self.count(cap=5), 5)
        self.assertEqual(len(self.visits), 5)

    def test_rejected_callbacks_share_one_global_visit_budget(self):
        self.node('g1', 11); self.node('g2', 11)
        self.node('a', parent='g1'); self.node('b', parent='g2'); self.node('c', parent='g2')
        self.streams['a'] = ['a', 'a']
        self.assertEqual(self.count(cap=5), 4)
        self.assertEqual(self.visits, ['g1', 'g2', 'a', 'a', 'b'])
        self.assertEqual(len(self.visits), 5)
        self.assertIs(self.flags[-1], True)

    def test_unknown_parent_identity_stops_before_iterator(self):
        self.node('a')
        self.vs.GetParent.side_effect = lambda h: None
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.starts, [])

    def test_uuid_aliases_are_canonicalized_for_cycle_detection(self):
        self.node('alias')
        self.nodes['alias']['uuid'] = '{' + self.nodes['root']['uuid'].upper() + '}'
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.starts, [])

    def test_single_pio_style_requires_complete_owned_contents(self):
        self.node('pio', 86)
        result = self.ns['resource_info']({'name':'style'})
        self.assertTrue(result['is_plugin_style'])
        self.assertTrue(result['contents_complete'])
        self.streams['pio'] = ['pio', 'pio']
        result = self.ns['resource_info']({'name':'style'})
        self.assertFalse(result['is_plugin_style'])
        self.assertFalse(result['contents_complete'])
        self.assertEqual(result['nesting_count'], 1)

    def test_resource_info_immediate_and_deep_traversals_are_bounded(self):
        for i in range(1000): self.node('leaf' + str(i))
        result = self.ns['resource_info']({'name':'style'})
        self.assertEqual(result['nesting_count'], 500)
        self.assertEqual(len(result['inner_types']), 50)
        self.assertFalse(result['contents_complete'])
        self.assertFalse(result['is_plugin_style'])
        self.assertEqual(len(self.visits), 1000)  # two separately bounded scans

    def test_native_iteration_error_keeps_partial_count_and_incomplete_info(self):
        self.node('pio', 86)
        def failed(callback, objOptions, travOptions, first):
            callback(first)
            raise RuntimeError('native iteration failure')
        self.vs.ForEachObjectInList.side_effect = failed
        self.assertEqual(self.count(), 1)
        result = self.ns['resource_info']({'name':'style'})
        self.assertFalse(result['contents_complete'])
        self.assertFalse(result['is_plugin_style'])

    def test_resource_import_absent_name_uses_same_job_list_and_never_renames(self):
        self.ns['_name_obj'] = lambda name: None
        self.bind('BuildResourceListN', (135, 2))
        self.bind('GetNameFromResourceList').side_effect = lambda lid, i: ['Other','Style'][i-1]
        def imported(lid, index, callback):
            self.assertEqual((lid,index), (135,2))
            self.assertEqual(callback('conflict'), 0)
            return 'root'
        self.bind('ImportResToCurFileN').side_effect = imported
        self.bind('SetName').side_effect = AssertionError('No rename branch expected')
        self.ns['RESOURCE_TYPES'] = {'style':16}
        result = self.ns['resource_import']({'file_path':'library.vwx','name':'Style','type':16})
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['nesting_count'],0)
        self.vs.ImportResToCurFileN.assert_called_once()
        self.vs.SetName.assert_not_called()

    def test_resource_import_existing_name_without_new_name_refuses_before_native_import(self):
        self.bind('ImportResToCurFileN').side_effect = AssertionError('Must not import')
        self.bind('SetName').side_effect = AssertionError('Must not rename')
        r = self.ns['resource_import']({'file_path':'library.vwx','name':'Style','type':16})
        self.assertIn('name exists', r['error'])
        self.vs.ImportResToCurFileN.assert_not_called()
        self.vs.SetName.assert_not_called()


if __name__ == '__main__':
    unittest.main()
