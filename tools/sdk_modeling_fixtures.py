"""Pending modeling fixtures with analytic, later-job readbacks.

Reviewed contracts: SDK 3200 build 882699 SDKLib/Include/vs.py and READ ME/
VectorScript Reference.xml, including SolidsResultsTable (success code 0).
No host connection is made. Every family creates fresh named objects. No view,
selection, layer, preference, document switch, external resource, or existing
user object is modified. Conversions and CSG always capture the returned handle;
consumed inputs are never reused. Native validity remains unverified until run.
"""
import importlib.util
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location('sdk_modeling_design', ROOT / 'tools/sdk_design_fixtures.py')
DESIGN = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(DESIGN)
_Fixture, call, capture = DESIGN._Fixture, DESIGN.call, DESIGN.capture
fixture_name = DESIGN.fixture_name

FAMILIES = ('modeling_bounds', 'modeling_rounded', 'modeling_oriented_primitives',
            'modeling_duplicates', 'modeling_planar_conversion',
            'modeling_primitive_solids', 'modeling_extrude_info',
            'modeling_nurbs_sampling', 'modeling_csg',
            'modeling_centroid_units', 'modeling_nurbs_distance',
            'modeling_nurbs_distance_characterization', 'modeling_curve_bounds_characterization')
CHARACTERIZATION_FAMILIES = ('modeling_nurbs_distance_characterization', 'modeling_curve_bounds_characterization')
DIAGNOSTIC_FAMILIES = ('modeling_nurbs_distance',) + CHARACTERIZATION_FAMILIES


def _named(f, run_id, key, calls, index=None):
    if isinstance(calls, dict):
        calls, index = [calls], 0
    else:
        calls = list(calls)
        index = len(calls)-1 if index is None else index
    name = fixture_name('SDK-Modeling-' + key + '-', run_id)
    calls.append(call('SetName', h={'$ref': index}, name=name))
    made = f.create('create_' + key, calls, key, index=index)
    f.read('GetName', {'h': capture(key)}, name, label=key + '_name', verifies=[made])
    return made, capture(key)


def _rect(f, run_id, key, p1=(0, 20), p2=(30, 0)):
    return _named(f, run_id, key, [call('Rect', p1=list(p1), p2=list(p2)), call('LNewObj')])


def _box(f, run_id, key, p1, p2, bottom, top):
    _, profile = _rect(f, run_id, key + '_profile', p1, p2)
    made, h = _named(f, run_id, key, call('HExtrude', objectH=profile, bottom=bottom, top=top))
    f.read('Get3DInfo', {'h': h}, [p1[1]-p2[1], p2[0]-p1[0], top-bottom], label=key + '_dimensions', verifies=[made])
    return made, h


def _bounds(run_id):
    f = _Fixture('modeling_bounds')
    made, h = _rect(f, run_id, 'bounds_rect')
    f.read('HCenter', {'h': h}, [15, 10], label='initial_center', verifies=[made])
    for label, p1, p2, width, height, center in (
            ('signed', [-40, -10], [-10, -30], 30, 20, [-25, -20]),
            ('fractional', [0.125, 0.75], [0.625, 0.5], 0.5, 0.25, [0.375, 0.625]),
            ('reset', [100, 10], [120, 0], 20, 10, [110, 5])):
        changed = f.mutate('SetBBox', {'h': h, 'p1': p1, 'p2': p2}, label='bbox_' + label)
        f.read('GetBBox', {'h': h}, [p1, p2], label=label + '_bounds', verifies=[changed])
        f.read('HWidth', {'h': h}, width, label=label + '_width', verifies=[changed])
        f.read('HHeight', {'h': h}, height, label=label + '_height', verifies=[changed])
        f.read('HAreaN', {'ObjectHandle': h}, width*height, label=label + '_area', verifies=[changed])
        f.read('HCenter', {'h': h}, center, label=label + '_center', verifies=[changed])
    # Only dimensions/area are asserted: the setter's anchor is unspecified.
    for index, width in enumerate((0.5, 20, 40)):
        changed = f.mutate('SetWidth', {'h': h, 'value': width}, label='set_width_%d' % index)
        f.read('HWidth', {'h': h}, width, label='width_%d' % index, verifies=[changed])
        f.read('HHeight', {'h': h}, 10, label='width_preserves_height_%d' % index, verifies=[changed])
        f.read('HAreaN', {'ObjectHandle': h}, width*10, label='width_area_%d' % index, verifies=[changed])
    for index, height in enumerate((0.25, 10, 80)):
        changed = f.mutate('SetHeight', {'h': h, 'value': height}, label='set_height_%d' % index)
        f.read('HHeight', {'h': h}, height, label='height_%d' % index, verifies=[changed])
        f.read('HWidth', {'h': h}, 40, label='height_preserves_width_%d' % index, verifies=[changed])
        f.read('HAreaN', {'ObjectHandle': h}, 40*height, label='height_area_%d' % index, verifies=[changed])
    return f.jobs


