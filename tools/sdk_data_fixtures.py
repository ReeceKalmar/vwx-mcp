"""Typed native data fixtures with independent readbacks, never a host connection.

Selectors and boundaries come from SDK 3200's VectorScript Reference.xml and
vs.py, not from catalog-generated sample arguments. Every family creates its
own objects/resources. No class, layer, document default, or existing resource
is modified. These are executable *pending* native tests, not native evidence.
"""
import importlib.util
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location('sdk_data_design_helpers', ROOT / 'tools/sdk_design_fixtures.py')
DESIGN = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(DESIGN)
_Fixture, call, capture = DESIGN._Fixture, DESIGN.call, DESIGN.capture
FAMILIES = ('data_attributes', 'data_records', 'data_worksheet_values', 'data_worksheet_classification',
            'data_worksheet_boundaries',
            'data_worksheet_format', 'data_worksheet_structure', 'data_materials',
            'data_resource_tags', 'data_worksheet_type_probe', 'data_worksheet_validity_probe',
            'data_worksheet_database', 'data_worksheet_operators', 'data_worksheet_edge_edits')
# Full offline plans retain these tests. Routine native batches should exclude
# them unless explicitly selected; the registry/batch runner owns that policy.
DIAGNOSTIC_FAMILIES = ('data_worksheet_boundaries', 'data_worksheet_classification',
                       'data_worksheet_type_probe', 'data_worksheet_validity_probe')
CHARACTERIZATION_FAMILIES = ('data_worksheet_type_probe', 'data_worksheet_validity_probe')


def _worksheet(f, run_id, rows=6, columns=5, suffix=''):
    prefix = suffix + '_' if suffix else ''
    key = f.family + '_' + prefix + 'sheet'
    made = f.create(prefix + 'create_worksheet', call('CreateWS', name=DESIGN.fixture_name('SDK-' + f.family + '-' + (suffix + '-' if suffix else ''), run_id),
                                          rows=rows, columns=columns), key)
    h = capture(key)
    f.read('GetWSRowColumnCount', {'worksheet': h}, [rows, columns], label=prefix + 'GetWSRowColumnCount', verifies=[made])
    return h


def _cell(h, row, column):
    return {'worksheet': h, 'row': row, 'column': column}


def _range(h, top=1, left=1, bottom=None, right=None):
    return {'worksheet': h, 'topRow': top, 'leftColumn': left,
            'bottomRow': top if bottom is None else bottom,
            'rightColumn': left if right is None else right}


def _numeric_capture(f, label, api, arguments, key):
    return f.add(label, native_call=call(api, **arguments), expected=[1, 2147483647],
                 predicate='range_inclusive', captures=key)


def _data_attributes(run_id):
    f = _Fixture('data_attributes')
    f.rectangle('data_attributes_rect', (700, 20), (730, 0))
    h = capture('data_attributes_rect')
    # Only object overrides change: no NameClass, class definition or default writes.
    for setter, getter in [('SetFillColorByClass', 'IsFillColorByClass'),
                           ('SetPenColorByClass', 'IsPenColorByClass'),
                           ('SetFPatByClass', 'IsFPatByClass'),
                           ('SetLSByClass', 'IsLSByClass'),
                           ('SetLWByClass', 'IsLWByClass'),
                           ('SetMarkerByClass', 'IsMarkerByClass')]:
        f.pair(setter, {'h': h}, getter, {'h': h}, True)
    for pen, fill in [(True, True), (True, False), (False, True), (False, False)]:
        f.pair('SetOpacityByClassN', {'h': h, 'inIsPenOpacityByClass': pen,
                                     'inIsFillOpacityByClass': fill},
               'GetOpacityByClassN', {'h': h}, [pen, fill], label='by_class_%s_%s' % (pen, fill))
    f.pair('SetOpacityByClass', {'h': h}, 'GetOpacityByClass', {'h': h}, True)
    reset = f.mutate('SetOpacityByClassN', {'h': h, 'inIsPenOpacityByClass': False,
                                          'inIsFillOpacityByClass': False}, label='explicit_opacity')
    f.read('GetOpacityByClassN', {'h': h}, [False, False], label='explicit_opacity_read', verifies=[reset])
    for value in (0, 37, 100):
        f.pair('SetOpacity', {'h': h, 'opacity': value}, 'GetOpacity', {'h': h}, value,
               label='opacity_%d' % value)
    for pen, fill in [(0, 100), (100, 0), (17, 83)]:
        f.pair('SetOpacityN', {'h': h, 'inPenOpacity': pen, 'inFillOpacity': fill},
               'GetOpacityN', {'h': h}, [True, pen, fill], returns=True,
               label='independent_opacity_%d_%d' % (pen, fill))
    f.read('GetBBox', {'h': h}, [[700, 20], [730, 0]], label='style_edits_preserve_geometry')
    return f.jobs


