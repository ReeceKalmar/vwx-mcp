"""Pending typed resource fixtures; building a plan never connects to a host.

Contracts: SDK 3200 vs.py and VectorScript Reference.xml; texture part constants
are TexturePartSDK in Interfaces/Base/RenderOptionsValues.h. Light types are
0 directional, 1 point, 2 spot; RGB is 0..65535; distance falloff is 0..2 and
angular falloff is 0..3. No legacy texture shader setters or bitmap dialogs.
Gradient segments are one-based; colors are 0..255, positions are 0..1 and
opacity is 0..100 per the reference. Only inserted interior spots are removed.
Every writable handle belongs to this family. No active symbol/class/layer,
selection, origin, view, default attributes, or existing resources are changed.
"""
import importlib.util
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location('sdk_resource_design', ROOT / 'tools/sdk_design_fixtures.py')
DESIGN = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(DESIGN)
_Fixture, call, capture = DESIGN._Fixture, DESIGN.call, DESIGN.capture
fixture_name = DESIGN.fixture_name
FAMILIES = ('resource_symbols', 'resource_textures', 'resource_lights', 'resource_light_defaults',
            'resource_gradient_segments', 'resource_gradient_opacity', 'resource_light_default_probe',
            'resource_gradient_opacity_probe', 'resource_gradient_aggregate_opacity')
DIAGNOSTIC_FAMILIES = ('resource_light_defaults', 'resource_light_default_probe', 'resource_gradient_opacity_probe')
CHARACTERIZATION_FAMILIES = ('resource_light_default_probe', 'resource_gradient_opacity_probe')


def _named(f, run_id, key, calls, index=None):
    calls = [calls] if isinstance(calls, dict) else list(calls)
    index = len(calls) - 1 if index is None else index
    name = fixture_name('SDK-Resource-' + key + '-', run_id)
    calls.append(call('SetName', h={'$ref': index}, name=name))
    made = f.create('create_' + key, calls, key, index=index)
    f.read('GetName', {'h': capture(key)}, name, label=key + '_identity', verifies=[made])
    return made, capture(key)


def _positive_index(f, key, api, arguments, verifies=()):
    f.add(key, native_call=call(api, **arguments), expected=[1, 2147483647],
          predicate='range_inclusive', captures=key, verifies=verifies)
    return capture(key)


def _symbol_angle(f, h, angle, label, verifies):
    # GetSymRot documents a direction in degrees without a canonical interval.
    # Host 882075 represents a symbol inserted at 270 degrees as -90 degrees.
    f.add(label, native_call=call('GetSymRot', symHd=h), expected=angle,
          predicate='angle_degrees', verifies=verifies)


def _resource_symbols(run_id):
    f = _Fixture('resource_symbols')
    names = {}
    for key, width, height in [('symbol_primary', 12, 8), ('symbol_control', 4, 6)]:
        name = names[key] = fixture_name('SDK-Resource-' + key + '-', run_id)
        made = f.create('define_' + key, [call('BeginSym', symbolName=name),
                        call('Rect', p1=[0, height], p2=[width, 0]), call('EndSym'),
                        call('GetObject', name=name)], key)
        f.read('GetName', {'h': capture(key)}, name, label=key + '_name', verifies=[made])
        child = key + '_child'
        found = f.create('contents_' + key, call('FInSymDef', sdHd=capture(key)), child)
        f.read('GetTypeN', {'h': capture(child)}, 3, label=key + '_child_type', verifies=[made, found])
        f.read('HWidth', {'h': capture(child)}, width, label=key + '_width', verifies=[made])
        f.read('HHeight', {'h': capture(child)}, height, label=key + '_height', verifies=[made])
        parent = key + '_parent'
        found_parent = f.create('parent_' + key, call('GetParent', h=capture(child)), parent)
        f.read('GetName', {'h': capture(parent)}, name, label=key + '_parent_name', verifies=[found_parent])

    instances = [('symbol_first', 'symbol_primary', [1600, 100], 0),
                 ('symbol_second', 'symbol_primary', [1650, -100], 90),
                 ('symbol_third', 'symbol_control', [-1700, 125.5], 270)]
    for key, definition, point, angle in instances:
        made, h = _named(f, run_id, key, [call('Symbol', symbolName=names[definition],
                                               p=point, rotationAngle=angle), call('LNewObj')])
        f.read('GetSymbolType', {'objectHandle': h}, 0, label=key + '_2d_type', verifies=[made])
        f.read('GetSymName', {'symHd': h}, names[definition], label=key + '_definition', verifies=[made])
        f.read('GetSymLoc', {'symHd': h}, point, label=key + '_insertion', verifies=[made])
        _symbol_angle(f, h, angle, key + '_rotation', [made])
    first, second = capture('symbol_first'), capture('symbol_second')
    moved = f.mutate('HMove', {'h': first, 'xOffset': -25.5, 'yOffset': 17.25}, label='move_first_instance')
    f.read('GetSymLoc', {'symHd': first}, [1574.5, 117.25], label='moved_first_insertion', verifies=[moved])
    _symbol_angle(f, first, 0, 'move_preserves_rotation', [moved])
    rotated = f.mutate('HRotate', {'h': first, 'center': [1574.5, 117.25], 'rotationAngle': 90},
                       label='rotate_first_instance')
    _symbol_angle(f, first, 90, 'rotated_first_angle', [rotated])
    f.read('GetSymLoc', {'symHd': first}, [1574.5, 117.25], label='rotation_preserves_insertion', verifies=[rotated])
    f.read('GetSymLoc', {'symHd': second}, [1650, -100], label='second_insertion_unchanged', verifies=[moved, rotated])
    _symbol_angle(f, second, 90, 'second_rotation_unchanged', [moved, rotated])
    f.read('HWidth', {'h': capture('symbol_primary_child')}, 12, label='definition_width_unchanged', verifies=[moved, rotated])
    f.read('HHeight', {'h': capture('symbol_primary_child')}, 8, label='definition_height_unchanged', verifies=[moved, rotated])
    return f.jobs