def _physical_coordinates(f, values):
    """Parse explicit mm inputs without changing document units/preferences.

    The official ValidNumStr example accepts physical units ('5m + 5cm').
    Capture its drawing-coordinate result only after success/finite checks.
    A later independently calculated geometric result checks the conversion.
    """
    coordinates = {}
    for index, value in enumerate(sorted(set(values))):
        key = f.family + '_physical_mm_' + str(index)
        f.add('parse_' + key, native_call=call('ValidNumStr', str=format(value, '.12g') + 'mm'),
              expected=True, path=['result', 0])
        f.jobs[-1]['assertions'].append({'path': ['result', 1], 'range_inclusive': [-1e12, 1e12]})
        f.jobs[-1]['capture'] = {'name': key, 'path': ['result', 1]}
        coordinates[value] = capture(key)
    return coordinates


def _centroid_units(run_id):
    """Centroid returns mm; the physical fixture is independent of drawing units.

    Vectorworks/developer-scripting Function Reference/Functions/Centroid.md
    explicitly documents this result unit (remarks 2016-04-18). Do not change
    the raw SDK return or infer units from a single native result. Construct
    physical millimetre geometry through ValidNumStr instead. Historical plans
    retaining the incorrect drawing-coordinate oracle are not rewritten.
    """
    f = _Fixture('modeling_centroid_units')
    rectangles = (
            ('initial', [0, 20], [30, 0], [15, 10]),
            ('signed', [-40, -10], [-10, -30], [-25, -20]),
            ('fractional', [0.125, 0.75], [0.625, 0.5], [0.375, 0.625]),
            ('offset', [100, 10], [120, 0], [110, 5]))
    triangle = [[-10, -10], [20, -10], [-10, 20]]
    coordinates = _physical_coordinates(f, [v for _, p1, p2, _ in rectangles for p in (p1, p2) for v in p]
                                         + [v for p in triangle for v in p])
    def point(values):
        return [coordinates[value] for value in values]
    for label, p1, p2, center in rectangles:
        made, h = _rect(f, run_id, 'centroid_units_' + label, point(p1), point(p2))
        f.read('Centroid', {'h': h}, [True] + center, label=label + '_centroid', verifies=[made])
    # Triangle centroid (0,0) differs from its bounds center (5,5). Both
    # windings must retain the physical center and reject a bounds-only proxy.
    for winding, vertices in (('ccw', triangle), ('cw', triangle[::-1])):
        calls = [call('BeginPoly')] + [call('AddPoint', p=point(p)) for p in vertices] + [call('EndPoly'), call('LNewObj')]
        index = len(calls)-1
        calls.append(call('SetPolyClosed', polyHandle={'$ref': index}, isClosed=True))
        made, h = _named(f, run_id, 'centroid_triangle_' + winding, calls, index=index)
        f.read('Centroid', {'h': h}, [True, 0, 0], label=winding + '_triangle_centroid', verifies=[made])
    for job in f.jobs:
        job['verification_dimension'] = 'physical millimetre centroid; explicit-unit input, no document-unit writes'
        job['contract_source'] = 'https://github.com/Vectorworks/developer-scripting/blob/main/Function%20Reference/Functions/Centroid.md'
    return f.jobs


