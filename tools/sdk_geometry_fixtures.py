"""Analytic geometry regressions for the guarded, typed SDK test runner.

This module only designs pending cases. It never connects to Vectorworks and
never generates native arguments from a signature. Every family creates its own
named geometry, leaves it available for inspection, and inspects changes in a
later menu invocation. Coordinates are primary drawing units; no units, drawing
preferences, selection, active layer, or existing objects are changed.

Contracts were reviewed against SDK 3200 build 882699 SDKLib/Include/vs.py.
The NURBS family converts a valid line, retains the original, and queries its
degree before addressing its documented zero-based control points. No test
passes invalid handles, degenerate axes, zero scales, or unchecked indices to
native code. Invalid transport arguments belong in the adapter contract suite.
"""
import importlib.util
import math
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location('sdk_geometry_design', ROOT / 'tools/sdk_design_fixtures.py')
DESIGN = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(DESIGN)
_Fixture, call, capture = DESIGN._Fixture, DESIGN.call, DESIGN.capture

FAMILIES = ('geometry_rectangles', 'geometry_ovals', 'geometry_arcs',
            'geometry_lines', 'geometry_polygons', 'geometry_loci',
            'geometry_poly3d', 'geometry_extrudes', 'geometry_nurbs',
            'geometry_harea', 'geometry_arc_characterization',
            'geometry_arc_geometry_characterization', 'geometry_arc_repair_geometry')
CHARACTERIZATION_FAMILIES = ('geometry_arc_characterization', 'geometry_arc_geometry_characterization')
DIAGNOSTIC_FAMILIES = CHARACTERIZATION_FAMILIES


def _named(f, run_id, key, calls, index=None):
    """Capture a new object and give it an auditable run-specific name."""
    if isinstance(calls, dict):
        calls, index = [calls], 0
    else:
        calls = list(calls)
        index = len(calls) - 1 if index is None else index
    name = DESIGN.fixture_name('SDK-Geometry-' + key + '-', run_id)
    calls.append(call('SetName', h={'$ref': index}, name=name))
    made = f.create('create_' + key, calls, key, index=index)
    f.read('GetName', {'h': capture(key)}, name, label=key + '_name', verifies=[made])
    return made, capture(key)


def _rect(f, run_id, key, box):
    return _named(f, run_id, key, [call('Rect', p1=list(box[0]), p2=list(box[1])), call('LNewObj')])


def _line(f, run_id, key, start, end):
    return _named(f, run_id, key, [call('MoveTo', p=list(start)), call('LineTo', p=list(end)), call('LNewObj')])


def _read_metrics(f, h, label, *, area, perimeter, center=None, box=None, verifies=()):
    for name, arguments, expected in (
            ('HAreaN', {'ObjectHandle': h}, area), ('HPerim', {'h': h}, perimeter),
            ('HPerimN', {'ObjectHandle': h}, perimeter)):
        f.read(name, arguments, expected, label=label + '_' + name, verifies=verifies)
    if center is not None:
        f.read('HCenter', {'h': h}, center, label=label + '_center', verifies=verifies)
    if box is not None:
        f.read('GetBBox', {'h': h}, box, label=label + '_bbox', verifies=verifies)


