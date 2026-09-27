"""Offline wall-join contracts; fake returns do not certify native geometry."""
import ast
import asyncio
import json
from pathlib import Path
import sys
from typing import Annotated, Any
import unittest
from unittest.mock import Mock

from pydantic import WithJsonSchema
from fastmcp import Client, Context, FastMCP

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'vwx-plugin/commands.py').is_file())
sys.path.insert(0, str(ROOT / 'tests'))
from test_sdk_commands import command_namespace, sdk_mock

WALL_A = '8ec2fd63-f0fa-42ef-81f2-07df8046c065'
WALL_B = 'cfbfa54b-b1d1-4cd5-8c82-57d0830fb310'


def selected_source(kind):
    return ROOT / ('vwx-plugin/commands.py' if kind == 'commands' else 'mcp-server/vwx_mcp_server.py')


def load_function(kind, namespace):
    tree = ast.parse(selected_source(kind).read_text(encoding='utf-8'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'join_walls')
    function.decorator_list = []
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<join_walls>', 'exec'), namespace)
    return namespace['join_walls']


class WallJoinContractTests(unittest.TestCase):
    def setUp(self):
        self.ns = command_namespace()
        self.join = load_function('commands', self.ns)
        self.vs = self.ns['vs']
        self.handles = {WALL_A: 'wall-a', WALL_B: 'wall-b'}
        self.bind('GetObjectByUuid').side_effect = self.handles.get
        self.bind('GetWallPathType', 0)
        self.bind('GetTypeN').side_effect = lambda h: 68 if h in ('wall-a', 'wall-b') else 0
        self.bind('GetObjectUuid').side_effect = lambda h: {'wall-a': WALL_A, 'wall-b': WALL_B}.get(h)
        self.bind('JoinWalls', True)
        for name in ('ResetObject', 'DelObject', 'GetBBox', 'GetSegPt1', 'GetSegPt2',
                     'SetWallOverallHeights', 'Wall', 'DoMenuTextByName'):
            self.bind(name).side_effect = AssertionError('Unwanted native call: ' + name)
        self.params = {'wall_id_a': WALL_A, 'wall_id_b': WALL_B,
                       'point_a': [18, 0], 'point_b': [20, 2], 'mode': 2, 'capped': True}

    def bind(self, name, result=None):
        fn = sdk_mock(name, result)
        setattr(self.vs, name, fn)
        return fn

    def call(self, **changes):
        return self.join({**self.params, **changes})

    def reject_undispatched(self, result, *, no_host_reads=False):
        self.assertEqual(result['status'], 'error')
        self.assertIn('error', result)
        self.assertIs(result['mutation_dispatched'], False)
        self.assertIs(result['geometry_verified'], False)
        self.assertEqual(result['outcome'], 'undispatched')
        self.vs.JoinWalls.assert_not_called()
        if no_host_reads:
            self.vs.GetObjectByUuid.assert_not_called()
            self.vs.GetTypeN.assert_not_called()
            self.vs.GetWallPathType.assert_not_called()
            self.vs.GetObjectUuid.assert_not_called()

    def test_exact_distinct_wall_handles_and_pick_points_are_sent_once(self):
        result = self.call()
        self.assertEqual(result['status'], 'ok')
        self.assertIs(result['joined'], True)
        self.assertIs(result['mutation_dispatched'], True)
        self.assertIs(result['geometry_verified'], False)
        self.assertEqual((result['wall_id_a'], result['wall_id_b']), (WALL_A, WALL_B))
        self.vs.JoinWalls.assert_called_once_with('wall-a', 'wall-b', (18., 0.), (20., 2.), 2, True, False)
        self.assertEqual(result['point_a'], [18., 0.])
        self.assertIn('later', result['verification'])
        for name in ('ResetObject', 'GetBBox', 'GetSegPt1', 'GetSegPt2', 'Wall', 'DelObject', 'DoMenuTextByName'):
            getattr(self.vs, name).assert_not_called()

    def test_all_sdk_modes_and_literal_cap_values_forward_unchanged(self):
        for mode in (1, 2, 3, 4):
            for capped in (False, True):
                self.setUp()
                with self.subTest(mode=mode, capped=capped):
                    self.assertEqual(self.call(mode=mode, capped=capped)['status'], 'ok')
                    self.vs.JoinWalls.assert_called_once_with('wall-a', 'wall-b', (18., 0.), (20., 2.), mode, capped, False)

    def test_existing_defaults_are_preserved_when_mode_and_capped_are_omitted(self):
        params = {k: v for k, v in self.params.items() if k not in ('mode', 'capped')}
        self.assertEqual(self.join(params)['status'], 'ok')
        self.vs.JoinWalls.assert_called_once_with('wall-a', 'wall-b', (18., 0.), (20., 2.), 2, True, False)

    def test_missing_either_or_both_pick_points_never_guesses_an_endpoint(self):
        for omitted in (('point_a',), ('point_b',), ('point_a', 'point_b')):
            self.setUp()
            self.reject_undispatched(self.join({k: v for k, v in self.params.items() if k not in omitted}), no_host_reads=True)
            self.vs.GetSegPt1.assert_not_called()
            self.vs.GetSegPt2.assert_not_called()

    def test_point_shape_and_coordinate_types_are_strict_before_any_host_call(self):
        invalid = [None, True, False, 2, '18,0', {}, [], [1], [1, 2, 3],
                   [[1, 2], 3], [True, 0], [0, False], ['18', 0], [0, None],
                   [float('nan'), 0], [0, float('inf')], [-float('inf'), 0], [10 ** 400, 0]]
        for field in ('point_a', 'point_b'):
            for value in invalid:
                self.setUp()
                with self.subTest(field=field, value=value):
                    self.reject_undispatched(self.call(**{field: value}), no_host_reads=True)

    def test_tuple_and_integer_points_are_accepted_without_mutating_input(self):
        params = {**self.params, 'point_a': (-18, 0), 'point_b': [20, -2]}
        before = params['point_b'][:]
        self.assertEqual(self.join(params)['status'], 'ok')
        self.assertEqual(params['point_b'], before)
        self.vs.JoinWalls.assert_called_once_with('wall-a', 'wall-b', (-18., 0.), (20., -2.), 2, True, False)

    def test_same_pick_point_is_not_confused_with_same_wall_identity(self):
        self.assertEqual(self.call(point_a=[20, 0], point_b=[20, 0])['status'], 'ok')
        self.vs.JoinWalls.assert_called_once()

    def test_non_object_parameters_are_rejected_cleanly(self):
        for value in (None, [], 'request', 1):
            self.setUp()
            self.reject_undispatched(self.join(value), no_host_reads=True)

    def test_missing_malformed_nil_and_non_string_ids_are_rejected_before_host_lookup(self):
        invalid = [None, True, 123, '', 'wall-a', [], {}, '00000000-0000-0000-0000-000000000000']
        for field in ('wall_id_a', 'wall_id_b'):
            for value in invalid:
                self.setUp()
                with self.subTest(field=field, value=value):
                    self.reject_undispatched(self.call(**{field: value}), no_host_reads=True)
            self.setUp()
            self.reject_undispatched(self.join({k: v for k, v in self.params.items() if k != field}), no_host_reads=True)

    def test_same_uuid_in_alternate_spelling_is_rejected_before_lookup(self):
        self.reject_undispatched(self.call(wall_id_b='{' + WALL_A.upper() + '}'), no_host_reads=True)

    def test_valid_alternate_uuid_spelling_is_canonicalized_and_roundtripped(self):
        result = self.call(wall_id_a='{' + WALL_A.upper() + '}')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['wall_id_a'], WALL_A)
        self.assertEqual(self.vs.GetObjectByUuid.call_args_list[0].args, (WALL_A,))

    def test_missing_native_wall_never_dispatches_join(self):
        for field in (WALL_A, WALL_B):
            self.setUp()
            self.handles.pop(field)
            self.reject_undispatched(self.call())

    def test_stale_wrong_and_malformed_native_types_never_dispatch(self):
        for target in ('wall-a', 'wall-b'):
            for bad_type in (0, 34, 71, 84, 86, None, True, '68', 68.0):
                self.setUp()
                with self.subTest(target=target, bad_type=bad_type):
                    self.vs.GetTypeN.side_effect = lambda h, bad=bad_type, t=target: bad if h == t else 68
                    self.reject_undispatched(self.call())

    def test_wrong_or_missing_uuid_readback_never_mutates_an_alias(self):
        for bad_id in (None, '', WALL_B, 'not-a-uuid', True):
            self.setUp()
            self.vs.GetObjectUuid.side_effect = lambda h, bad=bad_id: bad if h == 'wall-a' else WALL_B
            self.reject_undispatched(self.call())

    def test_distinct_requests_resolving_to_same_handle_are_rejected(self):
        self.handles[WALL_B] = 'wall-a'
        self.vs.GetObjectUuid.side_effect = [WALL_A, WALL_B]
        self.reject_undispatched(self.call())

    def test_mode_and_capped_coercion_is_never_accepted(self):
        for value in (None, True, False, 0, 5, -1, 2.0, '2', [], {}):
            self.setUp()
            self.reject_undispatched(self.call(mode=value), no_host_reads=True)
        for value in (None, 0, 1, 'true', 'false', [], {}):
            self.setUp()
            self.reject_undispatched(self.call(capped=value), no_host_reads=True)

    def test_native_false_keeps_both_ids_and_does_not_claim_no_effect_or_retry(self):
        self.bind('JoinWalls', False)
        result = self.call()
        self.assertEqual(result['code'], 'WALL_JOIN_REJECTED')
        self.assertIs(result['joined'], False)
        self.assertIs(result['mutation_dispatched'], True)
        self.assertIs(result['geometry_verified'], False)
        self.assertEqual((result['wall_id_a'], result['wall_id_b']), (WALL_A, WALL_B))
        self.vs.JoinWalls.assert_called_once()
        self.vs.ResetObject.assert_not_called()
        self.vs.DelObject.assert_not_called()

    def test_non_boolean_native_results_preserve_uncertainty_and_never_retry(self):
        for raw in (None, 0, 1, '', 'True', [], [True], {'joined': True}, float('nan')):
            self.setUp()
            with self.subTest(raw=raw):
                self.bind('JoinWalls', raw)
                result = self.call()
                self.assertEqual(result['code'], 'WALL_JOIN_RESULT')
                self.assertEqual(result['outcome'], 'uncertain')
                self.assertEqual(result['native_result_type'], type(raw).__name__)
                self.assertIsNone(result['joined'])
                self.assertIs(result['mutation_dispatched'], True)
                self.assertEqual((result['wall_id_a'], result['wall_id_b']), (WALL_A, WALL_B))
                self.assertIn('Do not retry', result['error'])
                json.dumps(result, allow_nan=False)
                self.vs.JoinWalls.assert_called_once()

    def test_native_join_exception_retains_dispatched_uncertainty(self):
        self.vs.JoinWalls.side_effect = RuntimeError('native join fault')
        result = self.call()
        self.assertEqual(result['code'], 'WALL_JOIN_NATIVE')
        self.assertEqual(result['phase'], 'JoinWalls')
        self.assertEqual(result['outcome'], 'uncertain')
        self.assertIs(result['mutation_dispatched'], True)
        self.assertEqual((result['wall_id_a'], result['wall_id_b']), (WALL_A, WALL_B))
        self.assertIn('native join fault', result['error'])
        self.vs.JoinWalls.assert_called_once()
        self.vs.ResetObject.assert_not_called()

    def test_native_identity_exceptions_are_undispatched(self):
        for name in ('GetObjectByUuid', 'GetTypeN', 'GetWallPathType', 'GetObjectUuid'):
            self.setUp()
            getattr(self.vs, name).side_effect = RuntimeError('identity inspection fault')
            result = self.call()
            self.reject_undispatched(result)
            self.assertIn('identity inspection fault', result['error'])

    def test_missing_or_noncallable_host_join_is_rejected_before_mutation(self):
        for bad in (None, False, 1, 'JoinWalls'):
            self.setUp()
            setattr(self.vs, 'JoinWalls', bad)
            result = self.call()
            self.assertEqual(result['status'], 'error')
            self.assertIs(result['mutation_dispatched'], False)
            self.assertEqual(result['outcome'], 'undispatched')
            self.assertEqual(result['phase'], 'JoinWalls_available')
            self.assertIn('unavailable', result['error'])
            self.vs.ResetObject.assert_not_called()
        self.setUp()
        delattr(self.vs, 'JoinWalls')
        self.assertIs(self.call()['mutation_dispatched'], False)


    def test_type68_arc_and_unknown_paths_never_dispatch(self):
        for target in ('wall-a','wall-b'):
            for value in (1,2,-1,None,True,False,'0',0.0):
                self.setUp()
                with self.subTest(target=target, value=value):
                    self.vs.GetWallPathType.side_effect = lambda h,t=target,v=value: v if h==t else 0
                    self.reject_undispatched(self.call())

    def test_both_straight_paths_are_checked(self):
        self.assertEqual(self.call()['status'],'ok')
        self.assertEqual([x.args for x in self.vs.GetWallPathType.call_args_list], [('wall-a',),('wall-b',)])