def _data_records(run_id):
    f = _Fixture('data_records')
    for key, x in [('data_record_first', 750), ('data_record_second', 800)]:
        made = f.rectangle(key, (x, 20), (x + 30, 0))
        f.read('NumRecords', {'h': capture(key)}, 0, label=key + '_initial_records', verifies=[made])
    h, other = capture('data_record_first'), capture('data_record_second')
    name = DESIGN.fixture_name('SDK-Data-Record-', run_id)
    # EFieldStyle kFieldText=4; text formatting flag=0 in MiniCadCallBacks.h.
    fields = [('Label', 'Default'), ('Notes', ''), ('Unicode', 'Grüße 東京')]
    creations = []
    for field, value in fields:
        creations.append(f.mutate('NewField', {'recName': name, 'fieldName': field,
                                              'fieldValue': value, 'fType': 4, 'fFlag': 0},
                                  label='new_field_' + field))
    f.create('find_format', call('GetObject', name=name), 'data_record_format')
    rh = capture('data_record_format')
    f.read('NumFields', {'h': rh}, len(fields), verifies=creations)
    for i, (field, _) in enumerate(fields, 1):
        f.read('GetFldName', {'h': rh, 'index': i}, field, label='field_name_%d' % i)
        f.read('GetFldType', {'h': rh, 't': i}, 4, label='field_type_%d' % i)
        f.read('GetFldFlag', {'h': rh, 't': i}, 0, label='field_flag_%d' % i)
    for obj, label in [(h, 'first'), (other, 'second')]:
        attached = f.mutate('SetRecord', {'h': obj, 'record': name}, label='attach_' + label)
        f.read('NumRecords', {'h': obj}, 1, label='attached_count_' + label, verifies=[attached])
        for field, value in fields:
            f.read('GetRField', {'h': obj, 'record': name, 'field': field}, value,
                   label='default_%s_%s' % (label, field), verifies=[attached])
    f.create('attached_record_handle', call('GetRecord', h=h, cnt=1), 'data_attached_record')
    f.read('GetName', {'h': capture('data_attached_record')}, name, label='attached_record_identity')
    for label, value in [('unicode', 'Étage 東京 — Δ'), ('empty', ''),
                         ('punctuation', '"quoted", apostrophe\'s, comma; equals=literal'),
                         ('long_text', 'Aé東' * 180)]:
        f.pair('SetRField', {'h': h, 'record': name, 'field': 'Label', 'value': value},
               'GetRField', {'h': h, 'record': name, 'field': 'Label'}, value, label='set_' + label)
        f.read('GetRField', {'h': other, 'record': name, 'field': 'Label'}, 'Default',
               label='other_instance_unchanged_' + label)
        f.read('GetRField', {'h': h, 'record': name, 'field': 'Unicode'}, 'Grüße 東京',
               label='other_field_unchanged_' + label)
    for empty in (True, False):
        f.pair('SetRFieldOpt', {'h': h, 'record': name, 'field': 'Notes', 'isEmpty': empty, 'isDataLinked': False},
               'GetRFieldOpt', {'h': h, 'record': name, 'field': 'Notes'}, [empty, False],
               label='empty_option_' + str(empty))
    detached = f.mutate('DelRecord', {'h': h, 'name': name})
    f.read('NumRecords', {'h': h}, 0, label='detached_count', verifies=[detached])
    f.read('NumRecords', {'h': other}, 1, label='other_attachment_survives', verifies=[detached])
    again = f.mutate('SetRecord', {'h': h, 'record': name}, label='reattach_defaults')
    f.read('GetRField', {'h': h, 'record': name, 'field': 'Label'}, 'Default',
           label='reattached_default', verifies=[again])
    return f.jobs


def _data_worksheet_values(run_id):
    f = _Fixture('data_worksheet_values')
    h = _worksheet(f, run_id)
    values = [(1, 1, '=6*7', 42), (2, 1, '=-2.5', -2.5),
              (3, 1, '=0', 0), (4, 1, '=2^10', 1024), (5, 1, '=1/8', .125)]
    for row, col, formula, expected in values:
        label = 'numeric_%d_%d' % (row, col)
        set_id = f.mutate('SetWSCellFormulaN', dict(_range(h, row, col), formula=formula), label=label)
        f.read('GetWSCellFormulaN', _cell(h, row, col), formula, label=label + '_formula', verifies=[set_id])
        recalc = f.mutate('RecalculateWS', {'worksheet': h}, label=label + '_recalc')
        f.read('GetWSCellValue', _cell(h, row, col), expected, label=label + '_value', verifies=[set_id, recalc])
    for row, value in [(1, 'Grüße 東京'), (2, 'quotation "test"; comma,'), (3, 'X' * 300)]:
        label = 'text_%d' % row
        set_id = f.mutate('SetWSCellFormulaN', dict(_range(h, row, 2), formula=value), label=label)
        recalc = f.mutate('RecalculateWS', {'worksheet': h}, label=label + '_recalc')
        f.read('GetWSCellStringN', _cell(h, row, 2), value, label=label + '_value', verifies=[set_id, recalc])
        f.read('GetWSCellFormulaN', _cell(h, row, 2), value, label=label + '_formula')
    fill = f.mutate('SetWSCellFormula', dict(_range(h, 4, 3, 5, 4), formula='range sentinel'), label='range_text')
    recalc = f.mutate('RecalculateWS', {'worksheet': h}, label='range_recalc')
    for row in (4, 5):
        for col in (3, 4):
            f.read('GetWSCellString', _cell(h, row, col), 'range sentinel',
                   label='range_cell_%d_%d' % (row, col), verifies=[fill, recalc])
    clear = f.mutate('ClearWSCell', _range(h, 4, 3), label='clear_one_range_cell')
    recalc = f.mutate('RecalculateWS', {'worksheet': h}, label='clear_recalc')
    f.read('GetWSCellFormulaN', _cell(h, 4, 3), '', label='cleared_formula', verifies=[clear, recalc])
    f.read('GetWSCellStringN', _cell(h, 4, 3), '', label='cleared_string')
    f.read('GetWSCellStringN', _cell(h, 4, 4), 'range sentinel', label='adjacent_cell_preserved')
    f.read('GetWSCellValue', _cell(h, 1, 1), 42, label='numeric_cell_preserved')
    return f.jobs