def _rounded(run_id):
    f = _Fixture('modeling_rounded')
    made, h = _named(f, run_id, 'rounded_edit', [call('RRect', p1=[150, 20], p2=[190, 0], Diam=[4, 4]), call('LNewObj')])
    f.read('GetRRDiam', {'h': h}, [4, 4], label='initial_diameters', verifies=[made])
    for index, (dx, dy) in enumerate(((0.5, 0.5), (6, 4), (8, 8), (20, 20))):
        changed = f.mutate('SetRRDiam', {'h': h, 'xDiam': dx, 'yDiam': dy}, label='set_diameters_%d' % index)
        f.read('GetRRDiam', {'h': h}, [dx, dy], label='diameters_%d' % index, verifies=[changed])
        f.read('HAreaN', {'ObjectHandle': h}, 800-(4-math.pi)*dx*dy/4, label='rounded_area_%d' % index, verifies=[changed])
        f.read('GetBBox', {'h': h}, [[150, 20], [190, 0]], label='diameters_preserve_bounds_%d' % index, verifies=[changed])
        if dx == dy:
            f.read('HPerimN', {'ObjectHandle': h}, 120-4*dx+math.pi*dx, label='rounded_perimeter_%d' % index, verifies=[changed])
    return f.jobs


def _oriented(run_id):
    f = _Fixture('modeling_oriented_primitives')
    # Unit direction vectors avoid an undocumented normalization requirement.
    # GetBBox explicitly returns screen-plane projection bounds; Top/Plan makes
    # these XY spans. HWidth/HHeight document object dimensions, not projected
    # spans (host 882075 returned width30 for a 90-degree rotated rectangle).
    # Bounding spans are independent of the origin corner convention.
    # These primitives are defined by construction boxes (SDK SetBBox docs).
    # GetBBox projects that box, not the tight curved contour. The independent
    # constructor/rotation/reset observations in batch F agreed on this result;
    # preserve their original evidence rather than rewriting old tight oracles.
    for index, direction in enumerate(([1, 0], [0, 1], [0.6, 0.8])):
        for name, key, area in (('RectangleN', 'oriented_rect', 600),
                                ('OvalN', 'oriented_oval', 150*math.pi),
                                ('RRectangleN', 'oriented_round', 600-(4-math.pi)*4)):
            arguments = {'orgin': [250+index*100, 0], 'direction': direction, 'width': 30, 'height': 20}
            if name == 'RRectangleN':
                arguments.update(xDiam=4, yDiam=4)
            made, h = _named(f, run_id, key + str(index), [call(name, **arguments), call('LNewObj')])
            f.read('HAreaN', {'ObjectHandle': h}, area, label=key + '_area_' + str(index), verifies=[made])
            dx, dy = map(abs, direction)
            spans = (30*dx + 20*dy, 30*dy + 20*dx)
            f.add(key + '_projected_bounds_' + str(index), native_call=call('GetBBox', h=h),
                  expected=list(spans), predicate='bbox_size', verifies=[made])
            if name == 'RectangleN':
                f.read('HPerimN', {'ObjectHandle': h}, 100, label=key + '_perimeter_' + str(index), verifies=[made])
            elif name == 'RRectangleN':
                f.read('GetRRDiam', {'h': h}, [4, 4], label=key + '_diameters_' + str(index), verifies=[made])
    return f.jobs