def _texture_identity(f, key, obj, part, name, verifies=(), resolve=False):
    index = _positive_index(f, key + '_index', 'GetTextureRefN',
                            {'obj': obj, 'texPartID': part, 'texLayerID': 0,
                             'resolveByClass': resolve}, verifies)
    f.read('Index2Name', {'index': index}, name, label=key + '_name', verifies=verifies)


def _resource_textures(run_id):
    f = _Fixture('resource_textures')
    textures, names = {}, {}
    for key, size in [('texture_a', 12.5), ('texture_b', 31.25)]:
        made, h = _named(f, run_id, key, call('CreateTexture'))
        name = names[key] = fixture_name('SDK-Resource-' + key + '-', run_id)
        sized = f.mutate('SetTextureSize', {'texture': h, 'newSize': size}, label=key + '_size')
        f.read('GetTextureSize', {'texture': h}, size, label=key + '_size_read', verifies=[made, sized])
        textures[key] = _positive_index(f, key + '_index', 'Name2Index', {'name': name})
        f.read('Index2Name', {'index': textures[key]}, name, label=key + '_index_identity', verifies=[made])
    for key, x in [('textured_target', 1800), ('textured_control', 1850)]:
        made, h = _named(f, run_id, key, [call('BeginXtrd', startDistance=0, endDistance=10),
                      call('Rect', p1=[x, 20], p2=[x + 30, 0]), call('EndXtrd'), call('LNewObj')])
        f.read('GetTypeN', {'h': h}, 24, label=key + '_extrude_type', verifies=[made])
        f.read('IsTextureableObject', {'obj': h}, True, label=key + '_supports_textures', verifies=[made])
        f.read('Get3DInfo', {'h': h}, [20, 30, 10], label=key + '_dimensions', verifies=[made])
    target, control = capture('textured_target'), capture('textured_control')
    control_set = f.mutate('SetTextureRefN', {'obj': control, 'textureRef': textures['texture_b'],
                          'texPartID': 3, 'texLayerID': 0}, label='control_overall_texture')
    _texture_identity(f, 'control_initial', control, 3, names['texture_b'], [control_set])
    for number, texture in enumerate(('texture_a', 'texture_b', 'texture_a')):
        changed = f.mutate('SetTextureRefN', {'obj': target, 'textureRef': textures[texture],
                           'texPartID': 3, 'texLayerID': 0}, label='target_assignment_%d' % number)
        _texture_identity(f, 'target_assignment_%d' % number, target, 3, names[texture], [changed])
        _texture_identity(f, 'target_resolved_%d' % number, target, 3, names[texture], [changed], resolve=True)
        _texture_identity(f, 'control_after_%d' % number, control, 3, names['texture_b'], [changed])
    # Documented extrude top/bottom/sides IDs; no unknown selectors or decals.
    for part, texture in [(4, 'texture_b'), (5, 'texture_a'), (6, 'texture_b')]:
        changed = f.mutate('SetTextureRefN', {'obj': target, 'textureRef': textures[texture],
                           'texPartID': part, 'texLayerID': 0}, label='extrude_part_%d' % part)
        _texture_identity(f, 'part_%d' % part, target, part, names[texture], [changed])
        _texture_identity(f, 'overall_after_part_%d' % part, target, 3, names['texture_a'], [changed])
    for key in ('textured_target', 'textured_control'):
        f.read('Get3DInfo', {'h': capture(key)}, [20, 30, 10], label=key + '_geometry_preserved')
    for key, size in [('texture_a', 12.5), ('texture_b', 31.25)]:
        f.read('GetTextureSize', {'texture': capture(key)}, size, label=key + '_resource_unchanged')
    return f.jobs