def _rectangles(run_id):
    f = _Fixture('geometry_rectangles')
    # Signed coordinates, fractional dimensions, extreme aspect ratio, and a
    # large translation are geometrically distinct from the origin rectangle.
    for key, box, area, perimeter, center in (
            ('signed_rect', ((-30, -10), (-10, -40)), 600, 100, [-20, -25]),
            ('fractional_rect', ((0.25, 0.75), (0.75, 0.5)), 0.125, 1.5, [0.5, 0.625]),
            ('thin_rect', ((40, 64), (40.125, 0)), 8, 128.25, [40.0625, 32]),
            ('far_rect', ((1000000, 1000020), (1000030, 1000000)), 600, 100, [1000015, 1000010])):
        made, h = _rect(f, run_id, key, box)
        _read_metrics(f, h, key, area=area, perimeter=perimeter, center=center,
                      box=[list(p) for p in box], verifies=[made])

    made, h = _rect(f, run_id, 'transform_rect', ((0, 20), (30, 0)))
    _read_metrics(f, h, 'initial', area=600, perimeter=100, verifies=[made])
    moved = f.mutate('HMove', {'h': h, 'xOffset': -45.5, 'yOffset': 12.25}, label='translate_signed')
    _read_metrics(f, h, 'translated', area=600, perimeter=100, center=[-30.5, 22.25],
                  box=[[-45.5, 32.25], [-15.5, 12.25]], verifies=[moved])
    rotated = f.mutate('HRotate', {'h': h, 'center': [-30.5, 22.25], 'rotationAngle': 90}, label='rotate_quarter_turn')
    _read_metrics(f, h, 'rotated', area=600, perimeter=100, center=[-30.5, 22.25],
                  box=[[-40.5, 37.25], [-20.5, 7.25]], verifies=[rotated])
    restored = f.mutate('HRotate', {'h': h, 'center': [-30.5, 22.25], 'rotationAngle': -90}, label='rotate_inverse')
    f.read('GetBBox', {'h': h}, [[-45.5, 32.25], [-15.5, 12.25]], label='inverse_rotation_bbox', verifies=[restored])
    scaled = f.mutate('HScale2D', {'h': h, 'centerX': -30.5, 'centerY': 22.25,
                                 'scaleX': 2, 'scaleY': 0.5, 'scaleText': False}, label='anisotropic_scale')
    _read_metrics(f, h, 'anisotropic', area=600, perimeter=140, center=[-30.5, 22.25],
                  box=[[-60.5, 27.25], [-0.5, 17.25]], verifies=[scaled])
    uniform = f.mutate('HScale2D', {'h': h, 'centerX': -30.5, 'centerY': 22.25,
                                  'scaleX': 2, 'scaleY': 2, 'scaleText': False}, label='uniform_scale')
    _read_metrics(f, h, 'uniform', area=2400, perimeter=280, center=[-30.5, 22.25],
                  box=[[-90.5, 32.25], [29.5, 12.25]], verifies=[uniform])
    identity = f.mutate('HScale2D', {'h': h, 'centerX': 0, 'centerY': 0,
                                   'scaleX': 1, 'scaleY': 1, 'scaleText': False}, label='identity_scale')
    f.read('GetBBox', {'h': h}, [[-90.5, 32.25], [29.5, 12.25]], label='identity_preserves_bbox', verifies=[identity])
    return f.jobs


def _ovals(run_id):
    f = _Fixture('geometry_ovals')
    for key, box, area, center in (
            ('unit_circle', ((-1, 1), (1, -1)), math.pi, [0, 0]),
            ('offset_circle', ((-35, -5), (-25, -15)), 25 * math.pi, [-30, -10]),
            ('ellipse', ((100, 20), (140, 0)), 200 * math.pi, [120, 10])):
        made, h = _named(f, run_id, key, [call('Oval', p1=list(box[0]), p2=list(box[1])), call('LNewObj')])
        f.read('HAreaN', {'ObjectHandle': h}, area, label=key + '_area', verifies=[made])
        f.read('HCenter', {'h': h}, center, label=key + '_center', verifies=[made])
        f.read('GetBBox', {'h': h}, [list(p) for p in box], label=key + '_bbox', verifies=[made])
        if key != 'ellipse':
            radius = (box[1][0] - box[0][0]) / 2
            f.read('HPerimN', {'ObjectHandle': h}, 2 * math.pi * radius, label=key + '_circumference')

    h = capture('ellipse')
    rotated = f.mutate('HRotate', {'h': h, 'center': [120, 10], 'rotationAngle': 90}, label='rotate_ellipse')
    f.read('GetBBox', {'h': h}, [[110, 30], [130, -10]], label='rotated_ellipse_axes', verifies=[rotated])
    f.read('HAreaN', {'ObjectHandle': h}, 200 * math.pi, label='ellipse_rotation_preserves_area', verifies=[rotated])
    scaled = f.mutate('HScale2D', {'h': h, 'centerX': 120, 'centerY': 10,
                                 'scaleX': 0.5, 'scaleY': 2, 'scaleText': False}, label='scale_ellipse')
    f.read('GetBBox', {'h': h}, [[115, 50], [125, -30]], label='scaled_ellipse_axes', verifies=[scaled])
    f.read('HAreaN', {'ObjectHandle': h}, 200 * math.pi, label='ellipse_determinant_one_area', verifies=[scaled])

    made, rounded = _named(f, run_id, 'rounded_rect', [call('RRect', p1=[200, 20], p2=[240, 0], Diam=[4, 4]), call('LNewObj')])
    # Four radius-2 quadrants replace four 2-by-2 squares.
    _read_metrics(f, rounded, 'rounded', area=800 - 16 + 4 * math.pi,
                  perimeter=120 - 16 + 4 * math.pi, center=[220, 10],
                  box=[[200, 20], [240, 0]], verifies=[made])
    return f.jobs