def _duplicates(run_id):
    f = _Fixture('modeling_duplicates')
    _, source = _rect(f, run_id, 'duplicate_source', (600, 20), (630, 0))
    f.add('parent_container', native_call=call('GetParent', h=source), expected=True, predicate='valid_uuid', captures='duplicate_parent')
    f.add('source_uuid', native_call=call('GetObjectUuid', h=source), expected=True, predicate='valid_uuid', captures='duplicate_source_uuid')
    f.add('resolve_source_uuid', native_call=call('GetObjectByUuid', UUID=capture('duplicate_source_uuid')),
          expected=True, predicate='valid_uuid', captures='duplicate_resolved_source')
    source_name = fixture_name('SDK-Modeling-duplicate_source-', run_id)
    f.read('GetName', {'h': capture('duplicate_resolved_source')}, source_name, label='uuid_identity')
    for index, (name, options) in enumerate((('CreateDuplicateObject', {}),
                                             ('CreateDuplicateObjN', {'maintainHeightRelativeToLayer': False}),
                                             ('CreateDuplicateObjN', {'maintainHeightRelativeToLayer': True}))):
        made, h = _named(f, run_id, 'duplicate_copy_' + str(index), call(name,
                         objectToDuplicate=source, containerHandle=capture('duplicate_parent'), **options))
        f.read('GetBBox', {'h': h}, [[600, 20], [630, 0]], label='copied_bounds_' + str(index), verifies=[made])
        moved = f.mutate('HMove', {'h': h, 'xOffset': 50*(index+1), 'yOffset': -20}, label='move_copy_' + str(index))
        f.read('GetBBox', {'h': h}, [[650+50*index, 0], [680+50*index, -20]], label='moved_copy_bounds_' + str(index), verifies=[moved])
        f.read('GetBBox', {'h': source}, [[600, 20], [630, 0]], label='source_bounds_survive_' + str(index), verifies=[made, moved])
        f.read('GetName', {'h': source}, source_name, label='source_name_survives_' + str(index), verifies=[made])
    return f.jobs


def _conversion(run_id):
    f = _Fixture('modeling_planar_conversion')
    _, source = _rect(f, run_id, 'conversion_source', (800, 20), (830, 0))
    # SDK Objs.TDType.h: kPolygonNode=5 and kPolylineNode=21. Geometry alone
    # cannot distinguish a successful conversion from an unchanged rectangle.
    for name, key, object_type in (('MakePolygon', 'made_polygon', 5), ('MakePolyline', 'made_polyline', 21)):
        made, h = _named(f, run_id, key, call(name, inSourceObject=source))
        f.read('GetTypeN', {'h': h}, object_type, label=key + '_type', verifies=[made])
        f.read('HAreaN', {'ObjectHandle': h}, 600, label=key + '_area', verifies=[made])
        f.read('HPerimN', {'ObjectHandle': h}, 100, label=key + '_perimeter', verifies=[made])
        f.read('GetBBox', {'h': h}, [[800, 20], [830, 0]], label=key + '_bbox', verifies=[made])
        f.read('HAreaN', {'ObjectHandle': source}, 600, label=key + '_source_preserved', verifies=[made])
        moved = f.mutate('HMove', {'h': h, 'xOffset': 0, 'yOffset': 50}, label=key + '_move')
        f.read('GetBBox', {'h': source}, [[800, 20], [830, 0]], label=key + '_source_not_aliased', verifies=[moved])
        f.read('GetBBox', {'h': h}, [[800, 70], [830, 50]], label=key + '_moved_bounds', verifies=[moved])
    # ConvertToPolyline is permitted to replace the original. All following
    # calls use only the returned UUID, never the original source UUID. The
    # SDK explicitly permits a polygon OR polyline, so no exact type is assumed.
    _, convertible = _rect(f, run_id, 'convertible_rect', (900, 20), (930, 0))
    made, h = _named(f, run_id, 'converted_polyline', call('ConvertToPolyline', h=convertible))
    f.read('HAreaN', {'ObjectHandle': h}, 600, label='converted_area', verifies=[made])
    f.read('HPerimN', {'ObjectHandle': h}, 100, label='converted_perimeter', verifies=[made])
    return f.jobs