def _resource_lights(run_id):
    f = _Fixture('resource_lights')
    lights = []
    for kind, point in [(0, [1900, 20, 30]), (1, [1950.25, -20, 15.5]), (2, [-2000, 35, 75])]:
        key = 'light_%d' % kind
        made, h = _named(f, run_id, key, call('CreateLight', pXR=point[0], pYR=point[1],
                     pZR=point[2], lightType=kind, isOn=False, castShadow=False))
        lights.append(h)
        f.read('GetLightLocation', {'h': h}, point, label=key + '_position', verifies=[made])
        # CreateLight's documented 75% default disagrees with host 882075's
        # measured 100%. Test that discrepancy separately; establish explicit
        # baselines here so routine setter/isolation tests do not depend on it.
        info = f.mutate('SetLightInfo', {'h': h, 'lightType': kind, 'brightness': 75,
                        'isOn': False, 'castShadow': False}, label=key + '_set_baseline')
        f.read('GetLightInfo', {'h': h}, [kind, 75, False, False], label=key + '_baseline', verifies=[made, info])
        color = f.mutate('SetLightColorRGB', {'light': h, 'red': 65535, 'green': 65535, 'blue': 65535},
                         label=key + '_set_white')
        f.read('GetLightColorRGB', {'light': h}, [65535, 65535, 65535], label=key + '_white', verifies=[made, color])
    directional, point, spot = lights
    moved = f.mutate('SetLightLocation', {'h': point, 'p': [-12.25, 8.5], 'zValue': -3.75}, label='move_point_light')
    f.read('GetLightLocation', {'h': point}, [-12.25, 8.5, -3.75], label='point_light_moved', verifies=[moved])
    f.read('GetLightLocation', {'h': directional}, [1900, 20, 30], label='directional_position_unchanged', verifies=[moved])
    for number, (brightness, on, shadow) in enumerate([(0, False, True), (100, True, False), (37, True, True), (75, False, False)]):
        changed = f.mutate('SetLightInfo', {'h': point, 'lightType': 1, 'brightness': brightness,
                           'isOn': on, 'castShadow': shadow}, label='point_info_%d' % number)
        f.read('GetLightInfo', {'h': point}, [1, brightness, on, shadow], label='point_info_%d_read' % number, verifies=[changed])
        f.read('GetLightInfo', {'h': directional}, [0, 75, False, False], label='directional_info_%d_unchanged' % number, verifies=[changed])
    for number, rgb in enumerate(([65535, 0, 0], [0, 65535, 0], [0, 0, 65535], [0, 0, 0], [65535, 65535, 65535])):
        changed = f.mutate('SetLightColorRGB', dict(light=point, red=rgb[0], green=rgb[1], blue=rgb[2]), label='point_rgb_%d' % number)
        f.read('GetLightColorRGB', {'light': point}, list(rgb), label='point_rgb_%d_read' % number, verifies=[changed])
        f.read('GetLightColorRGB', {'light': spot}, [65535, 65535, 65535], label='spot_rgb_%d_unchanged' % number, verifies=[changed])
    direction_control = f.mutate('SetLightDirection', {'h': directional, 'panAngleR': 0.125,
                                'tiltAngleR': 0.625}, label='directional_direction_control')
    f.read('GetLightDirection', {'h': directional}, [0.125, 0.625], label='directional_direction_baseline', verifies=[direction_control])
    # These small positive angles are away from wrap/pole normalization. No
    # physical-unit conclusion is inferred from a setter/getter round trip.
    for number, angles in enumerate(([0.5, 0.25], [1.0, 0.75], [0, 0])):
        changed = f.mutate('SetLightDirection', {'h': spot, 'panAngleR': angles[0],
                           'tiltAngleR': angles[1]}, label='spot_direction_%d' % number)
        f.read('GetLightDirection', {'h': spot}, list(angles), label='spot_direction_%d_read' % number, verifies=[changed])
        f.read('GetLightLocation', {'h': spot}, [-2000, 35, 75], label='spot_position_%d_unchanged' % number, verifies=[changed])
        f.read('GetLightDirection', {'h': directional}, [0.125, 0.625], label='directional_angles_%d_unchanged' % number, verifies=[changed])
    falloff_control = f.mutate('SetLightFalloff', {'light': point, 'distFalloff': 2,
                              'angFalloff': 0}, label='point_falloff_control')
    f.read('GetLightFalloff', {'light': point}, [2, 0], label='point_falloff_baseline', verifies=[falloff_control])
    for number, falloff in enumerate(((0, 0), (1, 2), (2, 3), (0, 1))):
        changed = f.mutate('SetLightFalloff', {'light': spot, 'distFalloff': falloff[0],
                           'angFalloff': falloff[1]}, label='spot_falloff_%d' % number)
        f.read('GetLightFalloff', {'light': spot}, list(falloff), label='spot_falloff_%d_read' % number, verifies=[changed])
        f.read('GetLightInfo', {'h': spot}, [2, 75, False, False], label='spot_info_%d_preserved' % number, verifies=[changed])
        f.read('GetLightFalloff', {'light': point}, [2, 0], label='point_falloff_%d_unchanged' % number, verifies=[changed])
    for key, content, expected in [
            ('light_group', call('CreateLight', pXR=2050, pYR=0, pZR=25, lightType=1, isOn=False, castShadow=False), True),
            ('unlit_group', call('Rect', p1=[2100, 10], p2=[2120, 0]), False)]:
        made, h = _named(f, run_id, key, [call('BeginGroup'), content, call('EndGroup'), call('LNewObj')])
        f.read('ContainsLight', {'containerObject': h}, expected, label=key + '_contains_light', verifies=[made])
    return f.jobs