def _arcs(run_id):
    f = _Fixture('geometry_arcs')
    for key, start, sweep in (('quarter_arc', 0, 90), ('offset_arc', 30, 90), ('major_arc', 45, 270)):
        made, h = _named(f, run_id, key, [call('Arc', p1=[-10, 10], p2=[10, -10], StartAngle=start, ArcAngle=sweep), call('LNewObj')])
        f.read('GetArc', {'h': h}, [start, sweep], label=key + '_angles', verifies=[made])
        f.read('HCenter', {'h': h}, [0, 0], label=key + '_center', verifies=[made])
    h = capture('quarter_arc')
    changed = f.mutate('SetArc', {'h': h, 'startAngle': 90, 'arcAngle': 180}, label='change_start_and_sweep')
    f.read('GetArc', {'h': h}, [90, 180], label='changed_arc_angles', verifies=[changed])
    f.read('HCenter', {'h': h}, [0, 0], label='changing_angles_preserves_center', verifies=[changed])
    moved = f.mutate('HMove', {'h': h, 'xOffset': 50, 'yOffset': -25}, label='translate_arc')
    f.read('GetArc', {'h': h}, [90, 180], label='translation_preserves_arc_angles', verifies=[moved])
    f.read('HCenter', {'h': h}, [50, -25], label='translated_arc_center', verifies=[moved])
    rotated = f.mutate('HRotate', {'h': h, 'center': [50, -25], 'rotationAngle': 90}, label='rotate_arc')
    f.read('GetArc', {'h': h}, [180, 180], label='rotation_changes_start_not_sweep', verifies=[rotated])
    return f.jobs


def _arc_characterization(run_id):
    """Fresh discriminating SetArc probes; do not award semantic API credit.

    Both the Python reference and GS_SetArcAnglesN require degree-valued
    start/sweep angles. Preserve GetArc after separate jobs to distinguish
    constructor, scalar representation, changed component, and reset behavior.
    A successful void setter is not proof that its intended effect occurred.
    """
    f = _Fixture('geometry_arc_characterization')
    variants = (('square_int', 'Arc', 90, 180, None),
                ('square_float', 'Arc', 90.0, 180.0, None),
                ('center_float', 'ArcByCenter', 90.0, 180.0, None),
                ('square_reset_bbox', 'Arc', 90.0, 180.0, 'ResetBBox'),
                ('square_reset_object', 'Arc', 90.0, 180.0, 'ResetObject'),
                ('sweep_only', 'Arc', 0.0, 180.0, None),
                ('start_only', 'Arc', 90.0, 90.0, None))
    for index, (label, constructor, start, sweep, reset) in enumerate(variants):
        center = [index*40, -200]
        creation = (call('Arc', p1=[center[0]-10, center[1]+10], p2=[center[0]+10, center[1]-10],
                         StartAngle=0.0, ArcAngle=90.0) if constructor == 'Arc' else
                    call('ArcByCenter', x=center[0], y=center[1], radius=10.0, startAngl=0.0, sweepAngle=90.0))
        made, h = _named(f, run_id, 'arc_probe_' + label, [creation, call('LNewObj')])
        f.read('GetTypeN', {'h': h}, 6, label=label + '_arc_type', verifies=[made])
        f.read('GetArc', {'h': h}, [0, 90], label=label + '_initial_angles', verifies=[made])
        changed = f.mutate('SetArc', {'h': h, 'startAngle': start, 'arcAngle': sweep}, label=label + '_set')
        mutations = [changed]
        if reset:
            mutations.append(f.mutate(reset, {'h': h} if reset == 'ResetBBox' else {'objectHandle': h},
                                      label=label + '_reset'))
        f.add(label + '_observed_angles', native_call=call('GetArc', h=h), expected=[-360, 360],
              path=['result', 0], predicate='range_inclusive', verifies=mutations)
        f.jobs[-1]['assertions'].append({'path': ['result', 1], 'range_inclusive': [-360, 360]})
        f.jobs[-1]['measurement_context'] = {'constructor': constructor, 'reset': reset,
                                           'requested_angles_degrees': [start, sweep],
                                           'initial_angles_degrees': [0, 90]}
        f.read('HCenter', {'h': h}, center, label=label + '_center_preserved', verifies=mutations)
    return f.jobs