def _primitives(run_id):
    f = _Fixture('modeling_primitive_solids')
    for index, (center, radius) in enumerate((([0, 0, 0], 1), ([-25, 50, -10], 5), ([100, -20, 30], 0.25))):
        made, h = _named(f, run_id, 'sphere_' + str(index), call('CreateSphere', center=center, radiusDistance=radius))
        f.read('Get3DInfo', {'h': h}, [2*radius]*3, label='sphere_dimensions_' + str(index), verifies=[made])
        f.read('Centroid3D', {'object': h}, [True]+center, label='sphere_centroid_' + str(index), verifies=[made])
        f.read('Products3D', {'object': h}, [True, 0, 0, 0], label='sphere_symmetry_products_' + str(index), verifies=[made])
    for index, (base, radius, height) in enumerate((([200, 0, -10], 5, 20), ([-50, -30, 5], 2, 8))):
        tip = [base[0], base[1], base[2]+height]
        made, h = _named(f, run_id, 'cone_' + str(index), call('CreateCone', center=base, tip=tip, radiusDistance=radius))
        f.read('Get3DInfo', {'h': h}, [2*radius, 2*radius, height], label='cone_dimensions_' + str(index), verifies=[made])
        f.read('Get3DCntr', {'h': h}, [base[:2], base[2]+height/2], label='cone_bounds_center_' + str(index), verifies=[made])
        f.read('Centroid3D', {'object': h}, [True, base[0], base[1], base[2]+height/4], label='cone_mass_centroid_' + str(index), verifies=[made])
    return f.jobs


def _extrude_info(run_id):
    f = _Fixture('modeling_extrude_info')
    made, h = _named(f, run_id, 'scoped_extrude', [call('BeginXtrd', startDistance=-5, endDistance=5),
                    call('Rect', p1=[-15, 10], p2=[15, -10]), call('EndXtrd'), call('LNewObj')])
    f.read('Get3DInfo', {'h': h}, [20, 30, 10], label='scoped_extrude_dimensions', verifies=[made])
    f.read('Get3DOrientation', {'h': h}, [True, 0, 0, 0, False], label='initial_orientation', verifies=[made])
    for label, angle, dimensions in (('quarter_turn', 90, [10, 30, 20]),
                                     ('same_absolute_turn', 90, [10, 30, 20]), ('restore', 0, [20, 30, 10])):
        changed = f.mutate('SetRot3D', {'h': h, 'xAngle': angle, 'yAngle': 0, 'zAngle': 0,
                                       'xDistance': 0, 'yDistance': 0, 'zDistance': 0}, label='rotation_' + label)
        f.read('Get3DOrientation', {'h': h}, [True, angle, 0, 0, False], label=label + '_orientation', verifies=[changed])
        f.read('Get3DInfo', {'h': h}, dimensions, label=label + '_dimensions', verifies=[changed])
    for index, dimensions in enumerate(([8, 12, 6], [20, 30, 10])):
        changed = f.mutate('Set3DInfo', {'h': h, 'heightDistance': dimensions[0], 'widthDistance': dimensions[1],
                                        'depthDistance': dimensions[2]}, label='resize_' + str(index))
        f.read('Get3DInfo', {'h': h}, dimensions, label='resized_dimensions_' + str(index), verifies=[changed])
        # Coordinate/display units cannot affect the zero symmetry products.
        f.read('Products3D', {'object': h}, [True, 0, 0, 0], label='box_symmetry_products_' + str(index), verifies=[changed])
    return f.jobs