def _resource_light_defaults(run_id):
    """Keep the SDK-documented CreateLight defaults as an isolated diagnostic."""
    f = _Fixture('resource_light_defaults')
    for kind, point in ((0, [1900, 20, 30]), (1, [1950.25, -20, 15.5]), (2, [-2000, 35, 75])):
        key = 'default_diagnostic_light_' + str(kind)
        made, h = _named(f, run_id, key, call('CreateLight', pXR=point[0], pYR=point[1],
                     pZR=point[2], lightType=kind, isOn=False, castShadow=False))
        f.read('GetLightLocation', {'h': h}, point, label=key + '_position', verifies=[made])
        f.read('GetLightInfo', {'h': h}, [kind, 75, False, False], label=key + '_defaults', verifies=[made])
        f.read('GetLightColorRGB', {'light': h}, [65535, 65535, 65535], label=key + '_white', verifies=[made])
    return f.jobs


def _resource_light_default_probe(run_id):
    """Observe defaults, then distinguish explicit light state from defaults.

    Public VS selectors 50/53/55 independently expose on/shadow/kind; selector
    51 is deliberately excluded because ObjectVariables.h marks it nonpublic.
    The complete family is characterization, including its strict readbacks.
    """
    f = _Fixture('resource_light_default_probe')
    lights = []
    for kind, point in ((0, [2300, 20, 30]), (1, [2350.25, -20, 15.5]), (2, [-2400, 35, 75])):
        key = 'light_probe_' + str(kind)
        made, h = _named(f, run_id, key, call('CreateLight', pXR=point[0], pYR=point[1],
                      pZR=point[2], lightType=kind, isOn=False, castShadow=False))
        lights.append((kind, h))
        f.read('GetTypeN', {'h': h}, 81, label=key + '_type', verifies=[made])
        f.read('GetLightLocation', {'h': h}, point, label=key + '_position', verifies=[made])
        # A range only permits observing the disputed brightness; it does not
        # establish that either 75 or 100 implements the documented default.
        f.add(key + '_observed_default', native_call=call('GetLightInfo', h=h),
              expected=[0, 32767], predicate='range_inclusive', path=['result', 1])
        f.jobs[-1]['assertions'].extend([
            {'path': ['result', 0], 'equals': kind},
            {'path': ['result', 2], 'equals': False},
            {'path': ['result', 3], 'equals': False}])
        f.jobs[-1]['documented_brightness_percent'] = 75
        for api, selector, expected, label in (
                ('GetObjectVariableBoolean', 50, False, 'initial_on'),
                ('GetObjectVariableBoolean', 53, False, 'initial_shadow'),
                ('GetObjectVariableInt', 55, kind, 'initial_kind')):
            f.read(api, {'h': h, 'index': selector}, expected, label=key + '_' + label, verifies=[made])
        f.read('GetLightColorRGB', {'light': h}, [65535, 65535, 65535], label=key + '_white', verifies=[made])
        changed = f.mutate('SetLightInfo', {'h': h, 'lightType': kind, 'brightness': 75,
                           'isOn': True, 'castShadow': True}, label=key + '_explicit_75')
        f.read('GetLightInfo', {'h': h}, [kind, 75, True, True], label=key + '_explicit_read', verifies=[changed])
        for api, selector, expected, label in (
                ('GetObjectVariableBoolean', 50, True, 'explicit_on'),
                ('GetObjectVariableBoolean', 53, True, 'explicit_shadow'),
                ('GetObjectVariableInt', 55, kind, 'explicit_kind')):
            f.read(api, {'h': h, 'index': selector}, expected, label=key + '_' + label, verifies=[changed])
        f.read('GetLightLocation', {'h': h}, point, label=key + '_position_preserved', verifies=[changed])
        f.read('GetName', {'h': h}, fixture_name('SDK-Resource-' + key + '-', run_id),
               label=key + '_identity_preserved', verifies=[changed])
    for kind, h in lights:
        f.read('GetLightInfo', {'h': h}, [kind, 75, True, True], label='all_created_kind_' + str(kind))
    return f.jobs


def _gradient_resources(f, run_id):
    handles = []
    for role in ('target', 'control'):
        key = f.family + '_' + role
        name = fixture_name('SDK-Gradient-' + key + '-', run_id)
        created = f.create('create_' + role, call('CreateGradient', name=name), key)
        h = capture(key)
        handles.append(h)
        f.read('GetName', {'h': h}, name, label=role + '_name', verifies=[created])
        f.read('GetTypeN', {'h': h}, 120, label=role + '_gradient_type', verifies=[created])
        f.read('GetNumGradientSegments', {'gradient': h}, 2, label=role + '_initial_count', verifies=[created])
        # The XML reference explicitly defines the initial white/black spots
        # at 0 and 1. Midpoint/opacity defaults are not assumed here.
        for index, position, color in ((1, 0, [255, 255, 255]), (2, 1, [0, 0, 0])):
            f.read('GetGradientSpotPosition', {'gradient': h, 'segmentIndex': index}, position,
                   label='%s_initial_position_%d' % (role, index), verifies=[created])
            f.read('GetGradientSpotColor', {'gradient': h, 'segmentIndex': index}, color,
                   label='%s_initial_color_%d' % (role, index), verifies=[created])
    return handles