def _arc_geometry_characterization(run_id):
    """Separate a SetArc no-op from a stale angle getter using fresh controls.

    The original quarter arc, directly constructed target semicircle and
    setter candidate share coordinates but have independent names/handles.
    ConvertToNURBS preserves each arc. A later type-111 assertion must pass
    before the documented 0..1 length-fraction API is called; no knot count,
    curve parameter normalization or conversion-group layout is assumed.
    Analytic predictions accompany the observations, without semantic credit.
    """
    f = _Fixture('geometry_arc_geometry_characterization')
    center, radius = [320, -260], 10
    initial, target = [0, 90], [90, 180]
    fractions = (0.0, 0.5, 1.0)

    def point(angles, fraction):
        angle = math.radians(angles[0] + angles[1]*fraction)
        return [center[0] + radius*math.cos(angle), center[1] + radius*math.sin(angle), 0]

    for role, angles in (('quarter_control', initial), ('target_control', target), ('setter_candidate', initial)):
        key = 'arc_geometry_' + role
        made, h = _named(f, run_id, key, [call('ArcByCenter', x=center[0], y=center[1], radius=radius,
                                             startAngl=angles[0], sweepAngle=angles[1]), call('LNewObj')])
        f.read('GetTypeN', {'h': h}, 6, label=role + '_arc_type', verifies=[made])
        f.read('GetArc', {'h': h}, angles, label=role + '_initial_angles', verifies=[made])
        f.read('HCenter', {'h': h}, center, label=role + '_center', verifies=[made])
        changes = [made]
        if role == 'setter_candidate':
            changes.append(f.mutate('SetArc', {'h': h, 'startAngle': target[0], 'arcAngle': target[1]},
                                    label=role + '_set_angles'))
        intended = target if role == 'setter_candidate' else angles
        context = {'role': role, 'center': center, 'radius': radius,
                   'initial_angles_degrees': angles, 'intended_angles_degrees': intended,
                   'analytic_open_arc_length': radius*math.radians(intended[1])}
        f.add(role + '_observed_angles', native_call=call('GetArc', h=h), expected=[-360, 360],
              path=['result', 0], predicate='range_inclusive', verifies=changes)
        f.jobs[-1]['assertions'].append({'path': ['result', 1], 'range_inclusive': [-360, 360]})
        f.jobs[-1]['measurement_context'] = dict(context)
        # HPerimN is supplementary: collect its value without assuming whether
        # an open arc's perimeter includes a closing chord on this host.
        f.add(role + '_perimeter', native_call=call('HPerimN', ObjectHandle=h), expected=[0, 1e12],
              predicate='range_inclusive', verifies=changes)
        f.jobs[-1]['measurement_context'] = dict(context)
        converted, nurbs = _named(f, run_id, key + '_nurbs', call('ConvertToNURBS', h=h, keepOrig=True))
        f.read('GetTypeN', {'h': nurbs}, 111, label=role + '_nurbs_type', verifies=[converted])
        for index, fraction in enumerate(fractions):
            f.add(role + '_point_' + str(index),
                  native_call=call('GetPointAndParameterOnNurbsCurveAtGivenLength',
                                   inNurbCurve=nurbs, inPercentOfLength=fraction),
                  expected=True, path=['result', 0], verifies=changes + [converted])
            f.jobs[-1]['assertions'].extend(
                {'path': ['result', 1, axis], 'range_inclusive': [-1e12, 1e12]} for axis in range(3))
            f.jobs[-1]['assertions'].extend([
                {'path': ['result', 2], 'range_inclusive': [-1e12, 1e12]},
                {'path': ['result', 3], 'range_inclusive': [0, 2147483647]}])
            f.jobs[-1]['measurement_context'] = dict(context, length_fraction=fraction,
                analytic_intended_point=point(intended, fraction),
                analytic_unchanged_point=point(angles, fraction))
    return f.jobs