def _nurbs(run_id):
    f = _Fixture('modeling_nurbs_sampling')
    _, line = _named(f, run_id, 'sampling_line', [call('MoveTo', p=[0, 0]), call('LineTo', p=[30, 40]), call('LNewObj')])
    made, h = _named(f, run_id, 'sampling_nurbs', call('ConvertToNURBS', h=line, keepOrig=True))
    f.read('NurbsCurveGetNumPieces', {'objectHd': h}, 1, label='one_piece', verifies=[made])
    f.read('NurbsDegree', {'objectHd': h, 'index': 0}, 1, label='linear_degree', verifies=[made])
    f.read('NurbsGetNumPts', {'objectHd': h, 'index': 0}, 2, label='two_control_points', verifies=[made])
    f.read('NurbsNumKnots', {'objectHd': h, 'index': 0}, 4, label='linear_knot_count', verifies=[made])
    for index, point in ((0, [0, 0, 0]), (3, [30, 40, 0])):
        key = 'nurbs_domain_' + str(index)
        f.add('capture_knot_' + str(index), native_call=call('NurbsKnot', objectHd=h, index1=0, index2=index),
              expected=[-1000000, 1000000], predicate='range_inclusive', captures=key)
        f.read('NurbsCurveEvalPt', {'objectHd': h, 'index': 0, 'u': capture(key)}, point,
               label='domain_endpoint_' + str(index))
    for index, fraction in enumerate((0, 0.25, 0.5, 0.75, 1)):
        point = [30*fraction, 40*fraction, 0]
        key = 'nurbs_sample_parameter_' + str(index)
        f.add('point_at_fraction_' + str(index), native_call=call('GetPointAndParameterOnNurbsCurveAtGivenLength',
              inNurbCurve=h, inPercentOfLength=fraction), expected=True, path=['result', 0])
        f.jobs[-1]['assertions'].extend([{'path': ['result', 1], 'equals': point}, {'path': ['result', 3], 'equals': 0}])
        f.jobs[-1]['capture'] = {'name': key, 'path': ['result', 2]}
        f.read('NurbsCurveEvalPt', {'objectHd': h, 'index': 0, 'u': capture(key)}, point,
               label='evaluate_fraction_parameter_' + str(index))
        projected_key = 'nurbs_projected_parameter_' + str(index)
        f.add('project_on_curve_' + str(index), native_call=call('GetParameterOnNurbsCurve', h=h, point=point),
              expected=True, path=['result', 0])
        f.jobs[-1]['assertions'].append({'path': ['result', 2], 'equals': 0})
        f.jobs[-1]['capture'] = {'name': projected_key, 'path': ['result', 1]}
        f.read('NurbsCurveEvalPt', {'objectHd': h, 'index': 0, 'u': capture(projected_key)}, point,
               label='evaluate_projected_parameter_' + str(index))
    for index, (point, distance) in enumerate((([0, 0], 0), ([15, 20], 0))):
        f.read('GetNurbsObjectDistanceFromPoint', {'h': h, 'point': point}, [True, distance], label='point_distance_' + str(index))
    return f.jobs


def _nurbs_distance(run_id):
    """Retain the unresolved sign/unit result without accepting a native quirk.

    The SDK reference says distance and uses REAL, without specifying a sign or
    a conversion policy. Host 882075 returned -127 for a perpendicular distance
    of 5 drawing coordinates. Neither abs() nor multiplication by 25.4 is a
    documented correction; the original oracle remains diagnostic.
    """
    f = _Fixture('modeling_nurbs_distance')
    _, line = _named(f, run_id, 'distance_diagnostic_line',
                     [call('MoveTo', p=[0, 0]), call('LineTo', p=[30, 40]), call('LNewObj')])
    made, h = _named(f, run_id, 'distance_diagnostic_nurbs', call('ConvertToNURBS', h=line, keepOrig=True))
    f.read('NurbsCurveGetNumPieces', {'objectHd': h}, 1, label='one_piece', verifies=[made])
    f.read('NurbsDegree', {'objectHd': h, 'index': 0}, 1, label='linear_degree', verifies=[made])
    f.read('NurbsGetNumPts', {'objectHd': h, 'index': 0}, 2, label='two_control_points', verifies=[made])
    f.read('GetNurbsObjectDistanceFromPoint', {'h': h, 'point': [11, 23]}, [True, 5],
           label='point_distance_2', verifies=[made])
    return f.jobs


