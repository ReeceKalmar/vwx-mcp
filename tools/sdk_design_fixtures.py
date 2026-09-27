"""Curated document-model fixtures for the SDK host-suite injected runner.

This module does not connect to Vectorworks. It supplies concrete native inputs
and independent readback oracles, never catalog-generated native arguments.
Plans use typed MCP tools with disposable-document, SDK-version,
deployment-hash, journal-before-send, and no-replay checks. No fixture contains
Python source, menu commands, dialogs, global preferences, or external files.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ('attributes', 'line', 'polygon', 'text', 'worksheet', 'records', 'resources', 'solid')
_SPEC = importlib.util.spec_from_file_location('sdk_design_host_suite', ROOT / 'tools/sdk_host_suite.py')
HOST = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(HOST)


def capture(name):
    return {'$capture': name}


def fixture_name(prefix, run_id):
    """Keep ASCII fixture identities below observed native name truncation.

    Short existing names are unchanged. Hash the full identity for long names
    so truncation cannot erase the run suffix or merge independent fixtures.
    This is fixture isolation, not a general SDK string-limit assertion.
    """
    if not isinstance(prefix, str) or not isinstance(run_id, str) or not prefix or not run_id:
        raise ValueError('Fixture names require a prefix and run ID')
    value = prefix + run_id
    if not value.isascii():
        raise ValueError('Fixture identity names must be ASCII; test Unicode as separate content')
    return value if len(value) <= 60 else value[:43] + '-' + hashlib.sha256(value.encode('ascii')).hexdigest()[:16]


def call(api_name, **arguments):
    return {'name': api_name, 'arguments': arguments}


class _Fixture:
    def __init__(self, family):
        self.family, self.jobs = family, []

    def add(self, label, *, native_call=None, calls=None, expected=None,
            path=None, predicate='equals', captures=None, phase='readback', verifies=()):
        job = {'id': 'design:%s:%s' % (self.family, label), 'kind': 'native',
               'fixture_family': self.family, 'phase': phase,
               'native_status': 'pending_not_executed',
               'evidence_basis': 'SDK 3200 vs.py exact signatures and documented object semantics; numeric oracles calculated from fixture coordinates',
               'prerequisites': ['Top/Plan view, active design layer, exact named disposable document',
                                 'Fresh run_id; fixture object/resource names must not already exist'],
               'assertions': [{'path': path or ['result'], predicate: expected}],
               'verification_dimension': ('independent semantic readback in a later menu invocation'
                                          if phase == 'readback' else 'native execution/return contract; readback follows in a separate job')}
        if native_call is not None:
            job.update(native_call)
        else:
            job['calls'] = calls
        if captures:
            job['capture'] = {'name': captures, 'path': path or ['result']}
        if verifies:
            job['verifies_jobs'] = list(verifies)
        self.jobs.append(job)
        return job['id']

    def mutate(self, name, arguments, *, label=None, returns=None):
        return self.add(label or name, native_call=call(name, **arguments), expected=returns,
                        phase='mutation')

    def read(self, name, arguments, expected, *, label=None, verifies=(), path=None):
        return self.add(label or name, native_call=call(name, **arguments), expected=expected,
                        verifies=verifies, path=path)

    def create(self, label, calls, key, index=None):
        if isinstance(calls, dict):
            return self.add(label, native_call=calls, captures=key, expected=True,
                            predicate='valid_uuid', phase='creation')
        return self.add(label, calls=calls, captures=key, expected=True,
                        path=['results', len(calls) - 1 if index is None else index, 'result'],
                        predicate='valid_uuid', phase='creation')

    def rectangle(self, key, p1=(0, 20), p2=(30, 0)):
        return self.create('create_' + key, [call('Rect', p1=list(p1), p2=list(p2)), call('LNewObj')], key)

    def pair(self, setter, setter_args, getter, getter_args, expected, *, label=None, returns=None):
        mutation = self.mutate(setter, setter_args, label=label, returns=returns)
        self.read(getter, getter_args, expected, label=(label + '_read') if label else None, verifies=[mutation])


def _attributes(run_id):
    f = _Fixture('attributes')
    made = f.rectangle('attributes_rect')
    h = capture('attributes_rect')
    f.read('GetTypeN', {'h': h}, 3, verifies=[made])
    f.read('GetBBox', {'h': h}, [[0, 20], [30, 0]])
    f.read('HAreaN', {'ObjectHandle': h}, 600)
    f.read('HPerim', {'h': h}, 100)
    f.read('HWidth', {'h': h}, 30)
    f.read('HHeight', {'h': h}, 20)
    name = fixture_name('SDK-Design-Rect-', run_id)
    f.pair('SetName', {'h': h, 'name': name}, 'GetName', {'h': h}, name)
    f.create('find_named_rectangle', call('GetObject', name=name), 'named_rect')
    f.read('GetName', {'h': capture('named_rect')}, name, label='named_rectangle_identity')
    for setter, getter, value in [('SetFPat', 'GetFPat', 1), ('SetLSN', 'GetLSN', 2), ('SetLW', 'GetLW', 10)]:
        argument = {'SetFPat': 'fillPattern', 'SetLSN': 'ls', 'SetLW': 'lw'}[setter]
        f.pair(setter, {'h': h, argument: value}, getter, {'h': h}, value)
    # 16-bit RGB endpoint channels survive any 8-bit color-palette quantization.
    for setter, getter, rgb in [('SetFillFore', 'GetFillFore', [65535, 0, 0]),
                               ('SetFillBack', 'GetFillBack', [0, 65535, 0]),
                               ('SetPenFore', 'GetPenFore', [0, 0, 65535]),
                               ('SetPenBack', 'GetPenBack', [65535, 65535, 0])]:
        f.pair(setter, {'h': h, 'color': rgb}, getter, {'h': h}, rgb)
    f.pair('SetOpacityN', {'h': h, 'inPenOpacity': 80, 'inFillOpacity': 60},
           'GetOpacityN', {'h': h}, [True, 80, 60], returns=True)
    f.pair('SetSelect', {'h': h}, 'Selected', {'h': h}, True, label='select_rectangle')
    f.pair('SetDSelect', {'h': h}, 'Selected', {'h': h}, False, label='deselect_rectangle')
    moved = f.mutate('HMove', {'h': h, 'xOffset': 50, 'yOffset': 70})
    f.read('HCenter', {'h': h}, [65, 80], verifies=[moved])
    f.read('GetBBox', {'h': h}, [[50, 90], [80, 70]], label='moved_bbox', verifies=[moved])
    duplicate = f.create('duplicate_rectangle', call('HDuplicate', objectHandle=h, x=100, y=0), 'duplicate_rect')
    f.read('GetBBox', {'h': capture('duplicate_rect')}, [[150, 90], [180, 70]],
           label='duplicate_bbox', verifies=[duplicate])
    f.read('GetBBox', {'h': h}, [[50, 90], [80, 70]], label='original_survives_duplicate')
    return f.jobs


def _line(run_id):
    f = _Fixture('line')
    created = f.create('create_line', [call('MoveTo', p=[0, 0]), call('LineTo', p=[30, 40]), call('LNewObj')], 'line')
    h = capture('line')
    f.read('GetTypeN', {'h': h}, 2, verifies=[created])
    f.read('GetSegPt1', {'h': h}, [0, 0])
    f.read('GetSegPt2', {'h': h}, [30, 40])
    f.read('HLength', {'h': h}, 50)
    f.pair('SetSegPt1', {'h': h, 'p': [10, 10]}, 'GetSegPt1', {'h': h}, [10, 10], label='move_start')
    end = f.mutate('SetSegPt2', {'h': h, 'p': [40, 50]})
    f.read('GetSegPt2', {'h': h}, [40, 50], label='end_after_move', verifies=[end])
    f.read('HLength', {'h': h}, 50, label='length_after_move', verifies=[end])
    return f.jobs


def _polygon(run_id):
    f = _Fixture('polygon')
    made = f.create('create_triangle', [call('BeginPoly'), call('AddPoint', p=[100, 0]),
                    call('AddPoint', p=[130, 0]), call('AddPoint', p=[100, 20]), call('EndPoly'),
                    call('LNewObj'), call('SetPolyClosed', polyHandle={'$ref': 5}, isClosed=True)], 'polygon', index=5)
    h = capture('polygon')
    f.read('GetVertNum', {'PolyHd': h}, 3, verifies=[made])
    f.read('IsPolyClosed', {'polyHandle': h}, True)
    f.read('GetPolyPt', {'objectHd': h, 'index': 2}, [130, 0])
    f.read('HAreaN', {'ObjectHandle': h}, 300)
    changed = f.mutate('SetPolyPt', {'objectHd': h, 'index': 2, 'xR': 140, 'yR': 0})
    f.read('GetPolyPt', {'objectHd': h, 'index': 2}, [140, 0], label='changed_vertex', verifies=[changed])
    f.read('HAreaN', {'ObjectHandle': h}, 400, label='area_after_vertex_move', verifies=[changed])
    inserted = f.mutate('InsertVertex', {'objectHandle': h, 'x': 120, 'y': 0,
                                        'beforeVertexNum': 2, 'vertexType': 0, 'arcRadius': 0})
    f.read('GetVertNum', {'PolyHd': h}, 4, label='vertex_count_after_insert', verifies=[inserted])
    f.read('GetPolyPt', {'objectHd': h, 'index': 2}, [120, 0], label='inserted_vertex', verifies=[inserted])
    removed = f.mutate('DelVertex', {'objectHd': h, 'vertexNum': 2})
    f.read('GetVertNum', {'PolyHd': h}, 3, label='vertex_count_after_remove', verifies=[removed])
    f.read('HAreaN', {'ObjectHandle': h}, 400, label='area_after_remove', verifies=[removed])
    f.pair('SetPolyClosed', {'polyHandle': h, 'isClosed': False}, 'IsPolyClosed', {'polyHandle': h}, False,
           label='open_polygon')
    f.pair('SetPolyClosed', {'polyHandle': h, 'isClosed': True}, 'IsPolyClosed', {'polyHandle': h}, True,
           label='close_polygon')
    return f.jobs


def _text(run_id):
    f = _Fixture('text')
    created = f.create('create_text', [call('TextOrigin', p=[0, -100]),
                     call('CreateText', theText='Design fixture'), call('LNewObj')], 'text')
    h = capture('text')
    f.read('GetText', {'objectHd': h}, 'Design fixture', verifies=[created])
    f.read('GetTextLength', {'TextHd': h}, 14)
    value = 'Changed fixture'
    f.pair('SetText', {'objectHd': h, 'text': value}, 'GetText', {'objectHd': h}, value, label='change_text')
    f.read('GetTextLength', {'TextHd': h}, len(value), label='changed_length')
    # Text substring offsets are zero-based; SDK MiniCadCallBacks.h defines bold=1.
    f.pair('SetTextSize', {'objectHd': h, 'Start': 0, 'Count': len(value), 'Size': 18.0},
           'GetTextSize', {'TextHd': h, 'Position': 0}, 18.0)
    f.pair('SetTextStyle', {'objectHd': h, 'Start': 0, 'Count': len(value), 'Style': 1},
           'GetTextStyle', {'TextHd': h, 'Position': 0}, 1)
    f.pair('SetTextJust', {'TextHd': h, 'JustFlag': 2}, 'GetTextJust', {'TextHd': h}, 2)
    f.pair('SetTextVerticalAlign', {'TextHd': h, 'verticalAlignment': 1},
           'GetTextVerticalAlign', {'TextHd': h}, 1)
    f.pair('SetTextOrientation', {'theText': h, 'textOrigin': [75, -100],
                                  'textAngle': 30.0, 'textIsMirrored': False},
           'GetTextOrientation', {'theText': h}, [[75, -100], 30.0, False])
    f.pair('SetTextWidth', {'theText': h, 'widthDistance': 150.0}, 'GetTextWidth', {'theText': h}, 150.0)
    f.pair('SetTextWrap', {'theText': h, 'wrap': False}, 'GetTextWrap', {'theText': h}, False)
    return f.jobs


def _worksheet(run_id):
    f = _Fixture('worksheet')
    created = f.create('create_worksheet', call('CreateWS', name=fixture_name('SDK-Design-WS-', run_id), rows=4, columns=3), 'worksheet')
    h = capture('worksheet')
    f.read('GetWSRowColumnCount', {'worksheet': h}, [4, 3], verifies=[created])
    f.pair('SetWSAutoRecalcState', {'worksheet': h, 'state': False},
           'GetWSAutoRecalcState', {'worksheet': h}, False)
    cell = {'worksheet': h, 'topRow': 1, 'leftColumn': 1, 'bottomRow': 1, 'rightColumn': 1}
    formula = f.mutate('SetWSCellFormula', dict(cell, formula='=6*7'))
    f.read('GetWSCellFormula', {'worksheet': h, 'row': 1, 'column': 1}, '=6*7', verifies=[formula])
    recalc = f.mutate('RecalculateWS', {'worksheet': h})
    f.read('GetWSCellValue', {'worksheet': h, 'row': 1, 'column': 1}, 42, verifies=[formula, recalc])
    text_cell = dict(cell, leftColumn=2, rightColumn=2)
    text = f.mutate('SetWSCellFormula', dict(text_cell, formula='Design fixture'), label='set_text_cell')
    recalc2 = f.mutate('RecalculateWS', {'worksheet': h}, label='recalculate_text_cell')
    f.read('GetWSCellString', {'worksheet': h, 'row': 1, 'column': 2}, 'Design fixture', verifies=[text, recalc2])
    f.pair('SetWSRowHeight', {'worksheet': h, 'fromRow': 1, 'toRow': 1, 'height': 30,
                            'updatePalette': False, 'lockHeight': True},
           'GetWSRowHeight', {'worksheet': h, 'row': 1}, 30)
    f.pair('SetWSColumnWidth', {'worksheet': h, 'fromColumn': 1, 'toColumn': 1, 'width': 120},
           'GetWSColumnWidth', {'worksheet': h, 'column': 1}, 120)
    f.pair('SetWSCellAlignment', dict(cell, cellAlignment=2),
           'GetWSCellAlignment', {'worksheet': h, 'row': 1, 'column': 1}, 2)
    # Append/remove empty rows and columns only within this newly created worksheet.
    for name, arguments, count, label in [
            ('InsertWSRows', {'beforeRow': 4, 'numRows': 2}, [6, 3], 'insert_rows'),
            ('DeleteWSRows', {'startRow': 4, 'numRows': 2}, [4, 3], 'remove_added_rows'),
            ('InsertWSColumns', {'beforeColumn': 3, 'numColumns': 2}, [4, 5], 'insert_columns'),
            ('DeleteWSColumns', {'startColumn': 3, 'numColumns': 2}, [4, 3], 'remove_added_columns')]:
        f.pair(name, dict(arguments, worksheet=h), 'GetWSRowColumnCount', {'worksheet': h}, count, label=label)
    f.pair('SetWSAutoRecalcState', {'worksheet': h, 'state': True},
           'GetWSAutoRecalcState', {'worksheet': h}, True, label='enable_auto_recalc')
    f.read('GetWSCellValue', {'worksheet': h, 'row': 1, 'column': 1}, 42, label='value_survives_resizing')
    return f.jobs


def _records(run_id):
    f = _Fixture('records')
    f.rectangle('record_rect', (200, 20), (230, 0))
    h, name = capture('record_rect'), fixture_name('SDK-Design-Record-', run_id)
    # EFieldStyle::kFieldText=4 in SDK MiniCadCallBacks.h. No PIO record is edited.
    made = f.mutate('NewField', {'recName': name, 'fieldName': 'Label', 'fieldValue': 'Default', 'fType': 4, 'fFlag': 0})
    f.create('find_record_format', call('GetObject', name=name), 'record_format')
    record = capture('record_format')
    f.read('NumFields', {'h': record}, 1, verifies=[made])
    f.read('GetFldName', {'h': record, 'index': 1}, 'Label')
    f.read('GetFldType', {'h': record, 't': 1}, 4)
    attached = f.mutate('SetRecord', {'h': h, 'record': name})
    f.read('GetRField', {'h': h, 'record': name, 'field': 'Label'}, 'Default', verifies=[attached])
    f.pair('SetRField', {'h': h, 'record': name, 'field': 'Label', 'value': 'Recorded fixture'},
           'GetRField', {'h': h, 'record': name, 'field': 'Label'}, 'Recorded fixture', label='change_record_field')
    return f.jobs


def _resources(run_id):
    f = _Fixture('resources')
    made = f.create('create_simple_material', call('CreateMaterial', name=fixture_name('SDK-Design-Material-', run_id),
                                                 isSimpleMaterial=True), 'material')
    f.read('IsMaterialSimple', {'materialHandle': capture('material')}, True, verifies=[made])
    f.read('GetName', {'h': capture('material')}, fixture_name('SDK-Design-Material-', run_id), label='material_name')
    f.create('create_texture', call('CreateTexture'), 'texture')
    h = capture('texture')
    f.pair('SetName', {'h': h, 'name': fixture_name('SDK-Design-Texture-', run_id)},
           'GetName', {'h': h}, fixture_name('SDK-Design-Texture-', run_id), label='name_texture')
    f.pair('SetTextureSize', {'texture': h, 'newSize': 12.0}, 'GetTextureSize', {'texture': h}, 12.0)
    return f.jobs


def _solid(run_id):
    f = _Fixture('solid')
    # A cube avoids assuming an undocumented height/depth axis convention.
    f.rectangle('extrude_profile', (300, 30), (330, 0))
    made = f.create('extrude_rectangle', call('HExtrude', objectH=capture('extrude_profile'), bottom=0.0, top=30.0), 'extrude')
    h = capture('extrude')
    f.read('GetTypeN', {'h': h}, 24, verifies=[made])
    f.read('Get3DInfo', {'h': h}, [30, 30, 30], verifies=[made])
    f.read('Get3DCntr', {'h': h}, [[315, 15], 15], verifies=[made])
    moved = f.mutate('Move3DObj', {'h': h, 'xDistance': 10.0, 'yDistance': 20.0, 'zDistance': 30.0})
    f.read('Get3DCntr', {'h': h}, [[325, 35], 45], label='moved_solid_center', verifies=[moved])
    f.read('Get3DInfo', {'h': h}, [30, 30, 30], label='translation_preserves_dimensions', verifies=[moved])
    return f.jobs


def design_fixtures(run_id, families=None):
    """Return host-suite native jobs; every family builds its own prerequisites."""
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id):
        raise ValueError('Invalid run_id')
    selected = list(FAMILIES if families is None else families)
    if not selected or len(set(selected)) != len(selected) or any(f not in FAMILIES for f in selected):
        raise ValueError('Select unique known fixture families')
    builders = {'attributes': _attributes, 'line': _line, 'polygon': _polygon, 'text': _text,
                'worksheet': _worksheet, 'records': _records, 'resources': _resources, 'solid': _solid}
    return [job for family in selected for job in builders[family](run_id)]


def build_plan(document_path, *, run_id=None, families=None, root=ROOT):
    """Compose only these document fixtures, preserving host-suite guard metadata."""
    plan = HOST.build_plan(document_path, root=root, run_id=run_id, include_contracts=False,
                           include_native=False, include_document=False)
    plan['jobs'] = design_fixtures(plan['run_id'], families)
    by_api = {}
    for job in plan['jobs']:
        for name in HOST._functions(job):
            by_api.setdefault(name, []).append(job['id'])
    for name, entry in plan['functions'].items():
        entry['native_case_ids'] = by_api.get(name, [])
        if name in by_api:
            entry['flags'] = [flag for flag in entry['flags'] if flag != 'native_fixture_not_yet_designed']
            entry['prerequisites'] = [value for value in entry['prerequisites']
                                      if not value.startswith('Review official semantics and provide concrete')]
    plan['summary'].update(native_cases=len(plan['jobs']), native_apis_with_designed_fixture=len(by_api),
                           native_apis_without_fixture=len(plan['functions']) - len(by_api))
    plan['fixture_library'] = 'sdk_design_fixtures_v1'
    plan['limitations'].extend([
        'Fixture availability and offline contract tests do not establish native success. All cases start pending.',
        'Creation/setter return-contract checks alone do not prove semantics; inspect the later readback and verifies_jobs links.',
        'Resource and object names include run_id. Use a new run_id; existing names are not renamed, overwritten, or deleted.',
        'Objects/resources remain in the disposable document for inspection. Walls, slabs, complex surfaces, and unprovided APIs remain pending.',
    ])
    return plan


def run_plan(send_tool, plan, journal_path, *, deployed_source_hashes):
    """Run through normal typed MCP tools; no raw-script or direct IPC path."""
    spec = importlib.util.spec_from_file_location('sdk_design_typed_runner', ROOT / 'tools/sdk_design_runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner.run_design_plan(send_tool, plan, journal_path, deployed_source_hashes=deployed_source_hashes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--document', required=True, help='Exact disposable .vwx absolute path; no host connection is made')
    parser.add_argument('--run-id')
    parser.add_argument('--family', action='append', choices=FAMILIES)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = build_plan(args.document, run_id=args.run_id, families=args.family)
    # Never silently replace a plan that may correspond to an already-executed run.
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(plan, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
    print(json.dumps(plan['summary'], sort_keys=True))


if __name__ == '__main__':
    main()
