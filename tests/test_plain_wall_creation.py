"""Independent plain-wall construction contracts; no native drawing is opened."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock

from test_sdk_commands import command_namespace, sdk_mock


class PlainWallCreationTests(unittest.TestCase):
    def setUp(self):
        self.ns = command_namespace()
        self.vs = self.ns['vs']
        self.ns['_wall_trace'] = Mock()
        self.ns['_with_layer_class'] = Mock(return_value=('layer', 'class'))
        self.ns['_restore'] = Mock()
        self.style = ''
        self.components = 1
        self.widths = {1: 6.}
        self.events = []
        self.bind('LNewObj').side_effect = ['existing', 'new-wall']
        self.bind('GetTypeN').side_effect = lambda h: 68 if h in ('existing', 'new-wall') else 0
        self.ns['_oid'] = lambda h: {'existing': 'old-uuid', 'new-wall': 'new-uuid'}.get(h)
        self.ns['_h'] = lambda uuid: 'new-wall' if uuid == 'new-uuid' else None
        self.bind('Wall').side_effect = lambda p1, p2: self.events.append('create')
        self.bind('GetWallStyle').side_effect = lambda h: self.style
        self.bind('GetNumberOfComponents').side_effect = lambda h: (True, self.components)
        self.bind('ConvertToUnstyledWall').side_effect = self.unstyle
        self.bind('SetComponentWidth').side_effect = self.set_width
        self.bind('GetComponentWidth').side_effect = lambda h, index: (True, self.widths[index])
        self.bind('SetWallOverallHeights', True)
        self.bind('ResetObject')
        for name in ('SetWallWidth', 'SetWallPrefStyle', 'SetWallHeights', 'SetWallThickness', 'DelObject',
                     'GetWallHeight', 'GetWallThickness', 'GetBBox', 'DeleteAllComponents', 'InsertNewComponentN'):
            self.bind(name).side_effect = AssertionError('Unwanted native call: ' + name)
        self.params = dict(x1=30, y1=40, x2=40, y2=40, height=3, thickness=.5)

    def bind(self, name, result=None):
        fn = sdk_mock(name, result)
        setattr(self.vs, name, fn)
        return fn

    def unstyle(self, h):
        self.assertEqual(h, 'new-wall')
        self.events.append('unstyle')
        self.style = ''
        return True

    def create(self, **changes):
        return self.ns['create_wall']({**self.params, **changes})

    def set_width(self, h, index, width):
        self.assertEqual(h, 'new-wall')
        self.assertIn(index, self.widths)
        self.events.append('set-width')
        self.widths[index] = width
        return True

    def test_plain_wall_sets_its_one_component_width_then_absolute_height_bounds(self):
        result = self.create()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['object_id'], 'new-uuid')
        self.assertFalse(result['geometry_verified'])
        self.vs.Wall.assert_called_once_with((30., 40.), (40., 40.))
        self.vs.ConvertToUnstyledWall.assert_not_called()
        self.vs.DeleteAllComponents.assert_not_called()
        self.vs.InsertNewComponentN.assert_not_called()
        self.vs.SetComponentWidth.assert_called_once_with('new-wall', 1, .5)
        self.vs.SetWallOverallHeights.assert_called_once_with('new-wall', 0, 0, '', 0., 0, 0, '', 3.)
        self.vs.ResetObject.assert_called_once_with('new-wall')
        self.vs.SetWallWidth.assert_not_called()
        self.vs.SetWallPrefStyle.assert_not_called()
        self.vs.SetWallHeights.assert_not_called()
        self.vs.SetWallThickness.assert_not_called()
        self.vs.GetWallHeight.assert_not_called()
        self.vs.GetWallThickness.assert_not_called()
        self.ns['_restore'].assert_called_once_with(('layer', 'class'))

    def test_styled_default_is_removed_only_from_freshly_created_wall(self):
        self.style = 'Existing document default style'
        self.assertEqual(self.create()['status'], 'ok')
        self.assertEqual(self.events, ['create', 'unstyle', 'set-width'])
        self.vs.ConvertToUnstyledWall.assert_called_once_with('new-wall')
        self.vs.SetWallPrefStyle.assert_not_called()

    def test_component_free_wall_is_retained_as_incomplete_without_guessed_insertion(self):
        self.components = 0
        result = self.create()
        self.assertIn('error', result)
        self.assertEqual(result['object_id'], 'new-uuid')
        self.vs.DeleteAllComponents.assert_not_called()
        self.vs.InsertNewComponentN.assert_not_called()
        self.vs.SetComponentWidth.assert_not_called()

    def test_multiple_inherited_components_are_scaled_in_place_with_ratios_preserved(self):
        self.components = 3
        self.widths = {1: 2., 2: 3., 3: 5.}
        result = self.create(thickness=20)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['component_widths'], [4., 6., 10.])
        self.assertEqual(self.widths, {1: 4., 2: 6., 3: 10.})
        self.assertEqual(self.events, ['create', 'set-width', 'set-width', 'set-width'])
        self.vs.DeleteAllComponents.assert_not_called()
        self.vs.InsertNewComponentN.assert_not_called()

    def test_invalid_dimensions_and_degenerate_segment_stop_before_context_or_creation(self):
        invalid = [(key, value) for key in ('height', 'thickness') for value in (0, -1)]
        invalid += [(key, value) for key in self.params
                    for value in (True, None, '3', float('nan'), float('inf'), 10 ** 400)]
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                result = self.create(**{key: value})
                self.assertIn('error', result)
                self.assertFalse(result['mutation_dispatched'])
        result = self.create(x2=30, y2=40)
        self.assertIn('error', result)
        self.assertFalse(result['mutation_dispatched'])
        self.vs.Wall.assert_not_called()
        self.ns['_with_layer_class'].assert_not_called()

    def test_stale_or_missing_last_object_is_never_converted_or_modified(self):
        for stale in ('existing', None, 'not-a-wall'):
            self.vs.LNewObj.side_effect = ['existing', stale]
            result = self.create()
            self.assertIn('error', result)
            self.assertTrue(result['mutation_dispatched'])
            self.assertIsNone(result.get('object_id'))
        self.vs.ConvertToUnstyledWall.assert_not_called()
        self.vs.DeleteAllComponents.assert_not_called()
        self.vs.SetComponentWidth.assert_not_called()

    def test_different_handle_with_existing_uuid_cannot_become_owned_wall(self):
        self.ns['_oid'] = lambda h: 'old-uuid'
        result = self.create()
        self.assertIn('error', result)
        self.assertIsNone(result.get('object_id'))
        self.vs.DeleteAllComponents.assert_not_called()

    def test_missing_new_object_uuid_does_not_grant_mutation_ownership(self):
        self.ns['_oid'] = lambda h: 'old-uuid' if h == 'existing' else None
        self.assertIn('error', self.create())
        self.vs.DeleteAllComponents.assert_not_called()

    def test_false_setters_preserve_created_uuid_and_never_replay_or_delete_wall(self):
        for step in ('ConvertToUnstyledWall', 'SetComponentWidth', 'SetWallOverallHeights'):
            for bad in (False, None, 1, 'true'):
                with self.subTest(step=step, bad=bad):
                    self.setUp()
                    self.style = 'Styled' if step == 'ConvertToUnstyledWall' else ''
                    self.bind(step, bad)
                    result = self.create()
                    self.assertIn('error', result)
                    self.assertEqual(result['object_id'], 'new-uuid')
                    self.assertTrue(result['mutation_dispatched'])
                    self.assertFalse(result['geometry_verified'])
                    self.vs.Wall.assert_called_once()
                    getattr(self.vs, step).assert_called_once()
                    self.vs.ResetObject.assert_not_called()
                    self.vs.DelObject.assert_not_called()

    def test_noop_unstyle_fails_before_dimension_setters(self):
        self.style = 'Styled'
        self.bind('ConvertToUnstyledWall', True)  # Deliberate no-op.
        result = self.create()
        self.assertIn('error', result)
        self.assertEqual(result['object_id'], 'new-uuid')
        self.vs.SetComponentWidth.assert_not_called()
        self.vs.ResetObject.assert_not_called()

    def test_malformed_style_or_component_count_is_not_used_as_mutation_permission(self):
        for name, bad in [('GetWallStyle', None), ('GetWallStyle', False),
                          ('GetNumberOfComponents', (False, 0)),
                          ('GetNumberOfComponents', (1, 0)),
                          ('GetNumberOfComponents', (True, True)),
                          ('GetNumberOfComponents', (True, -1)),
                          ('GetNumberOfComponents', (True, 32768))]:
            self.setUp()
            self.bind(name, bad)
            result = self.create()
            self.assertIn('error', result)
            self.assertEqual(result['object_id'], 'new-uuid')
            self.vs.SetComponentWidth.assert_not_called()

    def test_native_exception_and_reset_failure_keep_incomplete_object_and_restore_context(self):
        for step in ('Wall', 'GetWallStyle', 'GetComponentWidth', 'SetComponentWidth',
                     'SetWallOverallHeights', 'ResetObject'):
            self.setUp()
            getattr(self.vs, step).side_effect = RuntimeError('native failure')
            result = self.create()
            self.assertIn('native failure', result['error'])
            self.assertTrue(result['mutation_dispatched'])
            self.assertEqual(result.get('object_id'), None if step == 'Wall' else 'new-uuid')
            self.assertFalse(result['geometry_verified'])
            self.ns['_restore'].assert_called_once()
            self.vs.DelObject.assert_not_called()

    def test_noop_width_or_malformed_width_readback_blocks_height_and_reset(self):
        for raw in ((True, 6.), (False, .5), (True, True), (True, float('nan')), None):
            self.setUp()
            self.bind('GetComponentWidth').side_effect = [(True, 6.), raw]
            result = self.create()
            self.assertIn('error', result)
            self.assertEqual(result['object_id'], 'new-uuid')
            self.vs.SetWallOverallHeights.assert_not_called()
            self.vs.ResetObject.assert_not_called()

    def test_invalid_inherited_widths_are_rejected_before_any_component_mutation(self):
        for raw in ((True, -1), (True, 0), (True, True), (True, float('inf')),
                    (False, 6), (1, 6), (True,), None):
            self.setUp()
            self.bind('GetComponentWidth', raw)
            result = self.create()
            self.assertIn('error', result)
            self.vs.SetComponentWidth.assert_not_called()
            self.vs.ResetObject.assert_not_called()

    def test_zero_width_component_is_preserved_when_total_width_is_positive(self):
        self.components = 2
        self.widths = {1: 0., 2: 6.}
        self.assertEqual(self.create()['component_widths'], [0., .5])
        self.assertEqual(self.widths, {1: 0., 2: .5})

    def test_alias_or_deleted_uuid_never_receives_component_mutation(self):
        for resolution in (None, 'existing'):
            self.setUp()
            self.ns['_h'] = lambda oid: resolution
            result = self.create()
            self.assertIn('error', result)
            self.assertEqual(result['object_id'], 'new-uuid')
            self.vs.SetComponentWidth.assert_not_called()

    def test_partial_multicomponent_failure_does_not_replay_or_hide_changed_width(self):
        self.components = 3
        self.widths = {1: 2., 2: 3., 3: 5.}
        calls = []
        def set_width(h, index, value):
            calls.append(index)
            if index == 2:
                return False
            return self.set_width(h, index, value)
        self.vs.SetComponentWidth.side_effect = set_width
        result = self.create(thickness=20)
        self.assertIn('error', result)
        self.assertEqual(result['phase'], 'SetComponentWidth[2]')
        self.assertEqual(result['object_id'], 'new-uuid')
        self.assertEqual(calls, [1, 2])
        self.assertEqual(self.widths, {1: 4., 2: 3., 3: 5.})
        self.vs.SetWallOverallHeights.assert_not_called()

    def test_wall_label_matches_sdk_3200_type_constant(self):
        source = Path(__file__).resolve().parents[1] / 'vwx-plugin/commands.py'
        declaration = next(node for node in ast.parse(source.read_text(encoding='utf-8')).body
                           if isinstance(node, ast.Assign)
                           and any(isinstance(target, ast.Name) and target.id == 'OBJ_TYPES' for target in node.targets))
        # SDK Kernel/API/Objs.TDType.h: kWallNode = 68.
        self.assertEqual(ast.literal_eval(declaration.value)[68], 'wall')


if __name__ == '__main__':
    unittest.main()