def _gradient_index(f, label, api, arguments, expected):
    key = f.family + '_' + label + '_index'
    changed = f.add(label, native_call=call(api, **arguments), expected=expected,
                    captures=key, phase='mutation')
    return changed, capture(key)


def _resource_gradient_segments(run_id):
    """Documented one-based sorted spots; valid edits never remove endpoints."""
    f = _Fixture('resource_gradient_segments')
    target, control = _gradient_resources(f, run_id)
    control_data = [0, 0.625, 0, 0, 255]
    for role, h, values in (('target', target, [0, 0.25, 255, 0, 0]),
                             ('control', control, control_data)):
        changed, index = _gradient_index(f, role + '_baseline', 'SetGradientData',
            dict(gradient=h, segmentIndex=1, spotPosition=values[0], midpointPosition=values[1],
                 red=values[2], green=values[3], blue=values[4]), 1)
        f.read('GetGradientData', {'gradient': h, 'segmentIndex': index}, values,
               label=role + '_baseline_read', verifies=[changed])
    first, green = _gradient_index(f, 'insert_green', 'InsertGradientSegment',
        dict(gradient=target, spotPosition=0.25, midpointPosition=0.4, red=0, green=255, blue=0), 2)
    f.read('GetNumGradientSegments', {'gradient': target}, 3, label='first_insert_count', verifies=[first])
    f.read('GetGradientData', {'gradient': target, 'segmentIndex': green}, [0.25, 0.4, 0, 255, 0],
           label='first_insert_data', verifies=[first])
    second, blue = _gradient_index(f, 'insert_blue', 'InsertGradientSegment',
        dict(gradient=target, spotPosition=0.75, midpointPosition=0.6, red=0, green=0, blue=255), 3)
    f.read('GetNumGradientSegments', {'gradient': target}, 4, label='second_insert_count', verifies=[second])
    f.read('GetGradientData', {'gradient': target, 'segmentIndex': blue}, [0.75, 0.6, 0, 0, 255],
           label='second_insert_data', verifies=[second])
    moved, green = _gradient_index(f, 'move_green_past_blue', 'SetGradientSpotPosition',
                                   dict(gradient=target, segmentIndex=green, position=0.875), 3)
    for label, index, position, color in (('moved_green', green, 0.875, [0, 255, 0]),
                                          ('blue_reindexed', 2, 0.75, [0, 0, 255])):
        f.read('GetGradientSpotPosition', {'gradient': target, 'segmentIndex': index}, position,
               label=label + '_position', verifies=[moved])
        f.read('GetGradientSpotColor', {'gradient': target, 'segmentIndex': index}, color,
               label=label + '_color', verifies=[moved])
    recolor = f.mutate('SetGradientSpotColor', dict(gradient=target, segmentIndex=green, red=255, green=255, blue=0),
                       label='green_to_yellow')
    f.read('GetGradientSpotColor', {'gradient': target, 'segmentIndex': green}, [255, 255, 0],
           label='yellow_color', verifies=[recolor])
    f.read('GetGradientSpotColor', {'gradient': target, 'segmentIndex': 2}, [0, 0, 255],
           label='blue_color_unchanged', verifies=[recolor])
    midpoint = f.mutate('SetGradientMidpointPosition', dict(gradient=target, segmentIndex=2, position=0.3),
                        label='blue_midpoint')
    f.read('GetGradientMidpointPosition', {'gradient': target, 'segmentIndex': 2}, 0.3,
           label='blue_midpoint_read', verifies=[midpoint])
    f.read('GetGradientSpotPosition', {'gradient': target, 'segmentIndex': 2}, 0.75,
           label='midpoint_preserves_spot', verifies=[midpoint])
    replaced, magenta = _gradient_index(f, 'reorder_with_all_data', 'SetGradientData',
        dict(gradient=target, segmentIndex=green, spotPosition=0.125, midpointPosition=0.2,
             red=255, green=0, blue=255), 2)
    f.read('GetGradientData', {'gradient': target, 'segmentIndex': magenta}, [0.125, 0.2, 255, 0, 255],
           label='reordered_magenta_data', verifies=[replaced])
    f.read('GetGradientSpotPosition', {'gradient': target, 'segmentIndex': 3}, 0.75,
           label='blue_survives_second_reorder', verifies=[replaced])
    removed = f.mutate('RemoveGradientSegment', dict(gradient=target, segmentIndex=3), label='remove_blue')
    f.read('GetNumGradientSegments', {'gradient': target}, 3, label='count_after_blue_removal', verifies=[removed])
    f.read('GetGradientData', {'gradient': target, 'segmentIndex': 2}, [0.125, 0.2, 255, 0, 255],
           label='magenta_survives_removal', verifies=[removed])
    removed_last = f.mutate('RemoveGradientSegment', dict(gradient=target, segmentIndex=2), label='remove_magenta')
    f.read('GetNumGradientSegments', {'gradient': target}, 2, label='minimum_two_segments', verifies=[removed_last])
    for index, position, color in ((1, 0, [255, 0, 0]), (2, 1, [0, 0, 0])):
        f.read('GetGradientSpotPosition', {'gradient': target, 'segmentIndex': index}, position,
               label='surviving_endpoint_%d_position' % index, verifies=[removed_last])
        f.read('GetGradientSpotColor', {'gradient': target, 'segmentIndex': index}, color,
               label='surviving_endpoint_%d_color' % index, verifies=[removed_last])
    all_changes = [first, second, moved, recolor, midpoint, replaced, removed, removed_last]
    f.read('GetNumGradientSegments', {'gradient': control}, 2, label='control_count_preserved', verifies=all_changes)
    f.read('GetGradientData', {'gradient': control, 'segmentIndex': 1}, control_data,
           label='control_data_preserved', verifies=all_changes)
    return f.jobs


