"""Independent geometry oracles for explicitly specified disposable fixtures.

No Vectorworks imports or host calls. This roof oracle accepts only a convex
body over a rectangular XY footprint, bounded by two parallel sloped planes
and four vertical sides. It does not cover dormers, holes, curved faces, or
untrimmed NURBS control nets. Coordinates, thickness and tolerance use the same
length unit; slopes are dimensionless. A passing mathematical shell is not
proof of its native object identity, source provenance, units or regeneration.
"""
import math


class RoofGeometryError(ValueError):
    """Malformed input or geometry inconsistent with the declared fixture."""


def _require(condition, message):
    if not condition:
        raise RoofGeometryError(message)


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def _vector(value, count, label):
    _require(type(value) in (list, tuple) and len(value) == count
             and all(_number(part) for part in value), label + ' requires finite nonboolean numbers')
    return tuple(float(part) for part in value)


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _dot(a, b):
    return math.fsum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _norm(a):
    return math.hypot(*a)


def validate_roof_body(polygons, *, x_bounds, y_bounds, base_z, slope_xy,
                       normal_thickness, abs_tol=1e-7):
    """Return measured shell properties, or raise RoofGeometryError.

    ``base_z`` is the lower plane's elevation at (xmin, ymin). Its height is
    ``base_z + sx*(x-xmin) + sy*(y-ymin)``. Thickness is perpendicular to that
    plane; vertical separation is thickness*sqrt(1+sx**2+sy**2).

    Supply 6..64 polygon dictionaries with exactly ``face_id`` and ``points``.
    face_id is a unique nonempty local label, not a native handle. Each polygon
    has 3..32 ordered XYZ points, optionally repeating the first at the end.
    Either winding is accepted and normalized against the independently known
    outward normal. Convex subdivisions are accepted only when adjacent edges
    have matching segmentation; an unmatched T-junction is refused.
    Watertightness is established within abs_tol vertex welding, not as an
    exact-arithmetic topology certificate.

    Length tolerance must be positive and <=1e-5; each principal fixture length
    must exceed 100 tolerances. Area/volume comparisons derive their absolute
    error bounds from this length tolerance and use fixed 1e-9 relative error.
    Invalid values never become passing observations, even under python -O.
    """
    try:
        return _validate(polygons, x_bounds, y_bounds, base_z, slope_xy, normal_thickness, abs_tol)
    except RoofGeometryError:
        raise
    except (ArithmeticError, ValueError) as error:
        raise RoofGeometryError('Geometry arithmetic is not finite or representable') from error