def _data_worksheet_classification(run_id):
    """Preserve disputed stored-value predicates independently of value tests.

    SDK vs.py25791/25807 and APIBase.Legacy.Defs.h7487-7494 describe the cell's
    actual value type. Reference.xml's GetWSCellString comment distinguishes a
    number's formatted display string from the type of the stored value. No
    source establishes that both predicates should be true for a numeric formula.
    Host 882075 returned True for both after '=6*7' evaluated to 42.0; the
    original False expectation remains a diagnostic, not a production correction.
    """
    f = _Fixture('data_worksheet_classification')
    h = _worksheet(f, run_id)
    for row, formula, expected in [(1, '=6*7', 42), (2, '=-2.5', -2.5),
                                    (3, '=0', 0), (4, '=2^10', 1024), (5, '=1/8', .125)]:
        label = 'numeric_%d_1' % row
        changed = f.mutate('SetWSCellFormulaN', dict(_range(h, row, 1), formula=formula), label=label)
        f.read('GetWSCellFormulaN', _cell(h, row, 1), formula, label=label + '_formula', verifies=[changed])
        recalc = f.mutate('RecalculateWS', {'worksheet': h}, label=label + '_recalc')
        f.read('GetWSCellValue', _cell(h, row, 1), expected, label=label + '_value', verifies=[changed, recalc])
        f.read('IsWSCellNumber', _cell(h, row, 1), True, label=label + '_is_number', verifies=[changed, recalc])
        f.read('IsWSCellString', _cell(h, row, 1), False, label=label + '_not_string', verifies=[changed, recalc])
    for row, value in [(1, 'Grüße 東京'), (2, 'quotation "test"; comma,'), (3, 'X' * 300)]:
        label = 'text_%d' % row
        changed = f.mutate('SetWSCellFormulaN', dict(_range(h, row, 2), formula=value), label=label)
        recalc = f.mutate('RecalculateWS', {'worksheet': h}, label=label + '_recalc')
        f.read('GetWSCellStringN', _cell(h, row, 2), value, label=label + '_value', verifies=[changed, recalc])
        f.read('GetWSCellFormulaN', _cell(h, row, 2), value, label=label + '_formula', verifies=[changed])
        f.read('IsWSCellString', _cell(h, row, 2), True, label=label + '_is_string', verifies=[changed, recalc])
        f.read('IsWSCellNumber', _cell(h, row, 2), False, label=label + '_not_number', verifies=[changed, recalc])
    return f.jobs


def _data_worksheet_boundaries(run_id):
    f = _Fixture('data_worksheet_boundaries')
    h = _worksheet(f, run_id)
    for row, col, expected in [(1, 1, True), (6, 5, True), (7, 5, False),
                               (6, 6, False), (-1, 1, False), (1, -1, False),
                               (0, 1, True), (1, 0, True), (0, 0, True)]:
        # SDK VectorScript Reference.xml and APIBase.Legacy.Defs.h describe
        # 0..rowCount/0..columnCount. Build 882075 returned False for (0,0).
        # Keep this documented oracle as a separate diagnostic family rather
        # than changing it to fit the host or blocking ordinary value tests.
        # Invalid cells enter only the validity predicate, never a dereference.
        f.read('IsValidWSCell', _cell(h, row, col), expected, label='bounds_%d_%d' % (row, col))
        if row == 0 or col == 0:
            f.jobs[-1]['known_issue'] = ('SDK-described zero boundary disagrees with an observed '
                                        '(0,0) result on host build 882075; unresolved documentation/host mismatch. '
                                        'A later runtime interruption followed a completed (0,0) check; causality is unproven')
    return f.jobs


def _data_worksheet_type_probe(run_id):
    """Observe both stored-value predicates after independently checked edits."""
    f = _Fixture('data_worksheet_type_probe')
    h = _worksheet(f, run_id, rows=7, columns=3)
    cases = [('empty', '', None), ('literal_integer', '42', 42),
             ('literal_negative', '-42', -42), ('literal_zero', '0', 0),
             ('numeric_formula', '=6*7', 42), ('ascii_text', 'hello', None),
             ('unicode_text', 'café 東京', None)]
    for row, (label, formula, number) in enumerate(cases, 1):
        changed = f.mutate('SetWSCellFormulaN', dict(_range(h, row, 1), formula=formula), label=label + '_seed')
        f.read('GetWSCellFormulaN', _cell(h, row, 1), formula, label=label + '_formula', verifies=[changed])
        recalc = f.mutate('RecalculateWS', {'worksheet': h}, label=label + '_recalc')
        if number is not None:
            f.read('GetWSCellValue', _cell(h, row, 1), number, label=label + '_value', verifies=[changed, recalc])
            f.read('GetWSCellStringN', _cell(h, row, 1), 'ok', path=['status'], label=label + '_display')
        else:
            f.read('GetWSCellStringN', _cell(h, row, 1), formula, label=label + '_display', verifies=[changed, recalc])
        for api, suffix in [('IsWSCellNumber', 'number'), ('IsWSCellString', 'string')]:
            # Observational response contracts do not establish predicate semantics.
            f.read(api, _cell(h, row, 1), 'ok', path=['status'], label=label + '_' + suffix)
    return f.jobs


def _data_worksheet_validity_probe(run_id):
    """Compare cell/range validity without dereferencing headers or bad bounds."""
    f = _Fixture('data_worksheet_validity_probe')
    h = _worksheet(f, run_id, rows=2, columns=3)
    for row, column in [(1, 1), (2, 3), (3, 3), (2, 4), (-1, 1), (1, -1),
                         (0, 1), (1, 0), (0, 0)]:
        label = 'cell_%d_%d' % (row, column)
        f.read('IsValidWSCell', _cell(h, row, column), 'ok', path=['status'], label=label)
        f.read('IsValidWSRange', _range(h, row, column), 'ok', path=['status'], label=label + '_range')
    for label, coords in [('full_normal', (1, 1, 2, 3)), ('full_headers', (0, 0, 2, 3)),
                           ('outside', (0, 0, 3, 4))]:
        f.read('IsValidWSRange', _range(h, *coords), 'ok', path=['status'], label=label)
    f.read('GetWSRowColumnCount', {'worksheet': h}, [2, 3], label='dimensions_unchanged')
    return f.jobs