def _arc_repair_geometry(run_id):
    """Verify actual curve geometry independently of repaired angle readbacks.

    SDK SetArc uses degrees; the NURBS sampling API uses length fractions 0..1.
    For a positive circular arc the length fraction is also the angle fraction.
    Batch J separately measured the semicircle's open-arc perimeter and points.
    These new cases remain pending, and the old characterization is unchanged.
    Positive nondegenerate sweeps avoid assuming signed/zero/full-circle behavior.
    Every source read resolves its original captured UUID through the adapter's
    identity guard; post-mutation and post-conversion name checks preserve that
    identity rather than accepting a replacement with similar geometry.
    """
    f = _Fixture('geometry_arc_repair_geometry')
    cases = (('semicircle', [480, -260], 10, 90, 180),
             ('cross_zero', [540, -260], 12, 300, 120),
             ('small_sweep', [600, -260], 8, 30, 15),
             ('major_sweep', [660, -260], 9, 45, 270))

    def inspect_curve(key, h, center, radius, start, sweep, verifies, fractions):
        expected_name = DESIGN.fixture_name('SDK-Geometry-' + key + '-', run_id)
        f.read('GetTypeN', {'h': h}, 6, label=key + '_type', verifies=verifies)
        f.read('GetName', {'h': h}, expected_name, label=key + '_name_preserved', verifies=verifies)
        f.read('GetArc', {'h': h}, [start, sweep], label=key + '_angles', verifies=verifies)
        f.read('HCenter', {'h': h}, center, label=key + '_center', verifies=verifies)
        f.read('HPerimN', {'ObjectHandle': h}, radius*math.radians(sweep),
               label=key + '_open_length', verifies=verifies)
        converted, nurbs = _named(f, run_id, key + '_nurbs', call('ConvertToNURBS', h=h, keepOrig=True))
        f.read('GetTypeN', {'h': nurbs}, 111, label=key + '_nurbs_type', verifies=[converted])
        for index, fraction in enumerate(fractions):
            angle = math.radians(start + sweep*fraction)
            point = [center[0] + radius*math.cos(angle), center[1] + radius*math.sin(angle), 0]
            f.add(key + '_point_' + str(index),
                  native_call=call('GetPointAndParameterOnNurbsCurveAtGivenLength',
                                   inNurbCurve=nurbs, inPercentOfLength=fraction),
                  expected=True, path=['result', 0], verifies=list(verifies) + [converted])
            # Fixed absolute coordinate tolerance avoids granting a larger
            # error merely because the arc is far from the drawing origin.
            f.jobs[-1]['assertions'].append({'path': ['result', 1], 'equals': point,
                                             'abs_tol': 1e-6, 'rel_tol': 0})
        f.read('GetName', {'h': h}, expected_name, label=key + '_source_survives_conversion',
               verifies=[converted])
        f.read('HCenter', {'h': h}, center, label=key + '_source_center_survives_conversion',
               verifies=[converted])

    for label, center, radius, start, sweep in cases:
        handles, creations = {}, {}
        for role in ('control', 'candidate'):
            key = 'arc_repair_' + label + '_' + role
            made, h = _named(f, run_id, key, [call('ArcByCenter', x=center[0], y=center[1],
                                                 radius=radius, startAngl=0, sweepAngle=90), call('LNewObj')])
            handles[role], creations[role] = h, made
            f.read('GetTypeN', {'h': h}, 6, label=key + '_initial_type', verifies=[made])
            f.read('GetArc', {'h': h}, [0, 90], label=key + '_initial_angles', verifies=[made])
        changed = f.mutate('SetArc', {'h': handles['candidate'], 'startAngle': start, 'arcAngle': sweep},
                           label=label + '_change_angles')
        f.jobs[-1]['compatibility_caution'] = (
            'Build 882075 uses the disclosed VWXBridgeSetArc replacement; classify actual returned provenance, '
            'never credit that compatibility result as native Python SetArc success.')
        inspect_curve('arc_repair_' + label + '_candidate', handles['candidate'], center, radius, start, sweep,
                      [creations['candidate'], changed], (0.0, 0.25, 0.5, 0.75, 1.0))
        # A separate, originally coincident quarter arc must remain untouched.
        # Convert it after the mutation so a stale pre-mutation copy cannot hide
        # an accidental edit to the control object.
        inspect_curve('arc_repair_' + label + '_control', handles['control'], center, radius, 0, 90,
                      [creations['control'], changed], (0.0, 0.5, 1.0))
    return f.jobs


def _lines(run_id):
    f = _Fixture('geometry_lines')
    for key, start, end, length in (
            ('horizontal_line', [-20, -5], [30, -5], 50),
            ('vertical_line', [-7, -20], [-7, 30], 50),
            ('reverse_line', [30, 40], [0, 0], 50),
            ('fractional_line', [0.125, 0.25], [0.5, 0.75], 0.625)):
        made, h = _line(f, run_id, key, start, end)
        f.read('GetSegPt1', {'h': h}, start, label=key + '_start', verifies=[made])
        f.read('GetSegPt2', {'h': h}, end, label=key + '_end', verifies=[made])
        f.read('HLength', {'h': h}, length, label=key + '_length', verifies=[made])
    made, h = _line(f, run_id, 'transform_line', [10, 20], [40, 60])
    reflected, mirror = _named(f, run_id, 'reflected_line', call('MirrorN', h=h, dup=True,
                               p1=[0, 0], p2=[0, 1], preserveMatrix=True))
    f.read('GetSegPt1', {'h': mirror}, [-10, 20], label='reflected_start', verifies=[reflected])
    f.read('GetSegPt2', {'h': mirror}, [-40, 60], label='reflected_end', verifies=[reflected])
    f.read('HLength', {'h': mirror}, 50, label='reflection_preserves_length', verifies=[reflected])
    f.read('GetSegPt1', {'h': h}, [10, 20], label='reflection_preserves_source_start', verifies=[made, reflected])
    f.read('GetSegPt2', {'h': h}, [40, 60], label='reflection_preserves_source_end', verifies=[made, reflected])
    rotated = f.mutate('HRotate', {'h': h, 'center': [0, 0], 'rotationAngle': 90}, label='rotate_line_about_origin')
    f.read('GetSegPt1', {'h': h}, [-20, 10], label='rotated_line_start', verifies=[rotated])
    f.read('GetSegPt2', {'h': h}, [-60, 40], label='rotated_line_end', verifies=[rotated])
    f.read('HLength', {'h': h}, 50, label='line_rotation_preserves_length', verifies=[rotated])
    zero_move = f.mutate('HMove', {'h': h, 'xOffset': 0, 'yOffset': 0}, label='zero_translation')
    f.read('GetSegPt1', {'h': h}, [-20, 10], label='zero_translation_preserves_start', verifies=[zero_move])
    return f.jobs


