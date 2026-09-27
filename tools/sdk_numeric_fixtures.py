"""Independent numeric and string oracles for typed native regression tests.

Only finite, documented native domains are used. Invalid ABI inputs belong in
offline adapter tests; singular vectors and undefined mathematical domains are
not sent to Vectorworks. Angles follow the SDK's radians/degrees distinctions.
"""
import math
import re

FAMILIES = ('scalar_math', 'vector_math', 'coordinate_math', 'string_edges', 'string_encoding')


def numeric_fixtures(run_id, families=None):
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id):
        raise ValueError('Invalid run_id')
    selected = list(FAMILIES if families is None else families)
    if not selected or len(set(selected)) != len(selected) or any(f not in FAMILIES for f in selected):
        raise ValueError('Select unique known numeric fixture families')
    jobs = []
    serial = {}

    def case(family, name, arguments, expected, dimension):
        key = (family, name)
        serial[key] = serial.get(key, 0) + 1
        assertion = {'path': ['result'], 'equals': expected}
        # A global 1e-9 absolute tolerance would accept a silent zero for
        # Abs(-1e-9) or Sqr(-1e-9). Use a relative comparison for nonzero
        # algebraic scalar results. Transcendental cardinal-angle residuals
        # keep the ordinary absolute tolerance around their theoretical zero.
        if (name in {'Abs', 'Sqr', 'Sqrt', 'Norm', 'DotProduct', 'Distance', 'Distance3D',
                     'Round', 'Trunc', 'Min', 'Max'}
                and type(expected) in (int, float) and expected != 0):
            assertion['abs_tol'] = 0
        jobs.append({'id': 'numeric:%s:%s:%03d' % (family, name, serial[key]),
                     'kind': 'native', 'fixture_family': family, 'phase': 'readback',
                     'name': name, 'arguments': arguments,
                     'assertions': [assertion],
                     'verification_dimension': dimension,
                     'evidence_basis': 'SDK 3200 exact signature and documented semantics; independent analytic or literal expected result',
                     'native_status': 'pending_not_executed'})

    if 'scalar_math' in selected:
        family = 'scalar_math'
        for value in [-100.0, -0.25, -1e-9, -0.0, 0.25, 100.0]:
            case(family, 'Abs', {'v': value}, math.fabs(value), 'sign/zero/small-magnitude absolute value')
            case(family, 'Sqr', {'v': value}, value * value, 'sign-independent square')
        for value in [0.0, 1e-12, 0.25, 2.0, 10000.0]:
            case(family, 'Sqrt', {'v': value}, math.sqrt(value), 'nonnegative domain including zero and small values')
        for value in [-2 * math.pi, -math.pi, -math.pi / 2, -math.pi / 6, 0.0, math.pi / 6, math.pi / 2, math.pi, 2 * math.pi]:
            for name, function in [('Sin', math.sin), ('Cos', math.cos)]:
                case(family, name, {'v': value}, function(value), 'quadrants, periodicity and radians')
        for value in [-math.pi / 4, 0.0, math.pi / 4]:
            case(family, 'Tan', {'v': value}, math.tan(value), 'signed finite tangent domain')
        for value in [-1.0, -0.5, 0.0, 0.5, 1.0]:
            for name, function in [('ArcSin', math.asin), ('ArcCos', math.acos), ('ArcTan', math.atan)]:
                case(family, name, {'v': value}, function(value), 'inverse trigonometry endpoints and interior')
        for value in [1e-6, 0.5, 1.0, math.e, 10.0, 1e6]:
            case(family, 'Ln', {'v': value}, math.log(value), 'positive logarithm domain across scales')
        for value in [-10.0, -1.0, 0.0, 1.0, 10.0]:
            case(family, 'Exp', {'v': value}, math.exp(value), 'negative/zero/positive exponent')
        for value in [-720.0, -180.0, -45.0, 0.0, 45.0, 180.0, 720.0]:
            case(family, 'Deg2Rad', {'degreeValue': value}, value * math.pi / 180, 'signed degrees to radians')
            case(family, 'Rad2Deg', {'radianValue': value * math.pi / 180}, value, 'signed radians to degrees')
        for value, expected in [(-2.51, -3), (-2.49, -2), (-0.01, 0), (0.0, 0), (2.49, 2), (2.51, 3)]:
            case(family, 'Round', {'v': value}, expected, 'nearest integer either side of half; tie rule unspecified')
        for value in [-2.99, -0.01, 0.0, 0.01, 2.99]:
            case(family, 'Trunc', {'v': value}, math.trunc(value), 'truncation toward zero')
        for a, b in [(-8, 3), (3, -8), (-4, -2), (0, 0), (7, 7)]:
            case(family, 'Min', {'val1': a, 'val2': b}, min(a, b), 'ordering, equality and commutativity')
            case(family, 'Max', {'val1': a, 'val2': b}, max(a, b), 'ordering, equality and commutativity')

    if 'vector_math' in selected:
        family = 'vector_math'
        for vector in [[0, 0, 0], [3, 4, 0], [-3, -4, 0], [2, 3, 6], [0, 0, -5], [0.003, 0.004, 0]]:
            length = math.sqrt(sum(v * v for v in vector))
            case(family, 'Norm', {'Vec': vector}, length, 'signed/zero/spatial/scaled vector norm')
            if length:
                case(family, 'UnitVec', {'Vect': vector}, [v / length for v in vector], 'nonzero-vector normalization')
        for a, b in [([1, 0, 0], [0, 1, 0]), ([0, 1, 0], [1, 0, 0]),
                     ([1, 2, 3], [-4, 5, -6]), ([1, 2, 3], [2, 4, 6]), ([0, 0, 0], [3, 4, 5])]:
            case(family, 'DotProduct', {'v1': a, 'v2': b}, sum(x * y for x, y in zip(a, b)), 'orthogonal/parallel/signed/zero vectors')
            expected = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
            case(family, 'CrossProduct', {'v1': a, 'v2': b}, expected, 'orientation and antisymmetry; parallel/zero vectors')
        for a, b, angle in [([1, 0, 0], [0, 1, 0], 90), ([1, 0, 0], [-1, 0, 0], 180),
                            ([2, 0, 0], [4, 0, 0], 0), ([1, 0, 0], [1, 1, 0], 45)]:
            case(family, 'AngBVec', {'v1': a, 'v2': b}, angle, 'documented degree angle between nonzero vectors')
        for angle in [0, 45, 90, 180, 270]:
            radians = math.radians(angle)
            case(family, 'Ang2Vec', {'angleR': angle, 'Length': 5.0},
                 [5 * math.cos(radians), 5 * math.sin(radians), 0], 'degree quadrants and vector length')
        for vector, expected in [([1, 0, 0], [0, -1, 0]), ([0, 1, 0], [1, 0, 0]), ([-3, 4, 0], [4, 3, 0])]:
            case(family, 'Perp', {'Vec': vector}, expected, 'documented clockwise planar perpendicular')

    if 'coordinate_math' in selected:
        family = 'coordinate_math'
        for a, b in [([0, 0], [0, 0]), ([0, 0], [3, 4]), ([-8, -6], [-5, -2]),
                     ([0.01, 0.02], [0.04, 0.06]), ([100, 100], [-100, -100])]:
            case(family, 'Distance', dict(x1=a[0], y1=a[1], x2=b[0], y2=b[1]), math.dist(a, b), 'identity, translation and signed coordinate distance')
            case(family, 'Distance', dict(x1=b[0], y1=b[1], x2=a[0], y2=a[1]), math.dist(a, b), 'distance symmetry')
        for a, b in [([0, 0, 0], [0, 0, 0]), ([0, 0, 0], [2, 3, 6]), ([-5, -5, -5], [-3, -2, 1])]:
            case(family, 'Distance3D', dict(x1=a[0], y1=a[1], z1=a[2], x2=b[0], y2=b[1], z2=b[2]), math.dist(a, b), 'spatial identity and translation')
        for delta, expected in [(0.0, True), (0.009, True), (0.011, False), (1.0, False)]:
            case(family, 'Eq', {'value1': 1.0, 'value2': 1.0 + delta, 'tolerance': 0.01}, expected, 'inside and outside tolerance, avoiding ambiguous equality threshold')
        for name in ['EqPt', 'EqPt2D', 'EqPt3D']:
            for delta, expected in [(0, True), (0.005, True), (0.02, False)]:
                case(family, name, {'pt1': [0, 0, 0], 'pt2': [delta, 0, 0], 'tolerance': 0.01}, expected, 'point tolerance positive/negative cases')
        for p, expected in [([5, 5], True), ([-1, 5], False), ([11, 5], False), ([5, -1], False), ([5, 11], False)]:
            case(family, 'PtInRect', {'point': p, 'rect1': [0, 10], 'rect2': [10, 0]}, expected, 'rectangle interior and each exterior side')
        for point, expected in [([5, 0, 0], True), ([5, 0.005, 0], True), ([5, 0.02, 0], False)]:
            case(family, 'PtOnLine', {'pt': point, 'begPt': [0, 0, 0], 'endPt': [10, 0, 0], 'tolerance': 0.01}, expected, 'line tolerance inside segment')
        for point in [[5, 3, 0], [-2, 4, 0], [15, -3, 0]]:
            case(family, 'PtPerpLine', {'pt': point, 'begPt': [0, 0, 0], 'endPt': [10, 0, 0]}, [point[0], 0, 0], 'projection onto documented infinite supporting line')

    if 'string_encoding' in selected:
        # SDK LenEncoding explicitly defines 3=UTF8 and 4=UTF16. Literal
        # counts distinguish bytes, code units and code points; locale-specific
        # encodings 0..2 have no portable oracle and are deliberately excluded.
        for value, utf8_bytes, utf16_units in [
                ('', 0, 0), ('A', 1, 1), ('é', 2, 1), ('東', 3, 1),
                ('e\u0301', 3, 2), ('A😀B', 6, 4), ('\r\n', 2, 2),
                ('café 東京 😀 e\u0301 ' * 40, 880, 560)]:
            for encoding, expected in ((3, utf8_bytes), (4, utf16_units)):
                case('string_encoding', 'LenEncoding', {'v': value, 'encoding': encoding}, expected,
                     'documented UTF8 bytes/UTF16 units: empty, BMP, combining, supplementary, newline and long input')

    if 'string_edges' in selected:
        family = 'string_edges'
        for value, length in [('', 0), ('A', 1), ('café', 4), ('中 Ω', 3), ('line\nnext', 9)]:
            case(family, 'Len', {'v': value}, length, 'empty, BMP Unicode and newline string length')
            case(family, 'Concat', {'txt': value}, value, 'single-string identity including empty and Unicode')
        for char, code in [('A', 65), ('z', 122), ('0', 48)]:
            case(family, 'Chr', {'v': code}, char, 'ASCII codepoint conversion')
            case(family, 'Ord', {'v': char}, code, 'ASCII character conversion')
        for code, char in [(233, 'é'), (937, 'Ω'), (20013, '中')]:
            case(family, 'UniChr', {'v': code}, char, 'non-ASCII BMP codepoint conversion')
        for start, count, copied, deleted in [(1, 0, '', 'abcdef'), (1, 1, 'a', 'bcdef'),
                                             (6, 1, 'f', 'abcde'), (2, 3, 'bcd', 'aef'), (1, 6, 'abcdef', '')]:
            args = {'source': 'abcdef', 'index': start, 'count': count}
            case(family, 'Copy', args, copied, 'one-based start/end/full/zero-count substring')
            case(family, 'Delete', args, deleted, 'one-based start/end/full/zero-count string deletion')
        for needle, source, position in [('ab', 'abcdef', 1), ('ef', 'abcdef', 5), ('xx', 'abcdef', 0), ('x', '', 0)]:
            case(family, 'Pos', {'subStr': needle, 'str': source}, position, 'first/last/missing substring')
        for index, expected in [(1, 'red'), (2, 'green'), (3, 'blue')]:
            case(family, 'SubString', {'text': 'red,green,blue', 'delimiter': ',', 'index': index}, expected, 'first/interior/last token')
        for value, expected in [('', ''), ('aBc xyz 123', 'ABC XYZ 123'), ('Already UPPER', 'ALREADY UPPER')]:
            case(family, 'UprString', {'str': value}, expected, 'ASCII compatibility conversion; not native execution')
            jobs[-1]['execution_kind'] = 'compatibility'
        for value, text in [(-42, '-42'), (0, '0'), (42, '42')]:
            case(family, 'Num2Str', {'decPlace': 0, 'v': value}, text, 'signed integer numeric formatting')
            case(family, 'Str2Num', {'s': text}, value, 'signed integer numeric parsing')
    return jobs