def _data_worksheet_format(run_id):
    f = _Fixture('data_worksheet_format')
    h = _worksheet(f, run_id)
    target, outside = _range(h, 2, 2, 3, 3), _range(h, 5, 5)
    # Explicit outside baseline makes range-leakage assertions independent of user defaults.
    for api, getter, arg, baseline, edited in [
            ('SetWSCellWrapTextFlag', 'GetWSCellWrapTextFlag', 'wrapTextFlag', False, True),
            ('SetWSCellAlignment', 'GetWSCellAlignment', 'cellAlignment', 1, 3),
            ('SetWSCellVertAlignment', 'GetWSCellVertAlignment', 'vAlignment', 1, 5),
            ('SetWSTextAngle', 'GetWSCellTextAngle', 'angle', 0, 90)]:
        baseline_id = f.mutate(api, dict(outside, **{arg: baseline}), label=api + '_baseline')
        changed = f.mutate(api, dict(target, **{arg: edited}), label=api + '_range')
        for row, col in [(2, 2), (2, 3), (3, 2), (3, 3)]:
            f.read(getter, _cell(h, row, col), edited, label=api + '_%d_%d' % (row, col), verifies=[changed])
        f.read(getter, _cell(h, 5, 5), baseline, label=api + '_outside_preserved', verifies=[baseline_id, changed])
    for accuracy in (0, 2, 6):
        # SDK WorksheetNumberFormatTable: 1=fixed decimal; accuracy=decimal places.
        f.pair('SetWSCellNumberFormat', dict(target, style=1, accuracy=accuracy, leaderString='', trailerString=''),
               'GetWSCellNumberFormat', _cell(h, 2, 2), [1, accuracy, '', ''], label='fixed_decimal_%d' % accuracy)
    _numeric_capture(f, 'red_color_index', 'RGBToColorIndex', {'red': 65535, 'green': 0, 'blue': 0}, 'data_ws_red')
    red = capture('data_ws_red')
    colored = f.mutate('SetWSCellTextColor', dict(target, color=red))
    f.add('read_text_color_index', native_call=call('GetWSCellTextColor', **_cell(h, 3, 3)),
          expected=[1, 2147483647], predicate='range_inclusive', captures='data_ws_actual_red')
    f.read('ColorIndexToRGB', {'color': capture('data_ws_actual_red')}, [65535, 0, 0], verifies=[colored])
    # One defined fill mode avoids depending on ignored bgcolor/pattern return values.
    fill = f.mutate('SetWSCellFill', dict(target, style=1, bgcolor=red, fgcolor=red, fillpattern=-1))
    f.read('GetWSCellFill', _cell(h, 2, 2), 1, path=['result', 0], verifies=[fill])
    for index, label in [(1, 'background'), (2, 'foreground')]:
        key = 'data_ws_fill_' + label
        f.add('read_fill_' + label, native_call=call('GetWSCellFill', **_cell(h, 2, 2)),
              expected=[1, 2147483647], predicate='range_inclusive', path=['result', index], captures=key)
        f.read('ColorIndexToRGB', {'color': capture(key)}, [65535, 0, 0],
               label='fill_' + label + '_rgb', verifies=[fill])
    _numeric_capture(f, 'font_arial', 'GetFontID', {'fontName': 'Arial'}, 'data_ws_font')
    text = f.mutate('SetWSCellTextFormat', dict(target, fontIndex=capture('data_ws_font'), size=18, style=1))
    f.read('GetWSCellTextFormat', _cell(h, 2, 2), 18, path=['result', 1], label='text_size', verifies=[text])
    f.read('GetWSCellTextFormat', _cell(h, 2, 2), 1, path=['result', 2], label='bold_style', verifies=[text])
    f.add('assigned_font_index', native_call=call('GetWSCellTextFormat', **_cell(h, 2, 2)),
          expected=[1, 32767], predicate='range_inclusive', path=['result', 0], captures='data_ws_assigned_font')
    f.read('GetFontName', {'fontID': capture('data_ws_assigned_font')}, 'Arial', verifies=[text])
    borders = f.mutate('SetWSCellBorders', dict(_range(h, 1, 1), top=True, left=False,
                                              bottom=True, right=False, OutlineInside=0))
    f.read('GetWSCellBorder', _cell(h, 1, 1), [True, False, True, False], verifies=[borders])
    for visible in (False, True):
        f.pair('SetWorksheetGridLinesVisibility', {'h': h, 'visible': visible},
               'AreWorksheetGridLinesVisible', {'h': h}, visible, label='grid_' + str(visible))
    for locked in (True, False):
        change = f.mutate('SetWSRowHeight', {'worksheet': h, 'fromRow': 2, 'toRow': 3,
                                            'height': 36, 'updatePalette': False, 'lockHeight': locked},
                          label='row_lock_' + str(locked))
        f.read('GetWSRowHLockState', {'worksheet': h, 'row': 2}, locked,
               label='row_lock_read_' + str(locked), verifies=[change])
        if locked:
            f.read('GetWSRowHeight', {'worksheet': h, 'row': 3}, 36, verifies=[change])
    return f.jobs


