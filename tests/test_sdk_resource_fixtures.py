"""Independent resource state models drive real adapters; no native host calls."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RESOURCE = load('resource_fixture_module', 'tools/sdk_resource_fixtures.py')
HOST = RESOURCE.DESIGN.HOST
RUNTIME = HOST._load_runtime(ROOT)
RUNNER = load('resource_fixture_runner', 'tools/sdk_design_runner.py')
POLICY = load('resource_fixture_policy', 'mcp-server/background_policy.py')
CATALOG = json.loads((ROOT / 'vwx-plugin/sdk_catalog.json').read_text(encoding='utf-8'))
INDEX = json.loads((ROOT / 'vwx-plugin/vs_index.json').read_text(encoding='utf-8'))
with patch.dict(sys.modules, {'sdk_runtime': RUNTIME}):
    SEQUENCES = load('resource_fixture_sequences', 'vwx-plugin/sdk_sequences.py')


class ResourceModel:
    """State derives only from SDK arguments, never from a fixture assertion.

    Separate instances reference symbol definitions; textures live in an index
    table; per-object assignments and light properties are independent stores.
    Faults simulate plausible native no-ops, axis/color bugs and leaked writes.
    """
    def __init__(self, fault=None):
        self.fault = fault
        self.objects, self.named, self.indices, self.stack = {}, {}, {}, []
        self.last = None

    def _new(self, kind, **data):
        key = str(uuid.uuid5(uuid.NAMESPACE_OID, 'resource-model-%d' % len(self.objects)))
        obj = SimpleNamespace(kind=kind, uuid=key, name='', parent=None, **data)
        self.objects[key] = obj
        if self.stack:
            obj.parent = self.stack[-1]
            obj.parent.children.append(obj)
        self.last = obj
        return obj

    def _write(self, api, obj, **data):
        if self.fault == 'noop:' + api:
            return
        targets = [obj]
        if self.fault == 'leak:' + api:
            targets = [other for other in self.objects.values() if other.kind == obj.kind]
        for target in targets:
            for name, value in data.items():
                setattr(target, name, copy.deepcopy(value))

    def GetVersion(self): return 32, 0, 0, 2
    def GetObjectByUuid(self, key): return self.objects.get(key)
    def GetObjectUuid(self, obj): return obj.uuid
    def GetTypeN(self, obj): return obj.kind if obj else 0
    def LNewObj(self): return self.last
    def GetObject(self, name): return self.named.get(name)
    def GetName(self, h): return h.name
    def GetParent(self, h): return h.parent

    def SetName(self, h, name):
        if self.fault != 'noop:SetName':
            if h.name: self.named.pop(h.name, None)
            h.name = name
            self.named[name] = h

    def Rect(self, p1, p2):
        self._new(3, corners=(p1, p2))

    def HWidth(self, h): return abs(h.corners[1][0] - h.corners[0][0])
    def HHeight(self, h): return abs(h.corners[1][1] - h.corners[0][1])

    def BeginSym(self, symbolName):
        obj = self._new(16, children=[])
        self.SetName(obj, symbolName)
        self.stack.append(obj)

    def EndSym(self): self.last = self.stack.pop()
    def FInSymDef(self, sdHd): return sdHd.children[0]

    def Symbol(self, symbolName, p, rotationAngle):
        if self.fault == 'wrong_symbol_definition':
            definition = next(obj for obj in self.objects.values() if obj.kind == 16)
        else:
            definition = self.named[symbolName]
        self._new(15, definition=definition, point=tuple(p), rotation=rotationAngle)

    def GetSymbolType(self, objectHandle):
        kinds = {child.kind for child in objectHandle.definition.children}
        return 0 if kinds == {3} else 1

    def GetSymName(self, symHd): return symHd.definition.name
    def GetSymLoc(self, symHd): return symHd.point
    def GetSymRot(self, symHd): return symHd.rotation

    def HMove(self, h, xOffset, yOffset):
        self._write('HMove', h, point=(h.point[0] + xOffset, h.point[1] + yOffset))

    def HRotate(self, h, center, rotationAngle):
        angle = math.radians(rotationAngle)
        x, y = h.point[0] - center[0], h.point[1] - center[1]
        point = (center[0] + x * math.cos(angle) - y * math.sin(angle),
                 center[1] + x * math.sin(angle) + y * math.cos(angle))
        self._write('HRotate', h, point=point, rotation=(h.rotation + rotationAngle) % 360)

    def CreateTexture(self):
        obj = self._new(97, size=1)
        self.indices[len(self.indices) + 1] = obj
        return obj

    def SetTextureSize(self, texture, newSize): self._write('SetTextureSize', texture, size=newSize)
    def GetTextureSize(self, texture): return texture.size
    def Name2Index(self, name): return next(index for index, obj in self.indices.items() if obj.name == name)
    def Index2Name(self, index): return self.indices[index].name

    def BeginXtrd(self, startDistance, endDistance):
        self.stack.append(self._new(24, children=[], z=(startDistance, endDistance), textures={}))

    def EndXtrd(self): self.last = self.stack.pop()
    def IsTextureableObject(self, obj): return obj.kind == 24

    def Get3DInfo(self, h):
        return self.HHeight(h.children[0]), self.HWidth(h.children[0]), abs(h.z[1] - h.z[0])

    def SetTextureRefN(self, obj, textureRef, texPartID, texLayerID):
        parts = dict(obj.textures)
        if self.fault == 'wrong_texture_part': texPartID = 3
        parts[texPartID, texLayerID] = textureRef
        self._write('SetTextureRefN', obj, textures=parts)

    def GetTextureRefN(self, obj, texPartID, texLayerID, resolveByClass):
        return obj.textures.get((texPartID, texLayerID), 0)

    def CreateGradient(self, name):
        obj = self._new(120, segments=[{'position': 0.0, 'midpoint': 0.5, 'rgb': (255, 255, 255), 'opacity': 100},
                                       {'position': 1.0, 'midpoint': 0.5, 'rgb': (0, 0, 0), 'opacity': 100}])
        self.SetName(obj, name)
        return obj

    def GetNumGradientSegments(self, gradient): return len(gradient.segments)
    def GetGradientSpotPosition(self, gradient, segmentIndex): return gradient.segments[segmentIndex - 1]['position']
    def GetGradientMidpointPosition(self, gradient, segmentIndex): return gradient.segments[segmentIndex - 1]['midpoint']
    def GetGradientOpacity(self, gradient, segmentIndex): return gradient.segments[segmentIndex - 1]['opacity']

    def GetGradientSpotColor(self, gradient, segmentIndex):
        rgb = gradient.segments[segmentIndex - 1]['rgb']
        return tuple(channel * 257 for channel in rgb) if self.fault == 'gradient_rgb_16bit' else rgb

    def GetGradientData(self, gradient, segmentIndex):
        segment = gradient.segments[segmentIndex - 1]
        return segment['position'], segment['midpoint'], *self.GetGradientSpotColor(gradient, segmentIndex)

    def GetGradientDataN(self, gradient, segmentIndex):
        values = (*self.GetGradientData(gradient, segmentIndex), self.GetGradientOpacity(gradient, segmentIndex))
        if self.fault == 'gradient_extra_success_flag': return (True, *values)
        if self.fault == 'gradient_data_n_wrong_color': return (*values[:2], 255, 0, 0, values[5])
        if self.fault == 'gradient_data_n_stale_opacity': return (*values[:5], 100)
        return values

    def _gradient_update(self, api, gradient, segmentIndex, **updates):
        segments = copy.deepcopy(gradient.segments)
        segment = segments[segmentIndex - 1]
        segment.update(updates)
        if self.fault != 'gradient_no_reorder':
            segments.sort(key=lambda item: item['position'])
        updated_index = segments.index(segment) + 1
        self._write(api, gradient, segments=segments)
        return segmentIndex if self.fault == 'gradient_stale_index' else updated_index

    def _gradient_insert(self, api, gradient, spotPosition, midpointPosition, red, green, blue, opacity):
        segments = copy.deepcopy(gradient.segments)
        segment = {'position': spotPosition, 'midpoint': midpointPosition, 'rgb': (red, green, blue), 'opacity': opacity}
        segments.append(segment)
        segments.sort(key=lambda item: item['position'])
        self._write(api, gradient, segments=segments)
        return segments.index(segment) + 1

    def InsertGradientSegment(self, gradient, spotPosition, midpointPosition, red, green, blue):
        return self._gradient_insert('InsertGradientSegment', gradient, spotPosition, midpointPosition, red, green, blue, 100)

    def InsertGradientData(self, gradient, spotPosition, midpointPosition, red, green, blue, opacity):
        return self._gradient_insert('InsertGradientData', gradient, spotPosition, midpointPosition, red, green, blue, opacity)

    def SetGradientData(self, gradient, segmentIndex, spotPosition, midpointPosition, red, green, blue):
        return self._gradient_update('SetGradientData', gradient, segmentIndex, position=spotPosition,
                                     midpoint=midpointPosition, rgb=(red, green, blue))

    def SetGradientDataN(self, gradient, segmentIndex, spotPosition, midpointPosition, red, green, blue, opacity):
        return self._gradient_update('SetGradientDataN', gradient, segmentIndex, position=spotPosition,
                                     midpoint=midpointPosition, rgb=(red, green, blue), opacity=opacity)

    def SetGradientSpotPosition(self, gradient, segmentIndex, position):
        return self._gradient_update('SetGradientSpotPosition', gradient, segmentIndex, position=position)

    def SetGradientMidpointPosition(self, gradient, segmentIndex, position):
        value = position * gradient.segments[segmentIndex - 1]['position'] if self.fault == 'gradient_absolute_midpoint' else position
        self._gradient_update('SetGradientMidpointPosition', gradient, segmentIndex, midpoint=value)

    def SetGradientSpotColor(self, gradient, segmentIndex, red, green, blue):
        self._gradient_update('SetGradientSpotColor', gradient, segmentIndex, rgb=(red, green, blue))

    def SetGradientOpacity(self, gradient, segmentIndex, opacity):
        value = opacity / 100 if self.fault == 'gradient_opacity_fraction' else opacity
        self._gradient_update('SetGradientOpacity', gradient, segmentIndex, opacity=value)

    def RemoveGradientSegment(self, gradient, segmentIndex):
        segments = copy.deepcopy(gradient.segments)
        if len(segments) < 3: raise ValueError('Cannot remove below two gradient spots')
        segments.pop(segmentIndex - 1)
        self._write('RemoveGradientSegment', gradient, segments=segments)

    def CreateLight(self, pXR, pYR, pZR, lightType, isOn, castShadow):
        brightness = 100 if self.fault == 'host_light_default' else 75
        return self._new(81, point=(pXR, pYR, pZR), info=(lightType, brightness, isOn, castShadow),
                         light_variables={50: isOn, 53: castShadow, 55: lightType},
                         rgb=(65535, 65535, 65535), direction=(0, 0), falloff=(0, 0))

    def GetLightLocation(self, h): return h.point
    def GetLightInfo(self, h): return h.info
    def GetLightColorRGB(self, light): return light.rgb
    def GetLightDirection(self, h): return h.direction
    def GetLightFalloff(self, light): return light.falloff

    def SetLightLocation(self, h, p, zValue): self._write('SetLightLocation', h, point=(*p, zValue))

    def SetLightInfo(self, h, lightType, brightness, isOn, castShadow):
        self._write('SetLightInfo', h, info=(lightType, brightness, isOn, castShadow))
        if self.fault != 'light_info_stale_selectors':
            self._write('SetLightInfo', h, light_variables={50: isOn, 53: castShadow, 55: lightType})

    def GetObjectVariableBoolean(self, h, index):
        if h.kind != 81 or index not in (50, 53):
            raise ValueError('Only documented public light Boolean selectors are modeled')
        return h.light_variables[index]

    def GetObjectVariableInt(self, h, index):
        if h.kind != 81 or index != 55:
            raise ValueError('Only documented public light-kind selector is modeled')
        return h.light_variables[index]

    def SetLightColorRGB(self, light, red, green, blue):
        rgb = (red, green, blue)
        if self.fault == 'rgb_8bit': rgb = tuple(value // 257 for value in rgb)
        self._write('SetLightColorRGB', light, rgb=rgb)

    def SetLightDirection(self, h, panAngleR, tiltAngleR):
        angles = (tiltAngleR, panAngleR) if self.fault == 'direction_axis_swap' else (panAngleR, tiltAngleR)
        self._write('SetLightDirection', h, direction=angles)

    def SetLightFalloff(self, light, distFalloff, angFalloff):
        values = (angFalloff, distFalloff) if self.fault == 'falloff_axis_swap' else (distFalloff, angFalloff)
        self._write('SetLightFalloff', light, falloff=values)

    def BeginGroup(self): self.stack.append(self._new(11, children=[]))
    def EndGroup(self): self.last = self.stack.pop()

    def ContainsLight(self, containerObject):
        if self.fault == 'contains_always_true': return True
        return any(child.kind == 81 or (hasattr(child, 'children') and self.ContainsLight(child))
                   for child in containerObject.children)


def run_model(jobs, model):
    captures, results = {}, []
    for job in jobs:
        request = RUNNER.render_typed_job(job, captures)
        params = request['params']
        if request['command'] == 'sdk_sequence':
            response = SEQUENCES.run(params, vs_module=model, catalog=CATALOG)
        else:
            response = RUNTIME.invoke(params['name'], {'arguments': params['arguments']},
                                      vs_module=model, catalog=CATALOG)
        passed, assertions = HOST.evaluate_native(job, response)
        results.append((job['id'], passed, response, assertions))
        if not passed: break
        if 'capture' in job:
            captures[job['capture']['name']] = HOST._at(response, job['capture']['path'])
    return results


def check_readback_links(jobs):
    """No creation/mutation can be credited by return shape alone."""
    indices = {job['id']: index for index, job in enumerate(jobs)}
    verified = set()
    for index, job in enumerate(jobs):
        for target in job.get('verifies_jobs', []):
            if target not in indices or indices[target] >= index or job['phase'] != 'readback':
                raise ValueError('Invalid separate-job readback')
            verified.add(target)
    missing = {job['id'] for job in jobs if job['phase'] in {'creation', 'mutation'}} - verified
    if missing: raise ValueError('Missing independent readback: ' + ', '.join(sorted(missing)))


class SDKResourceFixtureTests(unittest.TestCase):
    def test_whole_plan_passes_registry_validation_without_registering_files(self):
        registry = load('resource_fixture_registry', 'tools/sdk_regression_suite.py')
        with patch.dict(registry.PROVIDERS, {'resource': ('sdk_resource_fixtures.py', 'resource_fixtures')}):
            plan = registry.build_plan(str(ROOT / '.audit/VWX-MCP-SDK-TEST-resources.vwx'),
                        run_id='resource-contracts', selected=['resource:' + family for family in RESOURCE.FAMILIES])
        self.assertEqual(len(plan['jobs']), len(RESOURCE.resource_fixtures('resource-contracts')))
        self.assertTrue(registry.validate_plan(plan))

    def test_every_family_runs_through_real_adapters_and_independent_state_model(self):
        for family in RESOURCE.FAMILIES:
            with self.subTest(family=family):
                jobs = RESOURCE.resource_fixtures('offline', [family])
                model = ResourceModel()
                results = run_model(jobs, model)
                self.assertTrue(all(row[1] for row in results), results[-1])
                self.assertEqual(len(results), len(jobs))
                self.assertFalse(model.stack)
                check_readback_links(jobs)

    def test_exact_sdk_contracts_background_policy_and_capture_dependencies(self):
        captures, ids = {}, set()
        for job in RESOURCE.resource_fixtures('contracts'):
            self.assertNotIn(job['id'], ids)
            ids.add(job['id'])
            self.assertEqual(job['native_status'], 'pending_not_executed')
            for native_call in job.get('calls', [job]):
                name = native_call['name']
                self.assertEqual(set(native_call['arguments']), set(INDEX[name]['args']))
                result = RUNTIME.validate(name, {'arguments': HOST._substitute(native_call['arguments'], captures)},
                         catalog=CATALOG, invocation_context={'sequence': True},
                         reference_validator=lambda value, _: isinstance(value, dict) and '$ref' in value)
                self.assertNotIn('error', result, (job['id'], result))
                context = CATALOG['functions'][name]['context']
                self.assertFalse(context['interactive'] or context['quarantined'] or context['unsupported_reason'])
            request = RUNNER.render_typed_job(job, captures)
            self.assertIsNone(POLICY.check(request['command'], request['params'], sdk_catalog=CATALOG['functions']))
            if 'capture' in job:
                key = job['capture']['name']
                self.assertNotIn(key, captures)
                assertion = next(a for a in job['assertions'] if a['path'] == job['capture']['path'])
                captures[key] = HOST.FIXTURE_UUID if assertion.get('valid_uuid') else 1

    def test_silent_void_setter_noops_are_caught_by_later_reads(self):
        for family, names in {
            'resource_symbols': ['SetName', 'HMove', 'HRotate'],
            'resource_textures': ['SetTextureSize', 'SetTextureRefN'],
            'resource_lights': ['SetLightLocation', 'SetLightInfo', 'SetLightColorRGB',
                                'SetLightDirection', 'SetLightFalloff'],
            'resource_gradient_segments': ['SetGradientData', 'InsertGradientSegment', 'SetGradientSpotPosition',
                                           'SetGradientSpotColor', 'SetGradientMidpointPosition', 'RemoveGradientSegment'],
            'resource_gradient_opacity': ['InsertGradientData', 'SetGradientDataN', 'SetGradientOpacity'],
        }.items():
            for name in names:
                with self.subTest(family=family, mutation=name):
                    results = run_model(RESOURCE.resource_fixtures('noop', [family]), ResourceModel('noop:' + name))
                    self.assertFalse(results[-1][1], name)
                    self.assertNotIn('error', results[-1][2], results[-1])

    def test_cross_object_writes_are_caught_even_when_target_readback_is_correct(self):
        for family, names in {
            'resource_symbols': ['HMove', 'HRotate'],
            'resource_textures': ['SetTextureRefN', 'SetTextureSize'],
            'resource_lights': ['SetLightLocation', 'SetLightInfo', 'SetLightColorRGB',
                                'SetLightDirection', 'SetLightFalloff'],
            'resource_gradient_segments': ['SetGradientData', 'InsertGradientSegment', 'SetGradientSpotPosition',
                                           'SetGradientSpotColor', 'SetGradientMidpointPosition', 'RemoveGradientSegment'],
            'resource_gradient_opacity': ['InsertGradientData', 'SetGradientDataN', 'SetGradientOpacity'],
        }.items():
            for name in names:
                with self.subTest(family=family, mutation=name):
                    results = run_model(RESOURCE.resource_fixtures('isolation', [family]), ResourceModel('leak:' + name))
                    self.assertFalse(results[-1][1], name)
                    self.assertNotIn('error', results[-1][2], results[-1])

    def test_symbol_identity_texture_parts_and_light_units_fail_on_plausible_wrong_results(self):
        for family, fault in [('resource_symbols', 'wrong_symbol_definition'),
                              ('resource_textures', 'wrong_texture_part'),
                              ('resource_lights', 'rgb_8bit'),
                              ('resource_lights', 'direction_axis_swap'),
                              ('resource_lights', 'falloff_axis_swap'),
                              ('resource_lights', 'contains_always_true')]:
            with self.subTest(fault=fault):
                results = run_model(RESOURCE.resource_fixtures('faults', [family]), ResourceModel(fault))
                self.assertFalse(results[-1][1], fault)

    def test_gradient_reordering_units_and_return_shape_mutations_are_detected(self):
        for family, fault in [('resource_gradient_segments', 'gradient_no_reorder'),
                              ('resource_gradient_segments', 'gradient_stale_index'),
                              ('resource_gradient_segments', 'gradient_rgb_16bit'),
                              ('resource_gradient_segments', 'gradient_absolute_midpoint'),
                              ('resource_gradient_opacity', 'gradient_opacity_fraction'),
                              ('resource_gradient_opacity', 'gradient_extra_success_flag')]:
            with self.subTest(fault=fault):
                results = run_model(RESOURCE.resource_fixtures('gradient_faults', [family]), ResourceModel(fault))
                self.assertFalse(results[-1][1], results[-1])

    def test_gradient_native_inputs_stay_in_documented_domains_and_never_remove_endpoints(self):
        for family in ('resource_gradient_segments', 'resource_gradient_opacity'):
            jobs = RESOURCE.resource_fixtures('gradient_domains', [family])
            model, captures = ResourceModel(), {}
            for job in jobs:
                request = RUNNER.render_typed_job(job, captures)
                args, name = request['params']['arguments'], request['params']['name']
                if 'gradient' in args:
                    resource = model.GetObjectByUuid(args['gradient'])
                    self.assertEqual(resource.kind, 120)
                    if 'segmentIndex' in args:
                        self.assertTrue(1 <= args['segmentIndex'] <= len(resource.segments))
                    if name == 'RemoveGradientSegment':
                        self.assertGreater(len(resource.segments), 2)
                        position = resource.segments[args['segmentIndex'] - 1]['position']
                        self.assertTrue(0 < position < 1, 'Only inserted interior spots are removed')
                for key in ('spotPosition', 'midpointPosition', 'position'):
                    if key in args: self.assertTrue(0 <= args[key] <= 1)
                for key in ('red', 'green', 'blue'):
                    if key in args: self.assertTrue(0 <= args[key] <= 255)
                if 'opacity' in args: self.assertTrue(0 <= args['opacity'] <= 100)
                returned = RUNTIME.invoke(name, {'arguments': args}, vs_module=model, catalog=CATALOG)
                self.assertTrue(HOST.evaluate_native(job, returned)[0], (job['id'], returned))
                if 'capture' in job: captures[job['capture']['name']] = HOST._at(returned, job['capture']['path'])

    def test_gradient_families_cover_all_seventeen_named_apis_and_keep_six_exact_data_fields(self):
        jobs = RESOURCE.resource_fixtures('gradient_inventory', ['resource_gradient_segments', 'resource_gradient_opacity'])
        names = {job['name'] for job in jobs}
        expected = {'CreateGradient', 'GetNumGradientSegments', 'GetGradientData', 'GetGradientDataN',
                    'InsertGradientSegment', 'InsertGradientData', 'SetGradientData', 'SetGradientDataN',
                    'SetGradientSpotPosition', 'GetGradientSpotPosition', 'SetGradientSpotColor', 'GetGradientSpotColor',
                    'SetGradientMidpointPosition', 'GetGradientMidpointPosition', 'SetGradientOpacity',
                    'GetGradientOpacity', 'RemoveGradientSegment'}
        self.assertEqual(names - {'GetName', 'GetTypeN'}, expected)
        for job in jobs:
            if job['name'] == 'GetGradientDataN':
                value = job['assertions'][0]['equals']
                self.assertEqual(len(value), 6)
                self.assertTrue(all(type(item) in (int, float) for item in value))
        data_reads = [job['assertions'][0]['equals'] for job in jobs if job['name'] == 'GetGradientDataN']
        self.assertEqual(data_reads, [[0.25, 0.4, 0, 0, 255, 71], [0.25, 0.4, 255, 0, 0, 37],
                                     [0.25, 0.4, 255, 0, 0, 0], [0.25, 0.4, 255, 0, 0, 100],
                                     [0.25, 0.4, 255, 0, 0, 61], [0.75, 0.2, 0, 255, 0, 22],
                                     [0.25, 0.4, 0, 0, 255, 71]])

    def test_gradient_six_field_adapter_does_not_hide_wrong_color_or_opacity(self):
        jobs = RESOURCE.resource_fixtures('exact_fields', ['resource_gradient_opacity'])
        for fault in ('gradient_data_n_wrong_color', 'gradient_data_n_stale_opacity'):
            with self.subTest(fault=fault):
                results = run_model(jobs, ResourceModel(fault))
                self.assertFalse(results[-1][1])
                self.assertTrue(results[-1][0].endswith(':control_insert_data'))
                self.assertEqual(results[-1][2]['status'], 'ok')
                self.assertEqual(len(results[-1][2]['result']), 6)
                self.assertNotIn('compatibility', results[-1][2])
                self.assertEqual(results[-1][3][0]['expected']['equals'], [0.25, 0.4, 0, 0, 255, 71])
        # A spurious success Boolean remains a contract error, rather than
        # being silently discarded or accepted as equivalent native evidence.
        results = run_model(jobs, ResourceModel('gradient_extra_success_flag'))
        self.assertFalse(results[-1][1])
        self.assertEqual(results[-1][2]['code'], 'SDK_RESULT')

    def test_incomplete_fixtures_and_forward_readbacks_are_detected(self):
        for family in RESOURCE.FAMILIES:
            jobs = RESOURCE.resource_fixtures('incomplete', [family])
            mutation = next(job['id'] for job in jobs if job['phase'] in {'creation', 'mutation'})
            truncated = [job for job in jobs if mutation not in job.get('verifies_jobs', [])]
            with self.subTest(family=family), self.assertRaisesRegex(ValueError, 'Missing independent readback'):
                check_readback_links(truncated)
            malformed = copy.deepcopy(jobs)
            malformed[0]['verifies_jobs'] = [jobs[-1]['id']]
            with self.assertRaisesRegex(ValueError, 'Invalid separate-job'):
                check_readback_links(malformed)

    def test_plans_are_deterministic_independent_and_validate_selection(self):
        first = RESOURCE.resource_fixtures('alpha')
        self.assertEqual(first, RESOURCE.resource_fixtures('alpha'))
        first[0]['assertions'].clear()
        self.assertTrue(RESOURCE.resource_fixtures('alpha')[0]['assertions'])
        for value in ['', 'a/b', 'x' * 81, None, True]:
            with self.subTest(run_id=value), self.assertRaises(ValueError): RESOURCE.resource_fixtures(value)
        for selection in [[], ['unknown'], ['resource_lights'] * 2, 'resource_lights', [None], [[]]]:
            with self.subTest(selection=selection), self.assertRaises(ValueError): RESOURCE.resource_fixtures('id', selection)
        self.assertEqual(RESOURCE.resource_fixtures('alpha', list(reversed(RESOURCE.FAMILIES))),
                         [job for family in reversed(RESOURCE.FAMILIES) for job in RESOURCE.resource_fixtures('alpha', [family])])

    def test_documented_light_default_is_diagnostic_and_routine_initializes_explicit_baselines(self):
        self.assertIn('resource_light_defaults', RESOURCE.DIAGNOSTIC_FAMILIES)
        self.assertIn('resource_light_default_probe', RESOURCE.DIAGNOSTIC_FAMILIES)
        routine = RESOURCE.resource_fixtures('explicit', ['resource_lights'])
        results = run_model(routine, ResourceModel('host_light_default'))
        self.assertTrue(all(row[1] for row in results), results[-1])
        diagnostic = RESOURCE.resource_fixtures('documented', ['resource_light_defaults'])
        self.assertTrue(all(job.get('diagnostic_only') is True and job.get('known_issue') for job in diagnostic))
        self.assertTrue(all(not job.get('diagnostic_only') for job in routine))
        api_names = {item['name'] for job in diagnostic for item in job.get('calls', [job])}
        self.assertFalse(api_names & {'SetLightInfo', 'SetLightColorRGB'})
        defaults = [job for job in diagnostic if job.get('name') == 'GetLightInfo']
        self.assertEqual([job['assertions'][0]['equals'][1] for job in defaults], [75, 75, 75])
        results = run_model(diagnostic, ResourceModel('host_light_default'))
        self.assertFalse(results[-1][1])
        self.assertEqual(results[-1][2]['result'], [0, 100, False, False])
        self.assertEqual(results[-1][3][0]['expected']['equals'], [0, 75, False, False])
        for kind in range(3):
            baseline = next(job for job in routine if job['id'].endswith(':light_%d_set_baseline' % kind))
            later = next(job for job in routine if job['id'].endswith(':light_%d_baseline' % kind))
            self.assertEqual(baseline['name'], 'SetLightInfo')
            self.assertIn(baseline['id'], later['verifies_jobs'])

    def test_light_default_probe_observes_both_defaults_without_semantic_credit(self):
        jobs = RESOURCE.resource_fixtures('observed', ['resource_light_default_probe'])
        self.assertIn('resource_light_default_probe', RESOURCE.CHARACTERIZATION_FAMILIES)
        self.assertEqual(len(jobs), 51)
        self.assertTrue(all(job['coverage_kind'] == 'characterization' and
                            job['verification_dimension'] == 'characterization' and
                            job['diagnostic_only'] for job in jobs))
        observed = [job for job in jobs if job['id'].endswith('_observed_default')]
        self.assertEqual(len(observed), 3)
        for fault, brightness in [(None, 75), ('host_light_default', 100)]:
            with self.subTest(brightness=brightness):
                results = run_model(jobs, ResourceModel(fault))
                self.assertTrue(all(row[1] for row in results), results[-1])
                responses = {row[0]: row[2] for row in results}
                for kind, job in enumerate(observed):
                    self.assertEqual(responses[job['id']]['result'], [kind, brightness, False, False])
                    self.assertEqual(job['documented_brightness_percent'], 75)
        registry = load('light_probe_registry', 'tools/sdk_regression_suite.py')
        plan = registry.build_plan(str(ROOT / '.audit/VWX-MCP-SDK-TEST-light-probe.vwx'),
            run_id='observed', selected=['resource:resource_light_default_probe'])
        self.assertTrue(registry.validate_plan(plan))
        self.assertTrue(all(registry.coverage_kind(job) == 'characterization' for job in plan['jobs']))

    def test_light_default_probe_preserves_documented_oracle_and_uses_only_public_selectors(self):
        jobs = RESOURCE.resource_fixtures('contracts', ['resource_light_default_probe'])
        for job in jobs:
            if job.get('name') == 'GetObjectVariableBoolean':
                self.assertIn(job['arguments']['index'], (50, 53))
            elif job.get('name') == 'GetObjectVariableInt':
                self.assertEqual(job['arguments']['index'], 55)
            self.assertNotEqual(job.get('name'), 'GetObjectVariableReal')
        legacy = RESOURCE.resource_fixtures('contracts', ['resource_light_defaults'])
        defaults = [job for job in legacy if job.get('name') == 'GetLightInfo']
        self.assertEqual([job['assertions'][0]['equals'][1] for job in defaults], [75, 75, 75])
        self.assertTrue(all(job.get('verification_dimension') != 'characterization' for job in legacy))

    def test_light_default_probe_detects_noop_leak_and_getter_only_state(self):
        jobs = RESOURCE.resource_fixtures('faults', ['resource_light_default_probe'])
        for fault, failed_suffix in [('noop:SetLightInfo', 'light_probe_0_explicit_read'),
                                     ('leak:SetLightInfo', 'all_created_kind_0'),
                                     ('light_info_stale_selectors', 'light_probe_0_explicit_on')]:
            with self.subTest(fault=fault):
                results = run_model(jobs, ResourceModel(fault))
                self.assertFalse(results[-1][1], results[-1])
                self.assertTrue(results[-1][0].endswith(failed_suffix), results[-1])
                self.assertNotIn('error', results[-1][2])

    def test_light_default_observation_still_rejects_wrong_kind_flags_and_bad_brightness(self):
        jobs = RESOURCE.resource_fixtures('responses', ['resource_light_default_probe'])
        job = next(job for job in jobs if job['id'].endswith('light_probe_0_observed_default'))
        for values in ([1, 100, False, False], [0, 100, True, False], [0, 100, False, True],
                       [0, -1, False, False], [0, float('nan'), False, False], [0, True, False, False]):
            with self.subTest(values=values):
                response = {'status': 'ok', 'function': 'GetLightInfo', 'result': values}
                self.assertFalse(HOST.evaluate_native(job, response)[0])

    def test_gradient_opacity_probe_preserves_original_oracle_and_never_awards_semantic_credit(self):
        jobs = RESOURCE.resource_fixtures('observed', ['resource_gradient_opacity_probe'])
        self.assertEqual(len(jobs), 99)
        self.assertIn('resource_gradient_opacity_probe', RESOURCE.CHARACTERIZATION_FAMILIES)
        self.assertIn('resource_gradient_opacity_probe', RESOURCE.DIAGNOSTIC_FAMILIES)
        self.assertTrue(all(job['coverage_kind'] == 'characterization' and
                            job['verification_dimension'] == 'characterization' and job['diagnostic_only'] for job in jobs))
        self.assertEqual(len([job for job in jobs if job['name'] == 'CreateGradient']), 3)
        observed = [job for job in jobs if 'requested_opacity_percent' in job]
        self.assertEqual(len(observed), 20)
        for setter in ('SetGradientOpacity', 'SetGradientDataN'):
            for getter in ('GetGradientOpacity', 'GetGradientDataN'):
                matching = [job for job in observed if job['observed_setter'] == setter and job['name'] == getter]
                self.assertEqual([job['requested_opacity_percent'] for job in matching], [0, 100, 75, 1, 37])
                self.assertTrue(all(job['assertions'][0]['range_inclusive'] == [0, 100] for job in matching))
        legacy = RESOURCE.resource_fixtures('original', ['resource_gradient_opacity'])
        reads = [job for job in legacy if job['id'].endswith(':opacity_0_read')]
        self.assertEqual(reads[0]['assertions'][0]['equals'], 0)
        self.assertNotEqual(reads[0].get('coverage_kind'), 'characterization')
        registry = load('gradient_probe_registry', 'tools/sdk_regression_suite.py')
        plan = registry.build_plan(str(ROOT / '.audit/VWX-MCP-SDK-TEST-gradient-probe.vwx'),
            run_id='observed', selected=['resource:resource_gradient_opacity_probe'])
        self.assertTrue(registry.validate_plan(plan))
        self.assertTrue(all(registry.coverage_kind(job) == 'characterization' for job in plan['jobs']))

    def test_gradient_probe_records_noop_setters_without_disguising_observed_values(self):
        jobs = RESOURCE.resource_fixtures('observed', ['resource_gradient_opacity_probe'])
        for fault in (None, 'noop:SetGradientOpacity', 'noop:SetGradientDataN'):
            with self.subTest(fault=fault):
                results = run_model(jobs, ResourceModel(fault))
                self.assertEqual(len(results), len(jobs))
                self.assertTrue(all(row[1] for row in results), results[-1])
                observed = {row[0]: row[2]['result'] for row in results}
                for role, setter in (('dedicated', 'SetGradientOpacity'), ('aggregate', 'SetGradientDataN')):
                    for value in (0, 100, 75, 1, 37):
                        expected = 37 if fault == 'noop:' + setter else value
                        key = 'design:resource_gradient_opacity_probe:' + role + '_' + str(value)
                        self.assertEqual(observed[key + '_opacity'], expected)
                        self.assertEqual(observed[key + '_data'], [0.25, 0.4, 19, 83, 151, expected])
                        self.assertEqual(observed[key + '_sibling_preserved'], [0.75, 0.6, 201, 37, 11, 71])

    def test_gradient_probe_captures_returned_index_and_detects_cross_object_or_wrong_segment_writes(self):
        jobs = RESOURCE.resource_fixtures('isolated', ['resource_gradient_opacity_probe'])
        for value in (0, 100, 75, 1, 37):
            setter = next(job for job in jobs if job['id'].endswith(':aggregate_' + str(value) + '_set'))
            key = setter['capture']['name']
            for suffix in ('_opacity', '_data'):
                read = next(job for job in jobs if job['id'].endswith(':aggregate_' + str(value) + suffix))
                self.assertEqual(read['arguments']['segmentIndex'], {'$capture': key})
        class WrongSegmentModel(ResourceModel):
            def SetGradientOpacity(self, gradient, segmentIndex, opacity):
                super().SetGradientOpacity(gradient, segmentIndex + 1, opacity)
        for model in (ResourceModel('leak:SetGradientOpacity'), ResourceModel('leak:SetGradientDataN'), WrongSegmentModel()):
            results = run_model(jobs, model)
            self.assertFalse(results[-1][1], results[-1])
            self.assertNotIn('error', results[-1][2])
            self.assertTrue('_control_' in results[-1][0] or '_sibling_preserved' in results[-1][0])

    def test_gradient_probe_rejects_nonfinite_out_of_domain_and_geometry_corruption(self):
        jobs = RESOURCE.resource_fixtures('strict', ['resource_gradient_opacity_probe'])
        job = next(job for job in jobs if job['id'].endswith(':dedicated_0_data'))
        for values in ([0.25, 0.4, 19, 83, 151, value] for value in (-1, 101, True, float('nan'), float('inf'))):
            self.assertFalse(HOST.evaluate_native(job, {'status': 'ok', 'function': 'GetGradientDataN', 'result': values})[0])
        for offset in range(5):
            values = [0.25, 0.4, 19, 83, 151, 37]
            values[offset] += 0.1 if offset < 2 else 1
            self.assertFalse(HOST.evaluate_native(job, {'status': 'ok', 'function': 'GetGradientDataN', 'result': values})[0])

    def test_aggregate_opacity_never_calls_dedicated_setter_and_keeps_exact_oracles(self):
        jobs = RESOURCE.resource_fixtures('aggregate', ['resource_gradient_aggregate_opacity'])
        self.assertEqual(len(jobs), 79)
        self.assertTrue(all(job['name'] != 'SetGradientOpacity' for job in jobs))
        self.assertTrue(all(job.get('coverage_kind') != 'characterization' for job in jobs))
        self.assertTrue(all('006-aa5521acbbbd' in job['evidence_basis'] for job in jobs))
        setters = [job for job in jobs if job['name'] == 'SetGradientDataN']
        self.assertEqual([job['arguments']['opacity'] for job in setters], [0, 100, 75, 1, 37])
        for job in setters:
            label = job['id'].rsplit(':', 1)[1].removesuffix('_set')
            value, capture = job['arguments']['opacity'], job['capture']['name']
            for suffix, expected in (('_data', [0.25, 0.4, 19, 83, 151, value]), ('_opacity', value)):
                read = next(item for item in jobs if item['id'].endswith(':' + label + '_target' + suffix))
                self.assertEqual(read['assertions'][0]['equals'], expected)
                self.assertEqual(read['arguments']['segmentIndex'], {'$capture': capture})
                self.assertIn(job['id'], read['verifies_jobs'])

    def test_aggregate_opacity_detects_noop_geometry_side_effect_and_cross_resource_writes(self):
        jobs = RESOURCE.resource_fixtures('aggregate_fault', ['resource_gradient_aggregate_opacity'])
        class PositionInsteadOfOpacity(ResourceModel):
            def SetGradientDataN(self, gradient, segmentIndex, spotPosition, midpointPosition, red, green, blue, opacity):
                return self._gradient_update('SetGradientDataN', gradient, segmentIndex, position=opacity)
        for model in (ResourceModel('noop:SetGradientDataN'), ResourceModel('leak:SetGradientDataN'), PositionInsteadOfOpacity()):
            results = run_model(jobs, model)
            self.assertFalse(results[-1][1], results[-1])
            self.assertNotIn('error', results[-1][2])
        # The broken dedicated binding is never touched, even when present.
        model = ResourceModel()
        model.SetGradientOpacity = lambda *args: self.fail('Unsafe dedicated setter invoked')
        results = run_model(jobs, model)
        self.assertEqual(len(results), len(jobs), results[-1])
        self.assertTrue(all(row[1] for row in results), results[-1])

    def test_dedicated_opacity_position_alias_stops_before_any_larger_value_is_sent(self):
        class PositionInsteadOfOpacity(ResourceModel):
            def __init__(self):
                super().__init__()
                self.opacity_calls = []
            def SetGradientOpacity(self, gradient, segmentIndex, opacity):
                self.opacity_calls.append(opacity)
                self._gradient_update('SetGradientOpacity', gradient, segmentIndex, position=opacity)
        model = PositionInsteadOfOpacity()
        results = run_model(RESOURCE.resource_fixtures('alias', ['resource_gradient_opacity_probe']), model)
        self.assertEqual(model.opacity_calls, [0])
        self.assertFalse(results[-1][1])
        self.assertTrue(results[-1][0].endswith(':dedicated_0_data'))
        self.assertEqual(results[-1][2]['result'], [0, 0.4, 19, 83, 151, 37])

    def test_long_run_ids_have_unique_bounded_names_and_all_resource_references_resolve(self):
        def names(jobs):
            return [item['arguments'].get('name', item['arguments'].get('symbolName'))
                    for job in jobs for item in job.get('calls', [job]) if item['name'] in {'SetName', 'BeginSym', 'CreateGradient'}]
        first_id, second_id = 'a'*79 + '1', 'a'*79 + '2'
        first, second = RESOURCE.resource_fixtures(first_id), RESOURCE.resource_fixtures(second_id)
        self.assertEqual(first, RESOURCE.resource_fixtures(first_id))
        self.assertEqual(len(names(first)), len(set(names(first))))
        self.assertTrue(set(names(first)).isdisjoint(names(second)))
        for name in names(first) + names(second):
            self.assertTrue(name.isascii())
            self.assertLessEqual(len(name), 60)
        for family in RESOURCE.FAMILIES:
            results = run_model(RESOURCE.resource_fixtures(first_id, [family]), ResourceModel())
            self.assertTrue(all(row[1] for row in results), (family, results[-1]))

    def test_no_global_or_interactive_operations_and_names_are_unique_between_runs(self):
        forbidden = {'SetActSymbol', 'NameClass', 'Layer', 'SetOrigin', 'SetOriginAbsolute',
                     'SetSelect', 'SetDSelect', 'SelectAll', 'DSelectAll', 'SetView', 'Projection',
                     'SetPref', 'SetClass', 'SetResourceTags', 'SetObjectTags', 'DoMenuTextByName'}
        names = []
        for run_id in ('first', 'second'):
            jobs = RESOURCE.resource_fixtures(run_id)
            named = set()
            for job in jobs:
                for native_call in job.get('calls', [job]):
                    self.assertNotIn(native_call['name'], forbidden)
                    if native_call['name'] in {'SetName', 'BeginSym'}:
                        name = native_call['arguments'].get('name', native_call['arguments'].get('symbolName'))
                        self.assertTrue(name.endswith('-' + run_id))
                        self.assertNotIn(name, named)
                        named.add(name)
            names.append(named)
        self.assertFalse(names[0] & names[1])


if __name__ == '__main__':
    unittest.main()