def _nurbs_distance_characterization(run_id):
    """Measure sign, physical units, direction, and finite-segment behavior.

    These are observations, not native semantic passes. The reference does not
    document signed or internal-unit results. Preserve both directions and
    both sides before proposing any compatibility correction.
    """
    f = _Fixture('modeling_nurbs_distance_characterization')
    samples = (('on_start', [0, 0], 0), ('on_middle', [15, 20], 0),
               ('left', [11, 23], 5), ('right', [19, 17], 5),
               ('before', [-3, -4], 5), ('beyond', [33, 44], 5),
               ('before_oblique', [-7, -1], math.sqrt(50)))
    coordinates = _physical_coordinates(f, [0, 30, 40] + [v for _, point, _ in samples for v in point])
    def point(values):
        return [coordinates[v] for v in values]
    for direction, start, end in (('forward', [0, 0], [30, 40]), ('reverse', [30, 40], [0, 0])):
        _, line = _named(f, run_id, 'distance_' + direction + '_line',
                         [call('MoveTo', p=point(start)), call('LineTo', p=point(end)), call('LNewObj')])
        made, h = _named(f, run_id, 'distance_' + direction + '_nurbs', call('ConvertToNURBS', h=line, keepOrig=True))
        f.read('NurbsCurveGetNumPieces', {'objectHd': h}, 1, label=direction + '_one_piece', verifies=[made])
        f.read('NurbsDegree', {'objectHd': h, 'index': 0}, 1, label=direction + '_linear_degree', verifies=[made])
        f.read('NurbsGetNumPts', {'objectHd': h, 'index': 0}, 2, label=direction + '_two_points', verifies=[made])
        for label, location, distance in samples:
            f.add(direction + '_' + label, native_call=call('GetNurbsObjectDistanceFromPoint', h=h, point=point(location)),
                  expected=True, path=['result', 0], verifies=[made])
            f.jobs[-1]['assertions'].append({'path': ['result', 1], 'range_inclusive': [-1e12, 1e12]})
            f.jobs[-1]['measurement_context'] = {'input_length_units': 'mm', 'start': start, 'end': end,
                                               'query': location, 'unsigned_segment_distance_mm': distance}
    return f.jobs


def _curve_bounds_characterization(run_id):
    """Distinguish cached bounds from primitive control-box projection.

    ResetBBox is documented to recompute from current geometry. Compare its
    result with fresh oriented construction and rotation of an axis-aligned
    primitive; keep tight-contour and projected-control predictions separate.
    No predicted interpretation is credited as passed by these observations.
    """
    f = _Fixture('modeling_curve_bounds_characterization')
    angle = math.degrees(math.atan2(4, 3))
    for index, (api, shape) in enumerate((('OvalN', 'oval'), ('RRectangleN', 'round'),
                                         ('Oval', 'rotated_oval'), ('RRect', 'rotated_round'))):
        origin = [1000 + index*100, 0]
        if api in ('OvalN', 'RRectangleN'):
            args = {'orgin': origin, 'direction': [0.6, 0.8], 'width': 30, 'height': 20}
            if api == 'RRectangleN':
                args.update(xDiam=4, yDiam=4)
        else:
            args = {'p1': [origin[0], 20], 'p2': [origin[0]+30, 0]}
            if api == 'RRect':
                args['Diam'] = [4, 4]
        made, h = _named(f, run_id, 'bounds_probe_' + shape, [call(api, **args), call('LNewObj')])
        f.read('GetTypeN', {'h': h}, 4 if 'oval' in shape else 13, label=shape + '_type', verifies=[made])
        changes = [made]
        if api in ('Oval', 'RRect'):
            changes.append(f.mutate('HRotate', {'h': h, 'center': [origin[0]+15, 10], 'rotationAngle': angle},
                                    label=shape + '_rotate'))
        area = 150*math.pi if 'oval' in shape else 600-(4-math.pi)*4
        f.read('HAreaN', {'ObjectHandle': h}, area, label=shape + '_area', verifies=changes)
        tight = [math.hypot(18, 16), math.hypot(24, 12)] if 'oval' in shape else [32.4, 34.4]
        for stage in ('before_reset', 'after_reset'):
            if stage == 'after_reset':
                changes = [f.mutate('ResetBBox', {'h': h}, label=shape + '_reset_bounds')]
            f.add(shape + '_' + stage, native_call=call('GetBBox', h=h),
                  expected=[-1e12, 1e12], path=['result', 0, 0], predicate='range_inclusive', verifies=changes)
            f.jobs[-1]['assertions'].extend({'path': ['result', row, column], 'range_inclusive': [-1e12, 1e12]}
                                          for row, column in ((0, 1), (1, 0), (1, 1)))
            f.jobs[-1]['measurement_context'] = {'shape': shape, 'stage': stage, 'analytic_tight_spans': tight,
                                               'projected_control_box_spans': [34, 36]}
    return f.jobs