def _data_worksheet_structure(run_id):
    f = _Fixture('data_worksheet_structure')
    h = _worksheet(f, run_id, 4, 4)
    seed = f.mutate('SetWSCellFormulaN', dict(_range(h, 2, 2), formula='Moving sentinel'), label='seed_cell')
    f.read('GetWSCellFormulaN', _cell(h, 2, 2), 'Moving sentinel', label='seed_readback', verifies=[seed])
    inserted = f.mutate('InsertWSRows', {'worksheet': h, 'beforeRow': 2, 'numRows': 2})
    f.read('GetWSRowColumnCount', {'worksheet': h}, [6, 4], label='rows_after_insert', verifies=[inserted])
    f.read('GetWSCellFormulaN', _cell(h, 4, 2), 'Moving sentinel', label='row_content_moves', verifies=[inserted])
    f.read('GetWSCellFormulaN', _cell(h, 2, 2), '', label='new_row_is_blank')
    inserted_col = f.mutate('InsertWSColumns', {'worksheet': h, 'beforeColumn': 2, 'numColumns': 1})
    f.read('GetWSCellFormulaN', _cell(h, 4, 3), 'Moving sentinel', label='column_content_moves', verifies=[inserted_col])
    removed_rows = f.mutate('DeleteWSRows', {'worksheet': h, 'startRow': 2, 'numRows': 2})
    f.read('GetWSCellFormulaN', _cell(h, 2, 3), 'Moving sentinel', label='row_content_returns', verifies=[removed_rows])
    removed_col = f.mutate('DeleteWSColumns', {'worksheet': h, 'startColumn': 2, 'numColumns': 1})
    f.read('GetWSCellFormulaN', _cell(h, 2, 2), 'Moving sentinel', label='column_content_returns', verifies=[removed_col])
    f.read('GetWSRowColumnCount', {'worksheet': h}, [4, 4], label='original_dimensions_restored')
    merged = f.mutate('WorksheetMergeCells', _range(h, 3, 1, 4, 2), returns=True)
    f.read('GetWSMergedCellRange', _cell(h, 3, 1), [True, 3, 1, 4, 2], verifies=[merged])
    split = f.mutate('WorksheetSplitCells', _range(h, 3, 1, 4, 2), returns=True)
    f.read('GetWSMergedCellRange', _cell(h, 3, 1), False, path=['result', 0], label='split_range', verifies=[split])
    f.read('GetWSCellFormulaN', _cell(h, 2, 2), 'Moving sentinel', label='merge_preserves_unrelated_cell')
    return f.jobs


def _database_setup(f, run_id, values):
    """Only objects bearing this new record can enter the database criteria."""
    record = DESIGN.fixture_name('SDK-' + f.family + '-Record-', run_id)
    field = f.mutate('NewField', {'recName': record, 'fieldName': 'Label', 'fieldValue': 'Default',
                                'fType': 4, 'fFlag': 0}, label='create_record_field')
    key = f.family + '_record'
    f.create('find_record', call('GetObject', name=record), key)
    f.read('NumFields', {'h': capture(key)}, 1, label='record_field_count', verifies=[field])
    objects = []
    for index, value in enumerate(values):
        key = f.family + '_object_%d' % index
        created = f.rectangle(key, (1100 + index * 40, 20), (1130 + index * 40, 0))
        obj = capture(key)
        f.read('GetTypeN', {'h': obj}, 3, label='object_%d_type' % index, verifies=[created])
        attached = f.mutate('SetRecord', {'h': obj, 'record': record}, label='attach_record_%d' % index)
        f.read('GetRField', {'h': obj, 'record': record, 'field': 'Label'}, 'Default',
               label='attached_default_%d' % index, verifies=[attached])
        f.pair('SetRField', {'h': obj, 'record': record, 'field': 'Label', 'value': value},
               'GetRField', {'h': obj, 'record': record, 'field': 'Label'}, value, label='label_%d' % index)
        objects.append(obj)
    # A fresh, unrelated rectangle proves the criteria do not match all geometry.
    f.rectangle(f.family + '_unrelated', (1240, 20), (1270, 0))
    h = _worksheet(f, run_id, rows=4, columns=3)
    f.pair('SetWSAutoRecalcState', {'worksheet': h, 'state': False},
           'GetWSAutoRecalcState', {'worksheet': h}, False, label='manual_recalculation')
    # SDK XML SetWSCellFormulaN explicitly permits column0 for database criteria.
    database = f.mutate('SetWSCellFormulaN', dict(_range(h, 2, 0), formula="=DATABASE(R IN ['" + record + "'])"),
                        label='define_database')
    f.read('IsWSDatabaseRow', {'worksheet': h, 'databaseRow': 2}, True, label='database_row', verifies=[database])
    f.read('IsWSDatabaseRow', {'worksheet': h, 'databaseRow': 1}, False, label='ordinary_row')
    for column, formula in [(1, "='" + record + "'.'Label'"), (2, '=6*7'), (3, "='" + record + "'.'Label'")]:
        changed = f.mutate('SetWSCellFormulaN', dict(_range(h, 2, column), formula=formula), label='database_column_%d' % column)
        f.read('GetWSCellFormulaN', _cell(h, 2, column), formula,
               label='column_formula_%d' % column, verifies=[changed])
    calculated = f.mutate('RecalculateWS', {'worksheet': h}, label='initial_database_recalc')
    f.read('GetWSSubrowCount', {'worksheet': h, 'databaseRow': 2}, len(values), label='initial_subrow_count', verifies=[calculated])
    return h, record, objects


def _subrow(h, column=1, index=1):
    return {'worksheet': h, 'row': 2, 'column': column, 'subrow': index}