def _resource_gradient_opacity(run_id):
    """Cross-check dedicated and aggregate getters on two independent resources."""
    f = _Fixture('resource_gradient_opacity')
    target, control = _gradient_resources(f, run_id)
    insertions = []
    for role, h, color, opacity in (('control', control, [0, 0, 255], 71),
                                    ('target', target, [255, 0, 0], 37)):
        changed, index = _gradient_index(f, role + '_insert', 'InsertGradientData',
            dict(gradient=h, spotPosition=0.25, midpointPosition=0.4,
                 red=color[0], green=color[1], blue=color[2], opacity=opacity), 2)
        insertions.append(changed)
        f.read('GetNumGradientSegments', {'gradient': h}, 3, label=role + '_insert_count', verifies=[changed])
        f.read('GetGradientDataN', {'gradient': h, 'segmentIndex': index}, [0.25, 0.4, *color, opacity],
               label=role + '_insert_data', verifies=[changed])
        f.read('GetGradientOpacity', {'gradient': h, 'segmentIndex': index}, opacity,
               label=role + '_insert_opacity', verifies=[changed])
    changes = []
    for opacity in (0, 100, 61):
        changed = f.mutate('SetGradientOpacity', dict(gradient=target, segmentIndex=2, opacity=opacity),
                           label='opacity_%d' % opacity)
        changes.append(changed)
        f.read('GetGradientOpacity', {'gradient': target, 'segmentIndex': 2}, opacity,
               label='opacity_%d_read' % opacity, verifies=[changed])
        f.read('GetGradientDataN', {'gradient': target, 'segmentIndex': 2}, [0.25, 0.4, 255, 0, 0, opacity],
               label='opacity_%d_other_fields_preserved' % opacity, verifies=[changed])
        f.read('GetGradientOpacity', {'gradient': control, 'segmentIndex': 2}, 71,
               label='opacity_%d_control_unchanged' % opacity, verifies=[changed])
    changed, index = _gradient_index(f, 'replace_with_opacity', 'SetGradientDataN',
        dict(gradient=target, segmentIndex=2, spotPosition=0.75, midpointPosition=0.2,
             red=0, green=255, blue=0, opacity=22), 2)
    changes.append(changed)
    f.read('GetGradientDataN', {'gradient': target, 'segmentIndex': index}, [0.75, 0.2, 0, 255, 0, 22],
           label='all_fields_read', verifies=[changed])
    f.read('GetGradientData', {'gradient': target, 'segmentIndex': index}, [0.75, 0.2, 0, 255, 0],
           label='legacy_getter_agrees', verifies=[changed])
    f.read('GetGradientOpacity', {'gradient': target, 'segmentIndex': index}, 22,
           label='dedicated_opacity_agrees', verifies=[changed])
    f.read('GetGradientDataN', {'gradient': control, 'segmentIndex': 2}, [0.25, 0.4, 0, 0, 255, 71],
           label='control_all_fields_preserved', verifies=insertions + changes)
    return f.jobs