def _csg(run_id):
    f = _Fixture('modeling_csg')
    # A=[0,30]x[0,20]x[0,10], B=[20,40]x[-5,25]x[-5,15].
    # Their overlap has positive volume and is well clear of tangent cases.
    for index, (api, dimensions, centroid) in enumerate((('AddSolid', [30, 40, 20], [25, 10, 5]),
                                                       ('IntersectSolid', [20, 10, 10], [25, 10, 5]),
                                                       ('SubtractSolid', [20, 20, 10], [10, 10, 5]))):
        _, a = _box(f, run_id, 'csg_a_' + str(index), [0, 20], [30, 0], 0, 10)
        _, b = _box(f, run_id, 'csg_b_' + str(index), [20, 25], [40, -5], -5, 15)
        key = 'csg_result_' + str(index)
        made = f.add('boolean_' + api, native_call=call(api, obj1=a, obj2=b), expected=0,
                     path=['result', 0], phase='creation')
        f.jobs[-1]['assertions'].append({'path': ['result', 1], 'valid_uuid': True})
        f.jobs[-1]['capture'] = {'name': key, 'path': ['result', 1]}
        h, name = capture(key), fixture_name('SDK-Modeling-' + key + '-', run_id)
        named = f.mutate('SetName', {'h': h, 'name': name}, label='name_result_' + str(index))
        f.read('GetName', {'h': h}, name, label='result_name_' + str(index), verifies=[made, named])
        f.read('Get3DInfo', {'h': h}, dimensions, label='boolean_dimensions_' + str(index), verifies=[made])
        f.read('Centroid3D', {'object': h}, [True]+centroid, label='boolean_centroid_' + str(index), verifies=[made])
    return f.jobs


def modeling_fixtures(run_id, families=None):
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id):
        raise ValueError('Invalid run_id')
    selected = list(FAMILIES if families is None else families)
    if not selected or len(set(selected)) != len(selected) or any(name not in FAMILIES for name in selected):
        raise ValueError('Select unique known modeling families')
    builders = dict(zip(FAMILIES, (_bounds, _rounded, _oriented, _duplicates, _conversion,
                                  _primitives, _extrude_info, _nurbs, _csg,
                                  _centroid_units, _nurbs_distance,
                                  _nurbs_distance_characterization, _curve_bounds_characterization)))
    jobs = [job for family in selected for job in builders[family](run_id)]
    for job in jobs:
        job['fixture_library'] = 'sdk_modeling_fixtures_v1'
        job['evidence_basis'] = 'SDK 3200 vs.py and VectorScript Reference.xml; independent analytic geometry and documented operation contracts'
        job['prerequisites'].append('Fresh run-specific objects only; Top/Plan, active design layer, no concurrent document switching')
        if job['fixture_family'] in DIAGNOSTIC_FAMILIES:
            job['diagnostic_only'] = True
            job['prerequisites'].append('Explicit diagnostic selection; unresolved semantics are preserved')
            job['known_issue'] = 'NURBS distance sign/unit or primitive control-bounds semantics require native characterization'
        if job['fixture_family'] in CHARACTERIZATION_FAMILIES:
            job['verification_dimension'] = 'characterization'
            job['prerequisites'].append('Response-shape observations only; never import as semantic native API passes')
    return jobs