def _polygon(f, run_id, key, points):
    calls = [call('BeginPoly')] + [call('AddPoint', p=list(p)) for p in points] + [call('EndPoly'), call('LNewObj')]
    index = len(calls) - 1
    calls.append(call('SetPolyClosed', polyHandle={'$ref': index}, isClosed=True))
    return _named(f, run_id, key, calls, index=index)


def _polygons(run_id):
    f = _Fixture('geometry_polygons')
    # Same right triangle, opposite winding: area magnitude and boundary
    # membership must agree. No self-intersection or coincident edges.
    vertices = [[-10, -10], [20, -10], [-10, 30]]
    for key, points in (('triangle_ccw', vertices), ('triangle_cw', vertices[::-1])):
        made, h = _polygon(f, run_id, key, points)
        f.read('GetVertNum', {'PolyHd': h}, 3, label=key + '_vertex_count', verifies=[made])
        f.read('IsPolyClosed', {'polyHandle': h}, True, label=key + '_closed', verifies=[made])
        _read_metrics(f, h, key, area=600, perimeter=120, verifies=[made])
        for label, point, expected in (('interior', [0, 0], True), ('outside', [20, 30], False),
                                       ('on_edge', [5, -10], True), ('at_vertex', [-10, -10], True)):
            f.read('PtInPoly', {'p': point, 'h': h}, expected, label=key + '_' + label)
    # Concave L has 16-by-12 outer box with the 10-by-8 upper-right corner absent.
    made, h = _polygon(f, run_id, 'concave_polygon', [[100, 0], [116, 0], [116, 4], [106, 4], [106, 12], [100, 12]])
    _read_metrics(f, h, 'concave', area=112, perimeter=56, verifies=[made])
    f.read('PtInPoly', {'p': [102, 10], 'h': h}, True, label='concave_inside_leg')
    f.read('PtInPoly', {'p': [112, 10], 'h': h}, False, label='concave_missing_corner')
    moved = f.mutate('HMove', {'h': h, 'xOffset': -100, 'yOffset': -20}, label='translate_concave')
    _read_metrics(f, h, 'concave_translated', area=112, perimeter=56, verifies=[moved])
    f.read('PtInPoly', {'p': [2, -10], 'h': h}, True, label='translated_containment', verifies=[moved])
    f.read('PtInPoly', {'p': [102, 10], 'h': h}, False, label='old_location_no_longer_inside', verifies=[moved])
    # Inserting a collinear point must change topology count, not metric area.
    inserted = f.mutate('InsertVertex', {'objectHandle': h, 'x': 8, 'y': -20,
                                        'beforeVertexNum': 2, 'vertexType': 0, 'arcRadius': 0}, label='insert_collinear')
    f.read('GetVertNum', {'PolyHd': h}, 7, label='collinear_vertex_count', verifies=[inserted])
    f.read('GetPolyPt', {'objectHd': h, 'index': 2}, [8, -20], label='collinear_vertex_coordinate', verifies=[inserted])
    _read_metrics(f, h, 'collinear_insert', area=112, perimeter=56, verifies=[inserted])
    removed = f.mutate('DelVertex', {'objectHd': h, 'vertexNum': 2}, label='remove_collinear')
    f.read('GetVertNum', {'PolyHd': h}, 6, label='restored_vertex_count', verifies=[removed])
    _read_metrics(f, h, 'collinear_remove', area=112, perimeter=56, verifies=[removed])
    return f.jobs


def _loci(run_id):
    f = _Fixture('geometry_loci')
    for key, point in (('locus_origin', [0, 0]), ('locus_signed', [-12.5, 25.25])):
        made, h = _named(f, run_id, key, [call('Locus', p=point), call('LNewObj')])
        f.read('GetLocPt', {'h': h}, point, label=key + '_point', verifies=[made])
    h = capture('locus_signed')
    moved = f.mutate('HMove', {'h': h, 'xOffset': 12.5, 'yOffset': -25.25}, label='move_locus_to_origin')
    f.read('GetLocPt', {'h': h}, [0, 0], label='locus_origin_after_move', verifies=[moved])
    made, h = _named(f, run_id, 'locus3d', [call('Locus3D', p=[-10, 20, -30]), call('LNewObj')])
    f.read('GetLocus3D', {'h': h}, [-10, 20, -30], label='locus3d_coordinates', verifies=[made])
    moved = f.mutate('Move3DObj', {'h': h, 'xDistance': 15, 'yDistance': -25, 'zDistance': 35}, label='translate_locus3d')
    f.read('GetLocus3D', {'h': h}, [5, -5, 5], label='translated_locus3d', verifies=[moved])
    return f.jobs