def _data_worksheet_database(run_id):
    f = _Fixture('data_worksheet_database')
    h, record, objects = _database_setup(f, run_id, ['Alpha café 東京'])
    string_apis = ('GetWSSubrowActualCellString', 'GetWSSubrowActualStringN',
                   'GetWSSubrowCellString', 'GetWSSubrowCellStrN')
    for api in string_apis:
        f.read(api, _subrow(h), 'Alpha café 東京', label=api + '_initial')
    f.read('GetWSSubrowCellValue', _subrow(h, 2), 42, label='numeric_subrow_value')
    # The SDK describes a range of displayed subrows, not an independent
    # column-bounds guard. Host 882075 returns True for existing subrow1 even
    # at column4/5 on this 4x3 sheet. Preserve the original failed run and
    # read-only diagnosis; test storage bounds explicitly instead of changing
    # that ambiguous expectation to True or normalizing the native result.
    f.read('GetWSRowColumnCount', {'worksheet': h}, [4, 3], label='database_dimensions_preserved')
    for column, expected in ((3, True), (4, False), (5, False)):
        f.read('IsValidWSCell', _cell(h, 2, column), expected, label='database_cell_bounds_%d' % column)
        f.read('IsValidWSRange', _range(h, 2, column), expected, label='database_range_bounds_%d' % column)
    for column, subrow, expected in [(1, 1, True), (3, 1, True), (1, 2, False)]:
        f.read('IsValidWSSubrowCell', _subrow(h, column, subrow), expected,
               label='valid_subrow_%d_%d' % (column, subrow))
    f.read('IsValidWSSubrowCell', dict(_subrow(h), row=1), False, label='ordinary_row_has_no_subrow')
    changed = f.mutate('SetRField', {'h': objects[0], 'record': record, 'field': 'Label', 'value': 'Updated façade'}, label='update_source_record')
    f.read('GetRField', {'h': objects[0], 'record': record, 'field': 'Label'}, 'Updated façade',
           label='source_record_updated', verifies=[changed])
    calculated = f.mutate('RecalculateWS', {'worksheet': h}, label='record_change_recalc')
    for api in string_apis:
        f.read(api, _subrow(h), 'Updated façade', label=api + '_updated', verifies=[changed, calculated])
    # Record removal changes membership without deleting drawing geometry.
    removed = f.mutate('DelRecord', {'h': objects[0], 'name': record}, label='remove_membership')
    f.read('NumRecords', {'h': objects[0]}, 0, label='record_removed', verifies=[removed])
    calculated = f.mutate('RecalculateWS', {'worksheet': h}, label='empty_database_recalc')
    f.read('GetWSSubrowCount', {'worksheet': h, 'databaseRow': 2}, 0, label='empty_database', verifies=[removed, calculated])
    f.read('IsValidWSSubrowCell', _subrow(h), False, label='removed_subrow_invalid')
    f.read('GetBBox', {'h': objects[0]}, [[1100, 20], [1130, 0]], label='membership_preserves_geometry')
    return f.jobs


def _data_worksheet_operators(run_id):
    f = _Fixture('data_worksheet_operators')
    h, record, objects = _database_setup(f, run_id, ['Beta', 'Alpha'])
    # MiniCadCallBacks.h4529-4543: sort0, summarize1, sum-values2;
    # sort direction ascending0/descending1 and remove-all-types sentinel-1.
    operator_args = lambda col, kind: {'worksheet': h, 'databaseRow': 2, 'column': col, 'operatorType': kind}
    for column in (1, 3):
        f.read('HasWSColumnOperator', operator_args(column, 0), False, label='initial_sort_%d' % column)
    added = f.mutate('AddWSColumnOperator', operator_args(1, 0), label='add_sort')
    f.read('HasWSColumnOperator', operator_args(1, 0), True, label='sort_added', verifies=[added])
    for label, sort_type, expected in [('ascending', 0, ['Alpha', 'Beta']), ('descending', 1, ['Beta', 'Alpha'])]:
        changed = f.mutate('SetWSColumnSortType', {'worksheet': h, 'databaseRow': 2, 'column': 1, 'sortType': sort_type}, label=label)
        f.read('GetWSColumnSortType', {'worksheet': h, 'databaseRow': 2, 'column': 1}, sort_type,
               label=label + '_type', verifies=[changed])
        calculated = f.mutate('RecalculateWS', {'worksheet': h}, label=label + '_recalc')
        for index, value in enumerate(expected, 1):
            f.read('GetWSSubrowActualStringN', _subrow(h, 1, index), value,
                   label='%s_item_%d' % (label, index), verifies=[added, changed, calculated])
    moved = f.mutate('MoveWSColumnOperator', {'worksheet': h, 'databaseRow': 2, 'fromColumn': 1, 'toColumn': 3, 'operatorType': 0}, label='move_sort')
    f.read('HasWSColumnOperator', operator_args(1, 0), False, label='old_sort_removed', verifies=[moved])
    f.read('HasWSColumnOperator', operator_args(3, 0), True, label='new_sort_present', verifies=[moved])
    removed = f.mutate('RemoveWSColumnOperator', operator_args(3, 0), label='remove_sort')
    f.read('HasWSColumnOperator', operator_args(3, 0), False, label='sort_removed', verifies=[removed])
    for label, column, kind in [('sort', 1, 0), ('summarize', 3, 1), ('sum_values', 2, 2)]:
        added = f.mutate('AddWSColumnOperator', operator_args(column, kind), label='add_' + label + '_again')
        f.read('HasWSColumnOperator', operator_args(column, kind), True, label=label + '_present', verifies=[added])
    cleared = f.mutate('RemoveAllWSColumnOperators', {'worksheet': h, 'databaseRow': 2, 'operatorType': -1}, label='clear_all_operators')
    for column in (1, 2, 3):
        for kind in (0, 1, 2):
            f.read('HasWSColumnOperator', operator_args(column, kind), False,
                   label='cleared_operator_%d_%d' % (column, kind), verifies=[cleared])
    calculated = f.mutate('RecalculateWS', {'worksheet': h}, label='final_recalc')
    f.read('GetWSSubrowCount', {'worksheet': h, 'databaseRow': 2}, 2, label='members_preserved', verifies=[calculated])
    for index, value in enumerate(['Beta', 'Alpha']):
        f.read('GetRField', {'h': objects[index], 'record': record, 'field': 'Label'}, value, label='source_%d_preserved' % index)
    return f.jobs