def _validate(polygons, x_bounds, y_bounds, base_z, slope_xy, normal_thickness, tolerance):
    xmin, xmax = _vector(x_bounds, 2, 'x_bounds')
    ymin, ymax = _vector(y_bounds, 2, 'y_bounds')
    sx, sy = _vector(slope_xy, 2, 'slope_xy')
    _require(_number(base_z), 'base_z must be finite and nonboolean')
    _require(_number(normal_thickness) and normal_thickness > 0, 'normal_thickness must be positive')
    _require(_number(tolerance) and 0 < tolerance <= 1e-5, 'abs_tol must be in (0, 1e-5]')
    width, depth = xmax - xmin, ymax - ymin
    _require(all(_number(v) and v > 100 * tolerance for v in (width, depth, normal_thickness)),
             'Fixture lengths must be positive and resolved by the tolerance')
    plane_scale = math.hypot(sx, sy, 1)
    height = normal_thickness * plane_scale
    scale = max(width, depth, height, abs(sx * width), abs(sy * depth))
    origin = (xmin, ymin, float(base_z))
    center = (width / 2, depth / 2, (sx * width + sy * depth + height) / 2)
    expected_volume = width * depth * height
    expected_areas = {'bottom': width * depth * plane_scale, 'top': width * depth * plane_scale,
                      'xmin': depth * height, 'xmax': depth * height,
                      'ymin': width * height, 'ymax': width * height}
    area_tolerance, volume_tolerance = tolerance * scale * 8, tolerance * scale * scale * 8
    _require(all(_number(v) and v > 0 for v in
                 (plane_scale, height, scale, expected_volume, area_tolerance, volume_tolerance, *expected_areas.values())),
             'Derived fixture dimensions must be finite and positive')
    normals = {'bottom': (sx / plane_scale, sy / plane_scale, -1 / plane_scale),
               'top': (-sx / plane_scale, -sy / plane_scale, 1 / plane_scale),
               'xmin': (-1, 0, 0), 'xmax': (1, 0, 0), 'ymin': (0, -1, 0), 'ymax': (0, 1, 0)}

    def distances(point):
        x, y, z = point
        plane = sx * x + sy * y
        return {'xmin': -x, 'xmax': x - width, 'ymin': -y, 'ymax': y - depth,
                'bottom': (plane - z) / plane_scale, 'top': (z - plane - height) / plane_scale}

    def near(a, b):
        return _norm(_sub(a, b)) <= tolerance

    _require(type(polygons) is list and 6 <= len(polygons) <= 64, 'Polygon count must be 6..64')
    vertices, edges, labels, face_keys, faces = [], {}, set(), set(), []
    area_terms = {plane: [] for plane in normals}
    volumes, moments = [], [[], [], []]
    for polygon in polygons:
        _require(type(polygon) is dict and set(polygon) == {'face_id', 'points'}, 'Malformed polygon fields')
        label, points = polygon['face_id'], polygon['points']
        _require(type(label) is str and bool(label.strip()) and len(label) <= 128 and label not in labels,
                 'Invalid or duplicate face_id')
        labels.add(label)
        _require(type(points) is list and 3 <= len(points) <= 32, 'Polygon points must contain 3..32 vertices')
        local = [_sub(_vector(point, 3, 'Point'), origin) for point in points]
        _require(all(all(_number(value) for value in point) for point in local), 'Local coordinates must be finite')
        if near(local[0], local[-1]):
            local.pop()
        _require(len(local) >= 3, 'Degenerate closed polygon')
        residuals = [distances(point) for point in local]
        _require(all(all(_number(value) and value <= tolerance for value in row.values()) for row in residuals),
                 'Point lies outside the expected roof halfspaces')
        planes = [plane for plane in normals if all(abs(row[plane]) <= tolerance for row in residuals)]
        _require(len(planes) == 1, 'Polygon must lie on exactly one expected boundary plane')
        plane, normal = planes[0], normals[planes[0]]
        signed_twice_area = math.fsum(_dot(_cross(_sub(local[i], local[0]), _sub(local[i + 1], local[0])), normal)
                                     for i in range(1, len(local) - 1))
        _require(_number(signed_twice_area) and abs(signed_twice_area) > tolerance * tolerance,
                 'Degenerate polygon area')
        if signed_twice_area < 0:
            local.reverse()
        # Every vertex must lie on the interior side of every boundary edge.
        # Adjacent-turn signs alone would incorrectly admit star polygons.
        for a, b in zip(local, local[1:] + local[:1]):
            edge = _sub(b, a)
            _require(_norm(edge) > tolerance, 'Degenerate polygon edge')
            _require(all(_dot(_cross(edge, _sub(point, a)), normal) >= -tolerance * _norm(edge)
                         for point in local), 'Face is not a simple convex polygon')
        ids = []
        for point in local:
            matches = [index for index, prior in enumerate(vertices) if near(point, prior)]
            _require(len(matches) <= 1, 'Ambiguous vertex welding')
            if matches:
                ids.append(matches[0])
            else:
                ids.append(len(vertices))
                vertices.append(point)
        _require(len(set(ids)) == len(ids), 'Repeated polygon vertex')
        key = (plane, frozenset(ids))
        _require(key not in face_keys, 'Duplicate geometric face')
        face_keys.add(key)
        for a, b in zip(ids, ids[1:] + ids[:1]):
            edges.setdefault(tuple(sorted((a, b))), []).append((a, b))
        face_area = []
        for i in range(1, len(local) - 1):
            a, b, c = local[0], local[i], local[i + 1]
            area = _norm(_cross(_sub(b, a), _sub(c, a))) / 2
            face_area.append(area)
            # Shift tetrahedra to an interior origin to avoid cancellation
            # from large world coordinates; centroid moments share that frame.
            aa, bb, cc = (_sub(point, center) for point in (a, b, c))
            volume = _dot(aa, _cross(bb, cc)) / 6
            volumes.append(volume)
            for axis in range(3):
                moments[axis].append(volume * (aa[axis] + bb[axis] + cc[axis]) / 4)
        area = math.fsum(face_area)
        area_terms[plane].append(area)
        faces.append({'face_id': label, 'plane': plane, 'area': area})
    _require(all(len(pair) == 2 and pair[0] == tuple(reversed(pair[1])) for pair in edges.values()),
             'Boundary is not a watertight consistently oriented manifold')
    areas = {plane: math.fsum(values) for plane, values in area_terms.items()}
    for plane, expected in expected_areas.items():
        _require(math.isclose(areas[plane], expected, abs_tol=area_tolerance, rel_tol=1e-9),
                 'Area mismatch for ' + plane)
    volume = math.fsum(volumes)
    _require(_number(volume) and volume > 0 and math.isclose(volume, expected_volume,
             abs_tol=volume_tolerance, rel_tol=1e-9), 'Volume mismatch')
    local_center = tuple(center[axis] + math.fsum(moments[axis]) / volume for axis in range(3))
    _require(near(local_center, center), 'Solid centroid mismatch')
    corners = [(x, y, sx * x + sy * y + delta) for x in (0, width) for y in (0, depth) for delta in (0, height)]
    _require(all(any(near(corner, point) for point in vertices) for corner in corners), 'Expected corner absent')
    lower = tuple(min(point[axis] for point in vertices) for axis in range(3))
    upper = tuple(max(point[axis] for point in vertices) for axis in range(3))
    _require(near(lower, tuple(min(point[axis] for point in corners) for axis in range(3)))
             and near(upper, tuple(max(point[axis] for point in corners) for axis in range(3))), 'Extrema mismatch')
    return {'status': 'passed', 'native_calls': 0, 'polygon_count': len(polygons),
            'vertex_count': len(vertices), 'edge_count': len(edges), 'watertight': True,
            'bounds_xyz': [[point[axis] + origin[axis] for axis in range(3)] for point in (lower, upper)],
            'spans_xyz': [upper[axis] - lower[axis] for axis in range(3)], 'volume': volume,
            'solid_centroid_xyz': [local_center[axis] + origin[axis] for axis in range(3)],
            'area_by_plane': areas, 'faces': faces}