def _poly3d(run_id):
    f = _Fixture('geometry_poly3d')
    points = [[0, 0, 5], [30, 0, 5], [30, 20, 5], [0, 20, 5]]
    calls = [call('BeginPoly3D')] + [call('Add3DPt', p=p) for p in points] + [call('EndPoly3D'), call('LNewObj')]
    made, h = _named(f, run_id, 'planar3d_polygon', calls)
    f.read('GetVertNum', {'PolyHd': h}, 4, label='poly3d_vertex_count', verifies=[made])
    # SDK 3200 documents GetPolyPt3D's zero-based indices. Use interior indices
    # only; a mismatch is a reportable native contract failure, not a reason to
    # try an out-of-range boundary in a user's host.
    f.read('GetPolyPt3D', {'objectHd': h, 'index': 1}, [30, 0, 5], label='poly3d_interior_vertex', verifies=[made])
    f.read('GetPolyPt3D', {'objectHd': h, 'index': 2}, [30, 20, 5], label='poly3d_second_interior_vertex', verifies=[made])
    changed = f.mutate('SetPolyPt3D', {'objectHd': h, 'index': 1, 'p': [40, 0], 'zValue': 5}, label='change_poly3d_vertex')
    f.read('GetPolyPt3D', {'objectHd': h, 'index': 1}, [40, 0, 5], label='changed_poly3d_vertex', verifies=[changed])
    moved = f.mutate('Move3DObj', {'h': h, 'xDistance': -10, 'yDistance': 5, 'zDistance': -7}, label='translate_poly3d')
    f.read('GetPolyPt3D', {'objectHd': h, 'index': 1}, [30, 5, -2], label='translated_poly3d_vertex', verifies=[moved])
    return f.jobs


def _extrudes(run_id):
    f = _Fixture('geometry_extrudes')
    _, profile = _rect(f, run_id, 'asymmetric_profile', ((300, 20), (330, 0)))
    made, h = _named(f, run_id, 'asymmetric_extrude', call('HExtrude', objectH=profile, bottom=-5, top=5))
    f.read('GetTypeN', {'h': h}, 24, label='extrude_type', verifies=[made])
    f.read('Get3DInfo', {'h': h}, [20, 30, 10], label='extrude_distinct_dimensions', verifies=[made])
    f.read('Get3DCntr', {'h': h}, [[315, 10], 0], label='extrude_bounds_center', verifies=[made])
    f.read('Centroid3D', {'object': h}, [True, 315, 10, 0], label='extrude_mass_centroid', verifies=[made])
    moved = f.mutate('Move3DObj', {'h': h, 'xDistance': -315, 'yDistance': -10, 'zDistance': 25}, label='move_extrude')
    f.read('Get3DInfo', {'h': h}, [20, 30, 10], label='extrude_translation_preserves_dimensions', verifies=[moved])
    f.read('Centroid3D', {'object': h}, [True, 0, 0, 25], label='translated_mass_centroid', verifies=[moved])
    rotated = f.mutate('Set3DRot', {'h': h, 'xAngle': 0, 'yAngle': 0, 'zAngle': 90,
                                  'xDistance': 0, 'yDistance': 0, 'zDistance': 25}, label='rotate_extrude_z')
    f.read('Get3DInfo', {'h': h}, [30, 20, 10], label='z_rotation_swaps_plan_dimensions', verifies=[rotated])
    f.read('Centroid3D', {'object': h}, [True, 0, 0, 25], label='rotation_preserves_centroid', verifies=[rotated])
    scaled = f.mutate('HScale3D', {'h': h, 'centerX': 0, 'centerY': 0, 'centerZ': 25,
                                  'scaleX': 2, 'scaleY': 0.5, 'scaleZ': 3}, label='scale_extrude_3d')
    f.read('Get3DInfo', {'h': h}, [15, 40, 30], label='scaled_3d_dimensions', verifies=[scaled])
    f.read('Centroid3D', {'object': h}, [True, 0, 0, 25], label='centered_scale_preserves_centroid', verifies=[scaled])
    return f.jobs