def _data_worksheet_edge_edits(run_id):
    f = _Fixture('data_worksheet_edge_edits')
    h = _worksheet(f, run_id, 4, 4)
    other = _worksheet(f, run_id, 4, 4, suffix='control')
    seeds = [(1, 1, 'NW'), (1, 4, 'NE'), (4, 1, 'SW'), (4, 4, 'SE'), (2, 2, '=6*7')]
    for row, column, value in seeds:
        f.pair('SetWSCellFormulaN', dict(_range(h, row, column), formula=value),
               'GetWSCellFormulaN', _cell(h, row, column), value, label='seed_%d_%d' % (row, column))
    f.pair('SetWSCellFormulaN', dict(_range(other, 2, 2), formula='Untouched control'),
           'GetWSCellFormulaN', _cell(other, 2, 2), 'Untouched control', label='seed_control')
    cases = [
        ('insert_first_row', 'InsertWSRows', {'beforeRow': 1, 'numRows': 1}, [5, 4],
         [(2, 1, 'NW'), (2, 4, 'NE'), (5, 1, 'SW'), (5, 4, 'SE'), (3, 2, '=6*7'), (1, 1, '')]),
        ('insert_first_columns', 'InsertWSColumns', {'beforeColumn': 1, 'numColumns': 2}, [5, 6],
         [(2, 3, 'NW'), (2, 6, 'NE'), (5, 3, 'SW'), (5, 6, 'SE'), (3, 4, '=6*7'), (2, 1, ''), (2, 2, '')]),
        ('delete_last_row', 'DeleteWSRows', {'startRow': 5, 'numRows': 1}, [4, 6],
         [(2, 3, 'NW'), (2, 6, 'NE'), (3, 4, '=6*7'), (4, 3, '')]),
        ('delete_last_column', 'DeleteWSColumns', {'startColumn': 6, 'numColumns': 1}, [4, 5],
         [(2, 3, 'NW'), (3, 4, '=6*7'), (2, 5, '')]),
        ('delete_first_row', 'DeleteWSRows', {'startRow': 1, 'numRows': 1}, [3, 5],
         [(1, 3, 'NW'), (2, 4, '=6*7')]),
        ('delete_first_columns', 'DeleteWSColumns', {'startColumn': 1, 'numColumns': 2}, [3, 3],
         [(1, 1, 'NW'), (2, 2, '=6*7')]),
    ]
    for label, api, args, dimensions, checks in cases:
        changed = f.mutate(api, dict(worksheet=h, **args), label=label)
        f.read('GetWSRowColumnCount', {'worksheet': h}, dimensions, label=label + '_dimensions', verifies=[changed])
        for row, column, expected in checks:
            f.read('GetWSCellFormulaN', _cell(h, row, column), expected,
                   label='%s_cell_%d_%d' % (label, row, column), verifies=[changed])
        f.read('GetWSRowColumnCount', {'worksheet': other}, [4, 4], label=label + '_control_dimensions')
        f.read('GetWSCellFormulaN', _cell(other, 2, 2), 'Untouched control', label=label + '_control_value')
    calculated = f.mutate('RecalculateWS', {'worksheet': h}, label='final_recalculate')
    f.read('GetWSCellValue', _cell(h, 2, 2), 42, label='formula_value_preserved', verifies=[calculated])
    return f.jobs


def _data_materials(run_id):
    f = _Fixture('data_materials')
    name = DESIGN.fixture_name('SDK-Data-Material-', run_id)
    texture_name = DESIGN.fixture_name('SDK-Data-Texture-', run_id)
    material = f.create('create_material', call('CreateMaterial', name=name, isSimpleMaterial=True), 'data_material')
    mh = capture('data_material')
    f.read('IsMaterialSimple', {'materialHandle': mh}, True, verifies=[material])
    texture = f.create('create_texture', call('CreateTexture'), 'data_texture')
    th = capture('data_texture')
    f.pair('SetName', {'h': th, 'name': texture_name}, 'GetName', {'h': th}, texture_name, label='texture_name')
    for size in (.125, 12.0, 1200.0):
        f.pair('SetTextureSize', {'texture': th, 'newSize': size}, 'GetTextureSize', {'texture': th}, size,
               label='texture_size_' + str(size).replace('.', '_'))
    _numeric_capture(f, 'texture_index', 'Name2Index', {'name': texture_name}, 'data_texture_index')
    f.read('Index2Name', {'index': capture('data_texture_index')}, texture_name, verifies=[texture])
    assigned = f.add('assign_material_texture', native_call=call('SetMaterialTexture', materialHandle=mh,
                         textureIndex=capture('data_texture_index')), expected=True, path=['result', 0], phase='mutation')
    f.jobs[-1]['assertions'].append({'path': ['result', 1], 'valid_uuid': True})
    f.jobs[-1]['capture'] = {'name': 'data_textured_material', 'path': ['result', 1]}
    mh = capture('data_textured_material')
    _numeric_capture(f, 'read_material_texture', 'GetMaterialTexture', {'objectHandle': mh}, 'data_material_texture_index')
    f.read('Index2Name', {'index': capture('data_material_texture_index')}, texture_name,
           label='material_texture_identity', verifies=[assigned])
    for style in (0, 1):
        f.pair('SetMaterialFillStyle', {'materialHandle': mh, 'fillStyle': style},
               'GetMaterialFillStyle', {'materialHandle': mh}, style, returns=True, label='material_fill_%d' % style)
    f.rectangle('data_material_profile', (850, 20), (880, 0))
    solid = f.create('create_material_solid', call('HExtrude', objectH=capture('data_material_profile'),
                                                bottom=0.0, top=10.0), 'data_material_solid')
    obj = capture('data_material_solid')
    f.read('GetTypeN', {'h': obj}, 24, label='material_solid_type', verifies=[solid])
    f.read('GetObjMaterialHandle', {'h': obj}, None, label='unassigned_material_handle', verifies=[solid])
    f.read('GetObjMaterialName', {'h': obj}, [False, ''], label='unassigned_material_name', verifies=[solid])
    attach = f.add('assign_object_material', native_call=call('SetObjMaterialHandle', objectHandle=obj,
                    materialHandle=mh), expected=True, path=['result', 0], phase='mutation')
    f.jobs[-1]['assertions'].append({'path': ['result', 1], 'valid_uuid': True})
    f.jobs[-1]['capture'] = {'name': 'data_assigned_solid', 'path': ['result', 1]}
    obj = capture('data_assigned_solid')
    f.read('GetObjMaterialName', {'h': obj}, [True, name], verifies=[attach])
    f.create('object_material_handle', call('GetObjMaterialHandle', h=obj), 'data_object_material_handle')
    f.read('GetName', {'h': capture('data_object_material_handle')}, name, label='object_material_identity', verifies=[attach])
    f.read('Get3DInfo', {'h': obj}, [20, 30, 10], label='material_preserves_dimensions')
    return f.jobs