class WallJoinServerContractTests(unittest.TestCase):
    def setUp(self):
        self.cmd=Mock(return_value='native response')
        self.join=load_function('server',{'cmd':self.cmd,'Context':Context,'json':json,
                               'Annotated':Annotated,'Any':Any,'WithJsonSchema':WithJsonSchema})
        self.params={'wall_id_a':WALL_A,'wall_id_b':WALL_B,'point_a':[18,0],
                     'point_b':[20,2],'mode':2,'capped':True}

    def test_wrapper_forwards_exact_points_with_options(self):
        self.assertEqual(self.join(None,**{**self.params,'mode':3,'capped':False}),'native response')
        self.cmd.assert_called_once_with('join_walls',{**self.params,'mode':3,'capped':False})

    def test_missing_points_reject_locally_without_guessing(self):
        result=json.loads(self.join(None,WALL_A,WALL_B))
        self.assertEqual(result['outcome'],'undispatched')
        self.assertIs(result['mutation_dispatched'],False)
        self.cmd.assert_not_called()

    def test_raw_types_shapes_finiteness_and_ids_reject_before_publication(self):
        bad={'wall_id_a':[True,1,None,'wall-a'],'wall_id_b':[False,2,None,WALL_A],
             'mode':[True,False,2.0,'2',0,5,None],'capped':[0,1,'true','false',None],
             'point_a':[None,[True,0],['1',2],[1],[1,2,3],[float('nan'),0],[10**400,0]],
             'point_b':[None,[0,False],[1,'2'],[],{},[0,float('inf')]]}
        for key,values in bad.items():
            for value in values:
                with self.subTest(key=key,value=value):
                    self.cmd.reset_mock()
                    r=json.loads(self.join(None,**{**self.params,key:value}))
                    self.assertEqual(r['outcome'],'undispatched')
                    self.assertIs(r['mutation_dispatched'],False)
                    self.assertIs(r['geometry_verified'],False)
                    self.cmd.assert_not_called()

    def test_transport_exception_is_not_reclassified_undispatched(self):
        self.cmd.side_effect=RuntimeError('publication outcome unknown')
        with self.assertRaisesRegex(RuntimeError,'publication outcome unknown'):
            self.join(None,**self.params)
        self.cmd.assert_called_once()

    def test_real_fastmcp_client_preserves_raw_values_and_rejects_coercion(self):
        server=FastMCP('offline-wall-join-test')
        server.tool(output_schema=None)(self.join)
        async def exercise():
            async with Client(server) as client:
                wire=next(t for t in await client.list_tools() if t.name=='join_walls')
                schema=wire.input_schema
                self.assertEqual(schema['properties']['mode']['enum'],[1,2,3,4])
                self.assertEqual(schema['properties']['wall_id_a']['format'],'uuid')
                self.assertEqual(schema['properties']['point_a']['anyOf'][0]['minItems'],2)
                self.assertNotIn('outputSchema',wire.model_dump(by_alias=True,exclude_none=True))
                await client.call_tool('join_walls',self.params)
                self.cmd.assert_called_once_with('join_walls',self.params)
                changes=[{'point_a':[True,0]},{'point_b':[0,False]},
                         {'point_a':['18',0]},{'point_b':[20,'2']},
                         {'mode':True},{'mode':False},{'mode':2.0},{'mode':'2'},
                         {'capped':1},{'capped':0},{'capped':'false'},
                         {'wall_id_a':True},{'wall_id_b':123},
                         {'point_a':[1]},{'point_b':[1,2,3]},{'point_a':None}]
                for change in changes:
                    with self.subTest(change=change):
                        self.cmd.reset_mock()
                        result=await client.call_tool('join_walls',{**self.params,**change})
                        r=json.loads(result.content[0].text)
                        self.assertEqual(r['outcome'],'undispatched')
                        self.assertIs(r['mutation_dispatched'],False)
                        self.cmd.assert_not_called()
                self.cmd.reset_mock()
                p={**self.params,'mode':4,'capped':False,'point_a':[-18,.5],'point_b':[20.25,-2]}
                await client.call_tool('join_walls',p)
                self.cmd.assert_called_once_with('join_walls',p)
        asyncio.run(exercise())


if __name__=='__main__':
    unittest.main()