def _nurbs(run_id):
    f = _Fixture('geometry_nurbs')
    _, line = _line(f, run_id, 'nurbs_source_line', [0, 0], [30, 40])
    made, h = _named(f, run_id, 'linear_nurbs', call('ConvertToNURBS', h=line, keepOrig=True))
    f.read('NurbsCurveGetNumPieces', {'objectHd': h}, 1, label='linear_nurbs_piece_count', verifies=[made])
    f.read('NurbsDegree', {'objectHd': h, 'index': 0}, 1, label='linear_nurbs_degree', verifies=[made])
    f.read('NurbsGetNumPts', {'objectHd': h, 'index': 0}, 2, label='linear_nurbs_control_count', verifies=[made])
    f.read('NurbsGetPt3D', {'objectHd': h, 'index1': 0, 'index2': 0}, [0, 0, 0], label='linear_nurbs_start', verifies=[made])
    f.read('NurbsGetPt3D', {'objectHd': h, 'index1': 0, 'index2': 1}, [30, 40, 0], label='linear_nurbs_end', verifies=[made])
    f.read('HLength', {'h': line}, 50, label='nurbs_conversion_preserves_source', verifies=[made])
    f.read('NurbsGetWeight', {'objectHd': h, 'index1': 0, 'index2': 0}, 1, label='linear_nurbs_start_weight')
    f.read('NurbsGetWeight', {'objectHd': h, 'index1': 0, 'index2': 1}, 1, label='linear_nurbs_end_weight')
    changed = f.mutate('NurbsSetPt3D', {'objectHd': h, 'index1': 0, 'index2': 1, 'p': [30, 40, 12]}, label='raise_nurbs_endpoint')
    f.read('NurbsGetPt3D', {'objectHd': h, 'index1': 0, 'index2': 1}, [30, 40, 12], label='raised_nurbs_endpoint', verifies=[changed])
    f.read('NurbsGetPt3D', {'objectHd': h, 'index1': 0, 'index2': 0}, [0, 0, 0], label='other_nurbs_endpoint_unchanged', verifies=[changed])
    weight = f.mutate('NurbsSetWeight', {'objectHd': h, 'index1': 0, 'index2': 1, 'weight': 2}, label='change_nurbs_weight')
    f.read('NurbsGetWeight', {'objectHd': h, 'index1': 0, 'index2': 1}, 2, label='changed_nurbs_weight', verifies=[weight])
    f.read('NurbsGetPt3D', {'objectHd': h, 'index1': 0, 'index2': 1}, [30, 40, 12], label='weight_preserves_control_coordinate', verifies=[weight])
    return f.jobs


def _harea(run_id):
    f = _Fixture('geometry_harea')
    for key, box, expected in (('area_unit', ((0, 1), (1, 0)), 1),
                               ('area_rectangle', ((10, 20), (40, 0)), 600),
                               ('area_thin', ((50, 0.5), (51, 0)), 0.5)):
        made, h = _rect(f, run_id, key, box)
        f.read('HArea', {'h': h}, expected, label=key + '_compatibility', verifies=[made])
        f.read('HAreaN', {'ObjectHandle': h}, expected, label=key + '_replacement', verifies=[made])
    h = capture('area_rectangle')
    rotated = f.mutate('HRotate', {'h': h, 'center': [25, 10], 'rotationAngle': 37}, label='area_arbitrary_rotation')
    f.read('HArea', {'h': h}, 600, label='rotation_preserves_coordinate_area', verifies=[rotated])
    scaled = f.mutate('HScale2D', {'h': h, 'centerX': 25, 'centerY': 10,
                                  'scaleX': 2, 'scaleY': 2, 'scaleText': False}, label='area_uniform_scale')
    f.read('HArea', {'h': h}, 2400, label='uniform_scale_squares_area', verifies=[scaled])
    f.read('HAreaN', {'ObjectHandle': h}, 2400, label='scaled_replacement_area', verifies=[scaled])
    for job in f.jobs:
        if job.get('name') == 'HArea':
            # The runner inspects the actual response. HArea can execute native
            # first and then disclose HAreaN; it is not marked native success in
            # advance, nor is a fallback forced on hosts with a valid HArea.
            job['verification_dimension'] = 'primary coordinate units squared; preserve actual native/compatibility provenance'
            job['compatibility_caution'] = 'A disclosed HAreaN fallback is compatibility evidence, not proof of native HArea behavior.'
    return f.jobs


def geometry_fixtures(run_id, families=None):
    """Return independent HOST-compatible jobs; all native results stay pending."""
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id):
        raise ValueError('Invalid run_id')
    selected = list(FAMILIES if families is None else families)
    if not selected or len(set(selected)) != len(selected) or any(name not in FAMILIES for name in selected):
        raise ValueError('Select unique known geometry families')
    builders = dict(zip(FAMILIES, (_rectangles, _ovals, _arcs, _lines, _polygons,
                                  _loci, _poly3d, _extrudes, _nurbs, _harea, _arc_characterization,
                                  _arc_geometry_characterization, _arc_repair_geometry)))
    jobs = [job for family in selected for job in builders[family](run_id)]
    for job in jobs:
        job['fixture_library'] = 'sdk_geometry_fixtures_v1'
        job['prerequisites'].append('Primary coordinate units unchanged during the family; no display-area-unit assumption')
        if job['fixture_family'] in CHARACTERIZATION_FAMILIES:
            job['diagnostic_only'] = True
            job['verification_dimension'] = 'characterization'
            job['prerequisites'].append('Response-shape observations only; never import as semantic native API passes')
    return jobs