def _resource_gradient_opacity_probe(run_id):
    """Observe both opacity setters with independent resources and sibling spots.

    A percent-range assertion records a disputed output without endorsing it.
    All other data remains literal and strict; the original semantic fixture
    continues to require the requested opacity. No fallback is performed here.
    """
    f = _Fixture('resource_gradient_opacity_probe')
    resources = {}
    primary = [0.25, 0.4, 19, 83, 151, 37]
    sibling = [0.75, 0.6, 201, 37, 11, 71]
    control_primary = [0.3, 0.45, 23, 171, 41, 53]
    control_sibling = [0.8, 0.55, 81, 99, 177, 89]
    for role in ('dedicated', 'aggregate', 'control'):
        key = f.family + '_' + role
        name = fixture_name('SDK-Gradient-' + key + '-', run_id)
        created = f.create('create_' + role, call('CreateGradient', name=name), key)
        h = capture(key)
        resources[role] = (h, name)
        f.read('GetName', {'h': h}, name, label=role + '_name', verifies=[created])
        f.read('GetTypeN', {'h': h}, 120, label=role + '_type', verifies=[created])
        f.read('GetNumGradientSegments', {'gradient': h}, 2, label=role + '_initial_count', verifies=[created])
        values = (control_primary, control_sibling) if role == 'control' else (primary, sibling)
        for index, data in enumerate(values, 2):
            changed, inserted = _gradient_index(f, role + '_insert_' + str(index), 'InsertGradientData',
                dict(gradient=h, spotPosition=data[0], midpointPosition=data[1],
                     red=data[2], green=data[3], blue=data[4], opacity=data[5]), index)
            f.read('GetGradientDataN', {'gradient': h, 'segmentIndex': inserted}, data,
                   label=role + '_baseline_data_' + str(index), verifies=[changed])
            f.read('GetGradientOpacity', {'gradient': h, 'segmentIndex': inserted}, data[5],
                   label=role + '_baseline_opacity_' + str(index), verifies=[changed])
        f.read('GetNumGradientSegments', {'gradient': h}, 4, label=role + '_populated_count')

    for role, setter in (('dedicated', 'SetGradientOpacity'), ('aggregate', 'SetGradientDataN')):
        h = resources[role][0]
        changes = []
        for opacity in (0, 100, 75, 1, 37):
            label = role + '_' + str(opacity)
            args = dict(gradient=h, segmentIndex=2, opacity=opacity)
            if setter == 'SetGradientDataN':
                args.update(spotPosition=primary[0], midpointPosition=primary[1],
                            red=primary[2], green=primary[3], blue=primary[4])
                changed, index = _gradient_index(f, label + '_set', setter, args, 2)
            else:
                changed = f.mutate(setter, args, label=label + '_set')
                index = 2
            changes.append(changed)
            for getter, path, suffix in (('GetGradientOpacity', ['result'], '_opacity'),
                                         ('GetGradientDataN', ['result', 5], '_data')):
                f.add(label + suffix, native_call=call(getter, gradient=h, segmentIndex=index),
                      expected=[0, 100], predicate='range_inclusive', path=path, verifies=[changed])
                f.jobs[-1]['requested_opacity_percent'] = opacity
                f.jobs[-1]['observed_setter'] = setter
                if getter == 'GetGradientDataN':
                    f.jobs[-1]['assertions'].extend(
                        {'path': ['result', offset], 'equals': value} for offset, value in enumerate(primary[:5]))
            f.read('GetGradientDataN', {'gradient': h, 'segmentIndex': 3}, sibling,
                   label=label + '_sibling_preserved', verifies=[changed])
            for index, data in ((2, control_primary), (3, control_sibling)):
                f.read('GetGradientDataN', {'gradient': resources['control'][0], 'segmentIndex': index}, data,
                       label=label + '_control_' + str(index), verifies=[changed])
        f.read('GetName', {'h': h}, resources[role][1], label=role + '_identity_preserved', verifies=changes)
        f.read('GetNumGradientSegments', {'gradient': h}, 4, label=role + '_count_preserved', verifies=changes)
    f.read('GetName', {'h': resources['control'][0]}, resources['control'][1], label='control_identity_preserved')
    f.read('GetNumGradientSegments', {'gradient': resources['control'][0]}, 4, label='control_count_preserved')
    return f.jobs


def _resource_gradient_aggregate_opacity(run_id):
    """Verify only the documented aggregate setter; never invoke the faulty API.

    The earlier dedicated-setter probe moved a stop instead of its opacity on
    host 882075. Fresh resources keep that corruption out of this independent
    test. Every requested opacity and every preserved field is an exact oracle.
    """
    f = _Fixture('resource_gradient_aggregate_opacity')
    target, control = _gradient_resources(f, run_id)
    primary = [0.25, 0.4, 19, 83, 151, 37]
    sibling = [0.75, 0.6, 201, 37, 11, 71]
    control_primary = [0.3, 0.45, 23, 171, 41, 53]
    control_sibling = [0.8, 0.55, 81, 99, 177, 89]
    for role, h, spots in (('target', target, (primary, sibling)),
                           ('control', control, (control_primary, control_sibling))):
        for index, data in enumerate(spots, 2):
            changed, inserted = _gradient_index(f, role + '_insert_' + str(index), 'InsertGradientData',
                dict(gradient=h, spotPosition=data[0], midpointPosition=data[1],
                     red=data[2], green=data[3], blue=data[4], opacity=data[5]), index)
            f.read('GetGradientDataN', {'gradient': h, 'segmentIndex': inserted}, data,
                   label=role + '_baseline_data_' + str(index), verifies=[changed])
            f.read('GetGradientOpacity', {'gradient': h, 'segmentIndex': inserted}, data[5],
                   label=role + '_baseline_opacity_' + str(index), verifies=[changed])
        f.read('GetNumGradientSegments', {'gradient': h}, 4, label=role + '_populated_count')
    changes = []
    for opacity in (0, 100, 75, 1, 37):
        label = 'aggregate_' + str(opacity)
        changed, index = _gradient_index(f, label + '_set', 'SetGradientDataN',
            dict(gradient=target, segmentIndex=2, spotPosition=primary[0], midpointPosition=primary[1],
                 red=primary[2], green=primary[3], blue=primary[4], opacity=opacity), 2)
        changes.append(changed)
        for suffix, h, spot, expected in (('target', target, index, [*primary[:5], opacity]),
                                          ('sibling', target, 3, sibling),
                                          ('control_primary', control, 2, control_primary),
                                          ('control_sibling', control, 3, control_sibling)):
            f.read('GetGradientDataN', {'gradient': h, 'segmentIndex': spot}, expected,
                   label=label + '_' + suffix + '_data', verifies=[changed])
            f.read('GetGradientOpacity', {'gradient': h, 'segmentIndex': spot}, expected[5],
                   label=label + '_' + suffix + '_opacity', verifies=[changed])
    for role, h in (('target', target), ('control', control)):
        f.read('GetNumGradientSegments', {'gradient': h}, 4, label=role + '_count_preserved', verifies=changes)
        f.read('GetName', {'h': h}, fixture_name('SDK-Gradient-' + f.family + '_' + role + '-', run_id),
               label=role + '_identity_preserved', verifies=changes)
    return f.jobs