def _data_resource_tags(run_id):
    f = _Fixture('data_resource_tags')
    name = DESIGN.fixture_name('SDK-Data-Tagged-', run_id)
    created = f.create('create_tagged_material', call('CreateMaterial', name=name, isSimpleMaterial=True), 'data_tagged_material')
    h = capture('data_tagged_material')
    f.read('GetNumResourceTags', {'handle': h}, 0, label='initial_tags', verifies=[created])
    tag = 'façade 東京 ' + run_id
    tagged = f.mutate('SetResourceTags', {'handle': h, 'tags': [tag]})
    f.read('GetNumResourceTags', {'handle': h}, 1, label='tag_count', verifies=[tagged])
    f.read('GetResourceTags', {'handle': h}, [tag], verifies=[tagged])
    f.read('GetName', {'h': h}, name, label='tags_preserve_resource_identity')
    return f.jobs


def data_fixtures(run_id, families=None):
    """Return independently runnable families; construction never executes APIs."""
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id):
        raise ValueError('Invalid run_id')
    selected = list(FAMILIES if families is None else families)
    if not selected or len(set(selected)) != len(selected) or any(item not in FAMILIES for item in selected):
        raise ValueError('Select unique known fixture families')
    builders = {name: globals()['_' + name] for name in FAMILIES}
    jobs = [job for family in selected for job in builders[family](run_id)]
    for job in jobs:
        job['evidence_basis'] = ('SDK 3200 vs.py and VectorScript Reference.xml; concrete data, '
                                 'documented selectors and later independent readback')
        if job['fixture_family'] == 'data_worksheet_format':
            job['prerequisites'].append('Arial font installed; GetFontID must return a positive font index before formatting')
        if job['fixture_family'] == 'data_records':
            job['prerequisites'].append('Disposable document has no automatic Data Manager record-attachment rules')
        if job['fixture_family'] == 'data_materials':
            job['prerequisites'].append('Fresh extrusion has no material assigned by document defaults or automatic class rules')
        if job['fixture_family'] in ('data_worksheet_database', 'data_worksheet_operators'):
            job['prerequisites'].append('Database criteria use only the unique fixture record; column0 is used only for documented database definition')
            job['prerequisites'].append('No Data Manager rules attach additional records to fresh rectangles; database subrows are read only after a separate RecalculateWS job')
        if job['fixture_family'] == 'data_worksheet_database':
            job['evidence_basis'] += ('; IsValidWSSubrowCell is tested for existing/missing displayed subrows, while dimensions and '
                                      'IsValidWSCell/IsValidWSRange establish column bounds. The SDK XML description is ambiguous about '
                                      'column validation and marks its documentation as needing attention. Original out-of-range-column '
                                      'failure remains in .audit/rootcause-batch-20260926-f/012-78d69a52dec2/result.json; independent '
                                      'read-only diagnosis remains in .audit/worksheet-limits-native-20260926-a/result.json')
        if job['fixture_family'] in DIAGNOSTIC_FAMILIES:
            job['diagnostic_only'] = True
            job['prerequisites'].append('Explicitly select this diagnostic family; exclude it from routine native batches')
        if job['fixture_family'] in CHARACTERIZATION_FAMILIES:
            job['verification_dimension'] = 'characterization'
            job['evidence_basis'] = ('SDK 3200 APIBase.Legacy.Defs.h7312-7321,7460-7494; '
                                     'observational classification and validity results are not semantic pass evidence')
            job['prerequisites'].append('Keep characterization results separate from semantic native pass coverage')
        if job['fixture_family'] == 'data_worksheet_classification':
            job['known_issue'] = ('Both IsWSCellNumber and IsWSCellString returned True after =6*7 evaluated to 42.0 '
                                  'on host build 882075. Stored-value classification semantics remain unresolved; '
                                  'original numeric-not-string expectation is preserved')
        if job['fixture_family'] == 'data_worksheet_boundaries':
            job['prerequisites'].append('Disputed zero boundary retained; runtime interruption was observed after the last '
                                        'completed invocation, without proof that IsValidWSCell caused it')
    return jobs