def resource_fixtures(run_id, families=None):
    """Return self-contained, pending fixture families without host access."""
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id):
        raise ValueError('Invalid run_id')
    if families is not None and not isinstance(families, (list, tuple)):
        raise ValueError('Select unique known fixture families')
    selected = list(FAMILIES if families is None else families)
    if not selected or any(type(item) is not str or item not in FAMILIES for item in selected) or len(set(selected)) != len(selected):
        raise ValueError('Select unique known fixture families')
    jobs = [job for family in selected for job in globals()['_' + family](run_id)]
    for job in jobs:
        job['evidence_basis'] = ('SDK 3200 vs.py and VectorScript Reference.xml; documented '
                                 'light/texture constants and later resource identity/state readbacks')
        if job['fixture_family'].startswith('resource_gradient_'):
            job['evidence_basis'] = ('SDK 3200 vs.py Python signatures and VectorScript Reference.xml: one-based sorted gradient spots, '
                                     '8-bit RGB, positions 0..1, opacity 0..100, and changed output indices after reordering. '
                                     'GetGradientDataN uses the six outputs in the SDK stub and VectorScript procedure, '
                                     'confirmed on host 882075 against independent GetGradientData and GetGradientOpacity reads '
                                     '(.audit/gradient-shape-native-20260926-a/result.json); its conflicting Python docstring Boolean is not fabricated')
        if job['fixture_family'] in DIAGNOSTIC_FAMILIES:
            job['diagnostic_only'] = True
        if job['fixture_family'] in ('resource_light_defaults', 'resource_light_default_probe'):
            job['prerequisites'].append('Explicitly select this diagnostic family; CreateLight defaults differ from SDK documentation on host 882075')
            job['known_issue'] = ('SDK reference documents white and 75% brightness; host 882075 GetLightInfo returned 100% for the fresh directional light. '
                                  'The documented 75% expectation is preserved; routine tests set explicit baselines')
        if job['fixture_family'] in CHARACTERIZATION_FAMILIES:
            job['verification_dimension'] = 'characterization'
            job['coverage_kind'] = 'characterization'
            job['prerequisites'].append('Keep this characterization separate from semantic native API coverage')
        if job['fixture_family'] == 'resource_light_default_probe':
            job['evidence_basis'] = ('SDK 3200 vs.py CreateLight/GetLightInfo/SetLightInfo; '
                                     'ObjectVariables.h public VS light selectors 50/53/55 and '
                                     'MiniCadCallBacks.h light kinds 0/1/2. Observed defaults are not semantic pass evidence')
            job['known_issue'] = ('CreateLight documents 75% brightness, but host 882075 returned 100% for a fresh directional light. '
                                  'Record defaults without endorsing either value; verify explicit 75% plus independent public on/shadow/kind selectors')
        if job['fixture_family'] == 'resource_gradient_opacity_probe':
            job['prerequisites'].append('Explicit diagnostic: only fresh gradients are used; inspect both recorded opacity getters before proposing a repair')
            job['known_issue'] = ('Host 882075 retained opacity37 and changed spot position0.25 to0 after SetGradientOpacity(..., 0). '
                                  'Do not run the uncorrected dedicated setter again or advance to values above1; the saved G006 probe '
                                  'stopped at its first strict geometry check. Use the independent aggregate-only family for diagnosis. '
                                  'Range checks are response characterization, not correct-setter evidence')
        if job['fixture_family'] == 'resource_gradient_aggregate_opacity':
            job['evidence_basis'] += ('; SetGradientDataN preserves five literal non-opacity fields while setting exact opacity0/100/75/1/37, '
                                      'with independent GetGradientOpacity and untouched sibling/resource controls. No SetGradientOpacity call '
                                      'occurs: its geometry side effect is preserved in .audit/rootcause-batch-20260926-g/006-aa5521acbbbd/result.json')
    return jobs
