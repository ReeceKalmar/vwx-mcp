"""Pending SDK 3200 annotation fixtures, with literal and topological oracles.

Sources: SDK vs.py, VectorScript Reference.xml, and APIBase.Legacy.Defs.h's
text constants. Only newly created, uniquely named objects/resources are edited.
Fonts are resolved by name; no document text defaults or selections are changed.
No API executes while constructing these plans.
"""
import importlib.util
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location('sdk_annotation_design_helpers', ROOT / 'tools/sdk_design_fixtures.py')
DESIGN = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(DESIGN)
_Fixture, call, capture = DESIGN._Fixture, DESIGN.call, DESIGN.capture
FAMILIES = ('annotation_text_runs', 'annotation_text_layout', 'annotation_text_styles',
            'annotation_text_replacements', 'annotation_ws_borders', 'annotation_ws_images',
            'annotation_text_leading_sentinel', 'annotation_ws_border_clearing',
            'annotation_unicode_length', 'annotation_text_length_encoding',
            'annotation_text_style_scope', 'annotation_text_offset_units', 'annotation_ws_border_scope',
            'annotation_text_utf16_runs', 'annotation_text_utf16_lengths', 'annotation_text_style_size_scope')
DIAGNOSTIC_FAMILIES = ('annotation_text_leading_sentinel', 'annotation_text_styles',
                       'annotation_ws_border_clearing', 'annotation_unicode_length',
                       'annotation_text_length_encoding', 'annotation_text_style_scope',
                       'annotation_text_offset_units', 'annotation_ws_border_scope', 'annotation_text_style_size_scope')
CHARACTERIZATION_FAMILIES = ('annotation_text_length_encoding', 'annotation_text_style_scope',
                             'annotation_text_offset_units', 'annotation_ws_border_scope', 'annotation_text_style_size_scope')


def _positive(f, label, name, arguments, key, maximum=2147483647):
    return f.add(label, native_call=call(name, **arguments), predicate='range_inclusive',
                 expected=[1, maximum], captures=key)


def _named_text(f, run_id, content, suffix=''):
    prefix = suffix + '_' if suffix else ''
    key = f.family + '_' + prefix + 'text'
    created = f.create(prefix + 'create_text', [call('CreateText', theText=content), call('LNewObj')], key)
    h = capture(key)
    f.read('GetText', {'objectHd': h}, content, label=prefix + 'initial_text', verifies=[created])
    name = DESIGN.fixture_name('SDK-' + f.family + ('-' + suffix if suffix else '') + '-', run_id)
    f.pair('SetName', {'h': h, 'name': name}, 'GetName', {'h': h}, name, label=prefix + 'name_text')
    return h


def _worksheet(f, run_id, rows=6, columns=6, suffix=''):
    prefix = suffix + '_' if suffix else ''
    name = DESIGN.fixture_name('SDK-' + f.family + ('-' + suffix if suffix else '') + '-', run_id)
    key = f.family + '_' + prefix + 'sheet'
    created = f.create(prefix + 'create_sheet', call('CreateWS', name=name, rows=rows, columns=columns), key)
    h = capture(key)
    f.read('GetName', {'h': h}, name, label=prefix + 'sheet_name', verifies=[created])
    f.read('GetWSRowColumnCount', {'worksheet': h}, [rows, columns], label=prefix + 'sheet_dimensions')
    return h, name


def _cell(h, row, column):
    return {'worksheet': h, 'row': row, 'column': column}


def _range(h, top, left, bottom, right):
    return {'worksheet': h, 'topRow': top, 'leftColumn': left,
            'bottomRow': bottom, 'rightColumn': right}


def _text_chars(f, h, label, api, expected, verifies):
    # Expectations are explicit per-character vectors, not derived by replaying
    # the setter's start/count calculation.
    for position, value in enumerate(expected):
        f.read(api, {'TextHd': h, 'Position': position}, value,
               label='%s_char_%d' % (label, position), verifies=verifies)


def _font_chars(f, h, label, expected_names, verifies):
    for position, name in enumerate(expected_names):
        key = '%s_%s_font_%d' % (f.family, label, position)
        _positive(f, key, 'GetTextFont', {'objectHd': h, 'Position': position}, key, 32767)
        f.read('GetFontName', {'fontID': capture(key)}, name,
               label='%s_font_name_%d' % (label, position), verifies=verifies)


def _annotation_text_runs(run_id):
    f = _Fixture('annotation_text_runs')
    h = _named_text(f, run_id, 'ABCDEF')
    unstyle = f.mutate('SetTextStyleRef', {'objectId': h, 'textStyleRef': 0}, label='unstyle_text')
    f.read('GetTextStyleRef', {'objectId': h}, 0, label='unstyled_ref', verifies=[unstyle])
    f.add('font_inventory', native_call=call('GetFontListSize'), expected=[2, 32767], predicate='range_inclusive')
    for label, name in [('arial', 'Arial'), ('courier', 'Courier New')]:
        _positive(f, label + '_font', 'GetFontID', {'fontName': name}, label + '_font', 32767)
        f.read('GetFontName', {'fontID': capture(label + '_font')}, name, label=label + '_identity')
    plain = f.mutate('SetTextStyle', {'objectHd': h, 'Start': 0, 'Count': 6, 'Style': 0}, label='plain_all')
    _text_chars(f, h, 'plain_all', 'GetTextStyle', [0, 0, 0, 0, 0, 0], [plain])
    baseline = f.mutate('SetTextFont', {'objectHd': h, 'Start': 0, 'Count': 6,
                                      'FontNum': capture('arial_font')}, label='arial_all')
    _font_chars(f, h, 'arial_all', ['Arial'] * 6, [baseline])
    middle = f.mutate('SetTextFont', {'objectHd': h, 'Start': 2, 'Count': 2,
                                    'FontNum': capture('courier_font')}, label='courier_middle')
    _font_chars(f, h, 'courier_middle', ['Arial', 'Arial', 'Courier New', 'Courier New', 'Arial', 'Arial'], [middle])
    initial = f.mutate('SetTextSize', {'objectHd': h, 'Start': 0, 'Count': 6, 'Size': 12.0}, label='size_all')
    _text_chars(f, h, 'size_all', 'GetTextSize', [12, 12, 12, 12, 12, 12], [initial])
    for label, start, count, size, expected in [
            ('size_first', 0, 1, 7.5, [7.5, 12, 12, 12, 12, 12]),
            ('size_middle', 2, 2, 18.25, [7.5, 12, 18.25, 18.25, 12, 12]),
            ('size_last', 5, 1, 36.0, [7.5, 12, 18.25, 18.25, 12, 36])]:
        changed = f.mutate('SetTextSize', {'objectHd': h, 'Start': start, 'Count': count, 'Size': size}, label=label)
        _text_chars(f, h, label, 'GetTextSize', expected, [changed])
    # SDK legacy docs require an initial plain reset before setting styles.
    for label, start, count, style, expected in [
            ('bold_first', 0, 1, 1, [1, 0, 0, 0, 0, 0]),
            ('italic_middle', 2, 2, 2, [1, 0, 2, 2, 0, 0]),
            ('underline_last', 5, 1, 4, [1, 0, 2, 2, 0, 4]),
            ('clear_middle', 2, 2, 0, [1, 0, 0, 0, 0, 4])]:
        changed = f.mutate('SetTextStyle', {'objectHd': h, 'Start': start, 'Count': count, 'Style': style}, label=label)
        _text_chars(f, h, label, 'GetTextStyle', expected, [changed])
    _text_chars(f, h, 'styles_preserve_sizes', 'GetTextSize', [7.5, 12, 18.25, 18.25, 12, 36], [])
    _font_chars(f, h, 'styles_preserve_fonts', ['Arial', 'Arial', 'Courier New', 'Courier New', 'Arial', 'Arial'], [])
    f.read('GetText', {'objectHd': h}, 'ABCDEF', label='formatting_preserves_content')
    f.read('GetTextLength', {'TextHd': h}, 6, label='formatting_preserves_length')
    return f.jobs


def _annotation_text_layout(run_id):
    f = _Fixture('annotation_text_layout')
    h = _named_text(f, run_id, 'Layout Alpha Beta')
    # SDK APIBase.Legacy.Defs.h: single=2, one-and-a-half=3, double=4,
    # custom=0. Leading and point size use points, independent of document units.
    for spacing in (2, 3, 4, 2):
        label = 'spacing_%d_%d' % (spacing, len(f.jobs))
        f.pair('SetTextSpace', {'theText': h, 'spacing': spacing}, 'GetTextSpace', {'theText': h}, spacing, label=label)
    for leading in (12.0, 18.5, 48.0):
        label = 'leading_' + str(leading).replace('.', '_')
        changed = f.mutate('SetTextLeading', {'theText': h, 'leading': leading}, label=label)
        f.read('GetTextLeading', {'theText': h}, leading, label=label + '_read', verifies=[changed])
        f.read('GetTextSpace', {'theText': h}, 0, label=label + '_custom_mode', verifies=[changed])
    for justification in (1, 2, 3, 1):
        label = 'justify_%d_%d' % (justification, len(f.jobs))
        f.pair('SetTextJustN', {'TextHd': h, 'JustFlag': justification}, 'GetTextJust',
               {'TextHd': h}, justification, label=label)
    for alignment in (1, 3, 5, 1):
        label = 'vertical_%d_%d' % (alignment, len(f.jobs))
        f.pair('SetTextVertAlignN', {'TextHd': h, 'verticalAlignment': alignment},
               'GetTextVerticalAlign', {'TextHd': h}, alignment, label=label)
    # This tests the N functions' alignment values, not a font-dependent visual
    # location claim; alignment changes can alter the text insertion anchor.
    f.read('GetText', {'objectHd': h}, 'Layout Alpha Beta', label='layout_preserves_content')
    f.read('GetTextLeading', {'theText': h}, 48.0, label='alignment_preserves_leading')
    return f.jobs


def _annotation_text_leading_sentinel(run_id):
    f = _Fixture('annotation_text_leading_sentinel')
    h = _named_text(f, run_id, 'Leading sentinel')
    # Reference.xml GetTextLeading says -1.0 when no custom value is set.
    # Build 882075 returned 0.0 after SetTextSpace(2); retain that disputed
    # contract independently so explicit custom-leading tests can proceed.
    for index, spacing in enumerate((2, 3, 4, 2)):
        changed = f.mutate('SetTextSpace', {'theText': h, 'spacing': spacing}, label='spacing_' + str(index))
        f.read('GetTextSpace', {'theText': h}, spacing, label='spacing_read_' + str(index), verifies=[changed])
        f.read('GetTextLeading', {'theText': h}, -1.0, label='no_custom_leading_' + str(index), verifies=[changed])
    return f.jobs


def _style_ref(f, h, position, label, name, verifies):
    key = f.family + '_' + label
    _positive(f, label + '_ref', 'GetTextStyleRefN', {'objectId': h, 'position': position}, key)
    f.read('Index2Name', {'index': capture(key)}, name, label=label + '_resource', verifies=verifies)
    f.read('IsTextStyleByClassN', {'objectId': h, 'position': position}, False, label=label + '_not_by_class')


def _annotation_text_styles(run_id):
    f = _Fixture('annotation_text_styles')
    h = _named_text(f, run_id, 'ABCDEF')
    name = DESIGN.fixture_name('SDK-Annotation-Style-', run_id)
    made = f.create('create_style', call('CreateTextStyleRes', name=name), 'annotation_style')
    f.read('GetName', {'h': capture('annotation_style')}, name, label='style_resource_name', verifies=[made])
    _positive(f, 'style_index', 'Name2Index', {'name': name}, 'annotation_style_index')
    f.read('Index2Name', {'index': capture('annotation_style_index')}, name, label='style_index_identity')
    assigned = f.mutate('SetTextStyleRef', {'objectId': h, 'textStyleRef': capture('annotation_style_index')}, label='assign_style_all')
    _positive(f, 'whole_style_ref', 'GetTextStyleRef', {'objectId': h}, 'whole_style_ref')
    f.read('Index2Name', {'index': capture('whole_style_ref')}, name, label='whole_style_identity', verifies=[assigned])
    f.read('IsTextStyleByClass', {'objectId': h}, False, label='whole_not_by_class', verifies=[assigned])
    for position in (0, 2, 3, 5):
        _style_ref(f, h, position, 'all_char_%d' % position, name, [assigned])
    cleared = f.mutate('SetTextStyleRefN', {'objectId': h, 'start': 2, 'count': 2, 'textStyleRef': 0},
                       label='unstyle_middle', returns=True)
    for position in (2, 3):
        f.read('GetTextStyleRefN', {'objectId': h, 'position': position}, 0,
               label='middle_unstyled_%d' % position, verifies=[cleared])
        f.read('IsTextStyleByClassN', {'objectId': h, 'position': position}, False,
               label='middle_not_by_class_%d' % position, verifies=[cleared])
    for position in (0, 1, 4, 5):
        _style_ref(f, h, position, 'preserved_char_%d' % position, name, [cleared])
    last = f.mutate('SetTextStyleRefN', {'objectId': h, 'start': 5, 'count': 1, 'textStyleRef': 0},
                    label='unstyle_last', returns=True)
    f.read('GetTextStyleRefN', {'objectId': h, 'position': 5}, 0, label='last_unstyled', verifies=[last])
    # Reference.xml explicitly guarantees False for a substring past the end.
    rejected = f.mutate('SetTextStyleRefN', {'objectId': h, 'start': 6, 'count': 1, 'textStyleRef': 0},
                        label='past_end_rejected', returns=False)
    f.read('GetText', {'objectHd': h}, 'ABCDEF', label='rejected_range_preserves_content', verifies=[rejected])
    _style_ref(f, h, 4, 'rejected_range_preserves_style', name, [rejected])
    restored = f.mutate('SetTextStyleRef', {'objectId': h, 'textStyleRef': 0}, label='unstyle_all')
    f.read('GetTextStyleRef', {'objectId': h}, 0, label='whole_unstyled', verifies=[restored])
    for position in range(6):
        f.read('GetTextStyleRefN', {'objectId': h, 'position': position}, 0,
               label='final_unstyled_%d' % position, verifies=[restored])
    return f.jobs


def _annotation_text_replacements(run_id):
    f = _Fixture('annotation_text_replacements')
    h = _named_text(f, run_id, 'Alpha alpha Alpha')
    cases = [
        ('first_only', 'Alpha', 'B', False, True, 'B alpha Alpha'),
        ('case_sensitive', 'Alpha', 'C', True, True, 'B alpha C'),
        ('case_insensitive', 'ALPHA', 'delta', True, False, 'B delta C'),
        ('no_match', 'absent', 'unexpected', True, True, 'B delta C'),
        ('delete_substring', 'delta', '', True, True, 'B  C'),
    ]
    for label, old, new, all_matches, case_sensitive, expected in cases:
        changed = f.mutate('ReplaceText', {'objectHd': h, 'oldText': old, 'newText': new,
                            'replaceAll': all_matches, 'isCaseSens': case_sensitive}, label=label)
        f.read('GetText', {'objectHd': h}, expected, label=label + '_content', verifies=[changed])
        f.read('GetTextLength', {'TextHd': h}, len(expected), label=label + '_length', verifies=[changed])
    # Exact Unicode text is checked here. Its disputed length unit is isolated
    # below so it cannot prevent later replacement edge cases from running.
    scenarios = [
        ('unicode', 'façade 東京 façade', 'façade', 'café', True, 'café 東京 café'),
        ('adjacent', 'aaaa', 'aa', 'x', True, 'xx'),
        ('expanding', 'ab ab', 'ab', 'ab!', True, 'ab! ab!'),
        ('last_character', 'ABZ', 'Z', 'END', False, 'ABEND'),
    ]
    for label, original, old, new, all_matches, expected in scenarios:
        seeded = f.mutate('SetText', {'objectHd': h, 'text': original}, label=label + '_seed')
        f.read('GetText', {'objectHd': h}, original, label=label + '_seed_read', verifies=[seeded])
        changed = f.mutate('ReplaceText', {'objectHd': h, 'oldText': old, 'newText': new,
                            'replaceAll': all_matches, 'isCaseSens': True}, label=label)
        f.read('GetText', {'objectHd': h}, expected, label=label + '_content', verifies=[changed])
        if label != 'unicode':
            f.read('GetTextLength', {'TextHd': h}, len(expected), label=label + '_length', verifies=[changed])
    return f.jobs


def _annotation_unicode_length(run_id):
    f = _Fixture('annotation_unicode_length')
    h = _named_text(f, run_id, 'façade 東京 façade')
    changed = f.mutate('ReplaceText', {'objectHd': h, 'oldText': 'façade', 'newText': 'café',
                        'replaceAll': True, 'isCaseSens': True}, label='unicode')
    f.read('GetText', {'objectHd': h}, 'café 東京 café', label='unicode_content', verifies=[changed])
    # Preserve the original oracle: these BMP characters count as twelve in
    # both Unicode code points and UTF-16 units. Host 882075 returned eighteen,
    # equal to UTF-8 bytes; SDK's "string length" wording does not specify units.
    f.read('GetTextLength', {'TextHd': h}, 12, label='unicode_length', verifies=[changed])
    return f.jobs


def _annotation_text_length_encoding(run_id):
    """Measure native string units without treating a range as semantic proof."""
    f = _Fixture('annotation_text_length_encoding')
    cases = [('ascii', 'ABC'), ('latin_bmp', 'é'), ('ideograph_bmp', '東'),
             ('combining', 'e\u0301'), ('supplementary', 'A😀B'),
             ('long_mixed', 'café 東京 😀 e\u0301 ' * 40)]
    for label, content in cases:
        key = 'encoding_' + label
        made = f.create('create_' + label, [call('CreateText', theText=content), call('LNewObj')], key)
        h = capture(key)
        f.read('GetText', {'objectHd': h}, content, label=label + '_content', verifies=[made])
        name = DESIGN.fixture_name('SDK-Encoding-' + label + '-', run_id)
        f.pair('SetName', {'h': h, 'name': name}, 'GetName', {'h': h}, name, label=label + '_name')
        f.add(label + '_length', native_call=call('GetTextLength', TextHd=h), expected=[0, 32767],
              predicate='range_inclusive', captures=key + '_length')
        f.jobs[-1]['comparison_lengths'] = {'unicode_codepoints': len(content),
                                           'utf16_units': len(content.encode('utf-16-le')) // 2,
                                           'utf8_bytes': len(content.encode('utf-8'))}
    return f.jobs


def _annotation_text_offset_units(run_id):
    f = _Fixture('annotation_text_offset_units')
    h = _named_text(f, run_id, 'A😀B')
    # SDK text buffers use UCChar/UTF-16. Four positions stay within those
    # documented units; never inspect byte positions 4 or 5 from raw length6.
    for label, start, count, style in [('plain', 0, 4, 0), ('bold_a', 0, 1, 1),
                                      ('bold_b_utf16', 3, 1, 1)]:
        changed = f.mutate('SetTextStyle', {'objectHd': h, 'Start': start, 'Count': count, 'Style': style}, label=label)
        f.read('GetText', {'objectHd': h}, 'A😀B', label=label + '_content', verifies=[changed])
        for position in range(4):
            f.add('%s_style_%d' % (label, position), native_call=call('GetTextStyle', TextHd=h, Position=position),
                  expected=[0, 127], predicate='range_inclusive')
    return f.jobs


def _annotation_text_utf16_runs(run_id):
    """Exact UTF-16 run vectors; prior observations remain a separate family."""
    f = _Fixture('annotation_text_utf16_runs')
    h = _named_text(f, run_id, 'A😀B')
    for label, start, count, style, expected in [
            ('plain', 0, 4, 0, [0, 0, 0, 0]),
            ('bold_a', 0, 1, 1, [1, 0, 0, 0]),
            ('bold_b_utf16', 3, 1, 1, [1, 0, 0, 1])]:
        changed = f.mutate('SetTextStyle', {'objectHd': h, 'Start': start, 'Count': count, 'Style': style}, label=label)
        f.read('GetText', {'objectHd': h}, 'A😀B', label=label + '_content', verifies=[changed])
        _text_chars(f, h, label, 'GetTextStyle', expected, [changed])
    return f.jobs


def _annotation_text_utf16_lengths(run_id):
    """Fixed UTF-16 counts, distinct from codepoints, bytes and graphemes."""
    f = _Fixture('annotation_text_utf16_lengths')
    cases = [('empty', '', 0), ('ascii', 'ABC', 3), ('accent', 'é', 1), ('cjk', '東', 1),
             ('combining', 'e\u0301', 2), ('supplementary', 'A😀B', 4),
             ('long_mixed', 'café 東京 😀 e\u0301 ' * 40, 560)]
    for label, content, length in cases:
        # A nonempty seed guarantees a fresh handle even if CreateText('')
        # would not create an object; empty text is an explicit mutation.
        h = _named_text(f, run_id, 'Length sentinel', suffix=label)
        changed = f.mutate('SetText', {'objectHd': h, 'text': content}, label=label + '_set')
        f.read('GetText', {'objectHd': h}, content, label=label + '_content', verifies=[changed])
        f.read('GetTextLength', {'TextHd': h}, length, label=label + '_utf16_length', verifies=[changed])
    return f.jobs


def _annotation_text_style_size_scope(run_id):
    """Calibrated size propagation distinguishes visual formatting from links.

    Selector1361 is a public double on text-style resources. Its effective
    point size is observed on whole-style controls, never inferred from the
    selector's numeric units. This entire family is characterization-only.
    """
    f = _Fixture('annotation_text_style_size_scope')
    for label, first, second, equal in [('equal', 2.0, 2.0, True), ('unequal', 2.0, 4.0, False)]:
        f.read('Eq', {'value1': first, 'value2': second, 'tolerance': 1e-7}, equal, label='compare_' + label)

    def equal_sizes(label, first, second, expected=True, verifies=()):
        f.read('Eq', {'value1': first, 'value2': second, 'tolerance': 1e-7}, expected,
               label=label, verifies=verifies)

    def measure(label, h, position, verifies=()):
        f.add(label, native_call=call('GetTextSize', TextHd=h, Position=position),
              expected=[1e-6, 1e6], predicate='range_inclusive', captures=label, verifies=verifies)
        return capture(label)

    def vector(label, h, expected, verifies=()):
        for position, value in enumerate(expected):
            measured = measure('%s_size_%d' % (label, position), h, position, verifies)
            equal_sizes('%s_matches_%d' % (label, position), measured, value, verifies=verifies)
        f.read('GetText', {'objectHd': h}, 'ABCDEF', label=label + '_content', verifies=verifies)

    resources, refs, names = {}, {}, {}
    for label, raw_size in [('a', 12.0), ('b', 24.0)]:
        name = DESIGN.fixture_name('SDK-Size-Scope-' + label + '-', run_id)
        key = 'size_resource_' + label
        created = f.create('create_' + key, call('CreateTextStyleRes', name=name), key)
        resources[label], names[label] = capture(key), name
        f.read('GetTypeN', {'h': capture(key)}, 109, label=key + '_type', verifies=[created])
        changed = f.mutate('SetObjectVariableReal', {'h': capture(key), 'index': 1361, 'value': raw_size}, label=key + '_set')
        f.add(key + '_raw_size', native_call=call('GetObjectVariableReal', h=capture(key), index=1361),
              expected=[1e-6, 1e6], predicate='range_inclusive', verifies=[changed])
        _positive(f, key + '_index', 'Name2Index', {'name': name}, key + '_index')
        refs[label] = capture(key + '_index')
        f.read('Index2Name', {'index': refs[label]}, name, label=key + '_index_identity')

    objects, initial_sizes = {}, {}
    for label, resource in [('control_a', 'a'), ('control_b', 'b'), ('clear_middle', 'a'), ('replace_middle', 'a')]:
        h = _named_text(f, run_id, 'ABCDEF', suffix=label)
        objects[label] = h
        changed = f.mutate('SetTextStyleRef', {'objectId': h, 'textStyleRef': refs[resource]}, label=label + '_baseline')
        if label.startswith('control_'):
            initial_sizes[resource] = measure(label + '_calibrated_size', h, 0, [changed])
        vector(label + '_baseline', h, [initial_sizes[resource]] * 6, [changed])
        if label == 'control_b':
            equal_sizes('whole_styles_have_distinct_sizes', initial_sizes['a'], initial_sizes['b'], False)

    clear = f.mutate('SetTextStyleRefN', {'objectId': objects['clear_middle'], 'start': 2, 'count': 2, 'textStyleRef': 0},
                     label='clear_middle_edit', returns=True)
    vector('clear_middle_after_edit', objects['clear_middle'], [initial_sizes['a']] * 6, [clear])
    replace = f.mutate('SetTextStyleRefN', {'objectId': objects['replace_middle'], 'start': 2, 'count': 2, 'textStyleRef': refs['b']},
                       label='replace_middle_edit', returns=True)
    vector('replace_middle_after_edit', objects['replace_middle'],
           [initial_sizes['a'], initial_sizes['a'], initial_sizes['b'], initial_sizes['b'], initial_sizes['a'], initial_sizes['a']], [replace])

    current = dict(initial_sizes)
    for resource, raw_size in [('a', 36.0), ('b', 48.0)]:
        changed = f.mutate('SetObjectVariableReal', {'h': resources[resource], 'index': 1361, 'value': raw_size},
                           label='update_' + resource + '_resource')
        f.add('update_' + resource + '_raw_size', native_call=call('GetObjectVariableReal', h=resources[resource], index=1361),
              expected=[1e-6, 1e6], predicate='range_inclusive', verifies=[changed])
        updated = f.mutate('UpdateStyledObjects', {'styleName': names[resource]}, label='propagate_' + resource)
        new_size = measure('updated_' + resource + '_control_size', objects['control_' + resource], 0, [changed, updated])
        equal_sizes('updated_' + resource + '_control_changed', new_size, current[resource], False, [updated])
        equal_sizes('updated_' + resource + '_differs_other', new_size, current['b' if resource == 'a' else 'a'], False, [updated])
        current[resource] = new_size
        for label in ('a', 'b'):
            vector('after_' + resource + '_control_' + label, objects['control_' + label], [current[label]] * 6, [updated])
        vector('after_' + resource + '_clear_middle', objects['clear_middle'],
               [current['a'], current['a'], initial_sizes['a'], initial_sizes['a'], current['a'], current['a']], [updated])
        vector('after_' + resource + '_replace_middle', objects['replace_middle'],
               [current['a'], current['a'], current['b'], current['b'], current['a'], current['a']], [updated])
    return f.jobs


def _annotation_text_style_scope(run_id):
    f = _Fixture('annotation_text_style_scope')
    resources = {}
    for label, font in [('a', 'Arial'), ('b', 'Courier New')]:
        font_key = 'scope_font_' + label
        _positive(f, font_key, 'GetFontID', {'fontName': font}, font_key, 32767)
        f.read('GetFontName', {'fontID': capture(font_key)}, font, label=font_key + '_identity')
        name = DESIGN.fixture_name('SDK-Scope-Style-' + label + '-', run_id)
        resource = 'scope_resource_' + label
        created = f.create('create_' + resource, call('CreateTextStyleRes', name=name), resource)
        h = capture(resource)
        # Exact public SDK selectors: Objs.TDType.h kTextStyleNode=109;
        # ObjectVariables.h ovTextStyleFontID=1370 is a short font ID.
        f.read('GetTypeN', {'h': h}, 109, label=resource + '_type', verifies=[created])
        changed = f.mutate('SetObjectVariableInt', {'h': h, 'index': 1370, 'value': capture(font_key)}, label=resource + '_font')
        _positive(f, resource + '_font_read', 'GetObjectVariableInt', {'h': h, 'index': 1370}, resource + '_font_read', 32767)
        f.read('GetFontName', {'fontID': capture(resource + '_font_read')}, font, label=resource + '_font_identity', verifies=[changed])
        _positive(f, resource + '_index', 'Name2Index', {'name': name}, resource + '_index')
        resources[label] = capture(resource + '_index')
    for label, baseline, target in [('replace_middle', resources['a'], resources['b']),
                                     ('clear_middle', resources['a'], 0), ('assign_middle', 0, resources['b'])]:
        h = _named_text(f, run_id, 'ABCDEF', suffix=label)
        changed = f.mutate('SetTextStyleRef', {'objectId': h, 'textStyleRef': baseline}, label=label + '_baseline')
        f.read('GetText', {'objectHd': h}, 'ABCDEF', label=label + '_baseline_content', verifies=[changed])
        for phase in ('before', 'after'):
            if phase == 'after':
                changed = f.mutate('SetTextStyleRefN', {'objectId': h, 'start': 2, 'count': 2, 'textStyleRef': target},
                                   label=label + '_edit', returns=True)
                f.read('GetText', {'objectHd': h}, 'ABCDEF', label=label + '_content', verifies=[changed])
            for position in range(6):
                prefix = '%s_%s_%d' % (label, phase, position)
                f.add(prefix + '_ref', native_call=call('GetTextStyleRefN', objectId=h, position=position),
                      expected=[0, 2147483647], predicate='range_inclusive')
                _positive(f, prefix + '_font', 'GetTextFont', {'objectHd': h, 'Position': position}, prefix + '_font', 32767)
                f.add(prefix + '_font_name', native_call=call('GetFontName', fontID=capture(prefix + '_font')),
                      expected='ok', path=['status'])
    return f.jobs


def _border_read(f, h, label, row, column, expected, verifies):
    f.read('GetWSCellBorder', _cell(h, row, column), expected, label=label, verifies=verifies)


def _annotation_ws_borders(run_id):
    f = _Fixture('annotation_ws_borders')
    # Border styles 0=None and 2=Solid, weight in mils, color index 0..255
    # are documented by each *BN entry. GetWSCellBorder's order is T,L,B,R.
    # Each case uses a fresh sheet; clearing a larger encompassing range is
    # not assumed to remove a prior, smaller outline. Every sampled cell has
    # an explicit zero baseline before the side/topology mutation.
    for side, expected in [('Top', [True, False, False, False]),
                           ('Left', [False, True, False, False]),
                           ('Bottom', [False, False, True, False]),
                           ('Right', [False, False, False, True])]:
        label = side.lower()
        h, _ = _worksheet(f, run_id, suffix=label)
        _border_read(f, h, label + '_baseline', 3, 3, [False] * 4, [])
        _border_read(f, h, label + '_distant_baseline', 1, 1, [False] * 4, [])
        changed = f.mutate('SetWSCell' + side + 'BN', dict(_range(h, 3, 3, 3, 3),
                           style=2, weight=10, color=0), label=label + '_enable')
        _border_read(f, h, label + '_enabled', 3, 3, expected, [changed])
        _border_read(f, h, label + '_distant_unchanged', 1, 1, [False] * 4, [changed])
        removed = f.mutate('SetWSCell' + side + 'BN', dict(_range(h, 3, 3, 3, 3),
                           style=0, weight=10, color=0), label=label + '_disable')
        _border_read(f, h, label + '_disabled', 3, 3, [False] * 4, [removed])
    for label, setter, checks in [
            ('outline', 'SetWSCellOutlineBN', [
                (2, 2, [True, True, False, False]), (2, 4, [True, False, False, True]),
                (4, 2, [False, True, True, False]), (4, 4, [False, False, True, True]),
                (3, 3, [False, False, False, False])]),
            ('horizontal', 'SetWSCellInsideHzBN', [
                (2, 2, [False, False, True, False]), (3, 3, [True, False, True, False]),
                (4, 4, [True, False, False, False])]),
            ('vertical', 'SetWSCellInsideVtBN', [
                (2, 2, [False, False, False, True]), (3, 3, [False, True, False, True]),
                (4, 4, [False, True, False, False])])]:
        h, _ = _worksheet(f, run_id, suffix=label)
        for row, column, _ in checks:
            _border_read(f, h, '%s_baseline_%d_%d' % (label, row, column), row, column, [False] * 4, [])
        _border_read(f, h, label + '_distant_baseline', 6, 6, [False] * 4, [])
        changed = f.mutate(setter, dict(_range(h, 2, 2, 4, 4), style=2, weight=10, color=0), label=label + '_enable')
        for row, column, expected in checks:
            _border_read(f, h, '%s_%d_%d' % (label, row, column), row, column, expected, [changed])
        _border_read(f, h, label + '_distant_unchanged', 6, 6, [False] * 4, [changed])
    return f.jobs


def _annotation_ws_border_clearing(run_id):
    f = _Fixture('annotation_ws_border_clearing')
    h, _ = _worksheet(f, run_id)
    corners = [(2, 2, [True, True, False, False]), (2, 4, [True, False, False, True]),
               (4, 2, [False, True, True, False]), (4, 4, [False, False, True, True])]
    for row, column, _ in corners:
        _border_read(f, h, 'baseline_%d_%d' % (row, column), row, column, [False] * 4, [])
    outline = f.mutate('SetWSCellOutlineBN', dict(_range(h, 2, 2, 4, 4), style=2, weight=10, color=0), label='outline_enable')
    for row, column, expected in corners:
        _border_read(f, h, 'outline_%d_%d' % (row, column), row, column, expected, [outline])
    cleared = f.mutate('SetWSCellBorders', dict(_range(h, 1, 1, 6, 6), top=False, left=False,
                         bottom=False, right=False, OutlineInside=0), label='horizontal_clear')
    # Preserve the original clearing expectation, but detect retained corners
    # before attributing their presence to SetWSCellInsideHzBN.
    _border_read(f, h, 'horizontal_clear_read', 3, 3, [False] * 4, [cleared])
    for row, column, _ in corners:
        _border_read(f, h, 'cleared_corner_%d_%d' % (row, column), row, column, [False] * 4, [cleared])
    horizontal = f.mutate('SetWSCellInsideHzBN', dict(_range(h, 2, 2, 4, 4), style=2, weight=10, color=0), label='horizontal_enable')
    for row, column, expected in [(2, 2, [False, False, True, False]), (3, 3, [True, False, True, False]),
                                  (4, 4, [True, False, False, False])]:
        _border_read(f, h, 'horizontal_%d_%d' % (row, column), row, column, expected, [horizontal])
    _border_read(f, h, 'horizontal_distant_unchanged', 6, 6, [False] * 4, [horizontal])
    return f.jobs


def _annotation_ws_border_scope(run_id):
    """Discriminate legacy block edges and verify explicit style-zero removal."""
    f = _Fixture('annotation_ws_border_scope')
    corners = [(2, 2, [True, True, False, False]), (2, 4, [True, False, False, True]),
               (4, 2, [False, True, True, False]), (4, 4, [False, False, True, True])]
    for label, clear_range in [('same_range', (2, 2, 4, 4)), ('enclosing_range', (1, 1, 6, 6))]:
        h, _ = _worksheet(f, run_id, suffix=label)
        sentinel = 'Preserve café 東京 ' + label
        seeded = f.mutate('SetWSCellFormulaN', dict(_range(h, 3, 3, 3, 3), formula=sentinel), label=label + '_seed')
        f.read('GetWSCellFormulaN', _cell(h, 3, 3), sentinel, label=label + '_seed_read', verifies=[seeded])
        for row, column, _ in corners:
            _border_read(f, h, '%s_baseline_%d_%d' % (label, row, column), row, column, [False] * 4, [])
        outline = f.mutate('SetWSCellOutlineBN', dict(_range(h, 2, 2, 4, 4), style=2, weight=10, color=0),
                           label=label + '_outline')
        for row, column, expected in corners:
            _border_read(f, h, '%s_outline_%d_%d' % (label, row, column), row, column, expected, [outline])
        cleared = f.mutate('SetWSCellBorders', dict(_range(h, *clear_range), top=False, left=False,
                           bottom=False, right=False, OutlineInside=0), label=label + '_legacy_clear')
        for row, column, _ in corners:
            f.read('GetWSCellBorder', _cell(h, row, column), 'ok', path=['status'],
                   label='%s_legacy_result_%d_%d' % (label, row, column), verifies=[cleared])
        # Explicit style0=None is documented for all three *BN calls. Clearing
        # the entire edge topology must preserve values, unlike ClearWSCell.
        removed = []
        for mode in ('Outline', 'InsideHz', 'InsideVt'):
            removed.append(f.mutate('SetWSCell' + mode + 'BN', dict(_range(h, 1, 1, 6, 6),
                                     style=0, weight=10, color=0), label=label + '_remove_' + mode))
        for row, column, _ in corners:
            _border_read(f, h, '%s_explicit_clear_%d_%d' % (label, row, column), row, column, [False] * 4, removed)
        f.read('GetWSCellFormulaN', _cell(h, 3, 3), sentinel, label=label + '_content_preserved', verifies=removed)
    return f.jobs


def _annotation_ws_images(run_id):
    f = _Fixture('annotation_ws_images')
    h, name = _worksheet(f, run_id, rows=3, columns=3)
    value = 'façade 東京 ' + 'abcdefghij' * 30
    seeded = f.mutate('SetWSCellFormulaN', dict(_range(h, 1, 1, 1, 1), formula=value), label='seed_long_string')
    f.read('GetWSCellFormulaN', _cell(h, 1, 1), value, label='long_formula', verifies=[seeded])
    recalculated = f.mutate('RecalculateWS', {'worksheet': h}, label='calculate_sheet')
    f.read('GetWSCellStringN', _cell(h, 1, 1), value, label='long_display_string', verifies=[seeded, recalculated])
    for dpi in (72, 150, 300):
        f.pair('SetWSCellsImgDPIRes', {'worksheet': h, 'dpiResolution': dpi},
               'GetWSCellsImgDPIRes', {'worksheet': h}, dpi, label='dpi_%d' % dpi)
    made = f.create('create_image', call('CreateWSImage', worksheet=h, location=[1000.0, -1000.0]), 'annotation_ws_image')
    image = capture('annotation_ws_image')
    image_name = DESIGN.fixture_name('SDK-Annotation-Image-', run_id)
    f.pair('SetName', {'h': image, 'name': image_name}, 'GetName', {'h': image}, image_name, label='name_image')
    f.create('source_from_image', call('GetWSFromImage', worksheetImage=image), 'annotation_image_source')
    f.read('GetName', {'h': capture('annotation_image_source')}, name, label='image_source_identity', verifies=[made])
    f.create('image_from_source', call('GetWSImage', worksheet=h), 'annotation_image_again')
    f.read('GetName', {'h': capture('annotation_image_again')}, image_name, label='source_image_identity', verifies=[made])
    for scale in (0.5, 2.0, 1.0):
        label = 'scale_' + str(scale).replace('.', '_')
        changed = f.mutate('SetWSImageScaleF', {'handle': image, 'scaleFactor': scale, 'redraw': False}, label=label)
        f.read('GetWSImageScaleF', {'handle': image}, scale, label=label + '_read', verifies=[changed])
        f.read('GetWSCellStringN', _cell(h, 1, 1), value, label=label + '_preserves_source', verifies=[changed])
    for index, show in enumerate((False, True, False)):
        f.pair('SetWSImgShowDBHeader', {'hWorksheetImage': image, 'show': show, 'redrawImage': False},
               'GetWSImgShowDBHeader', {'hWorksheetImage': image}, show, label='header_%d' % index)
    f.read('GetWSRowColumnCount', {'worksheet': h}, [3, 3], label='image_preserves_dimensions')
    f.read('GetWSCellsImgDPIRes', {'worksheet': h}, 300, label='image_preserves_dpi')
    return f.jobs


def annotation_fixtures(run_id, families=None):
    """Build selected self-contained families without contacting Vectorworks."""
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id):
        raise ValueError('Invalid run_id')
    if families is not None and not isinstance(families, (list, tuple)):
        raise ValueError('Select a list or tuple of known fixture families')
    selected = list(FAMILIES if families is None else families)
    if not selected or any(not isinstance(x, str) or x not in FAMILIES for x in selected) or len(set(selected)) != len(selected):
        raise ValueError('Select unique known fixture families')
    jobs = [job for family in selected for job in globals()['_' + family](run_id)]
    for job in jobs:
        job['evidence_basis'] = ('SDK 3200 vs.py, VectorScript Reference.xml, APIBase.Legacy.Defs.h; '
                                 'literal character runs and strings, named resource identity, worksheet edge topology')
        job['prerequisites'].append('Only fresh fixture-owned text, worksheets, images and text-style resources are modified')
        if job['fixture_family'] == 'annotation_text_runs':
            job['prerequisites'].append('Arial and Courier New installed under these exact names; positive IDs checked before use')
        if job['fixture_family'].startswith('annotation_text_'):
            job['prerequisites'].append('Substring offsets are zero-based; sizes and leading are in points, independent of drawing units')
        if job['fixture_family'] in ('annotation_ws_borders', 'annotation_ws_border_clearing', 'annotation_ws_border_scope'):
            job['prerequisites'].append('Border style 2=solid, 0=none; weight=10 mils; documented palette index 0; no dash resources')
        if job['fixture_family'] in DIAGNOSTIC_FAMILIES:
            job['diagnostic_only'] = True
            job['prerequisites'].append('Explicit diagnostic selection: preserve SDK contract despite observed build 882075 discrepancy')
        if job['fixture_family'] == 'annotation_unicode_length':
            job['known_issue'] = ('GetText returned the exact replacement text café 東京 café, while GetTextLength returned 18 '
                                  'instead of 12 code points/UTF-16 units, matching UTF-8 bytes. The original length oracle is '
                                  'preserved pending clarification of SDK string-length units')
        if job['fixture_family'] in CHARACTERIZATION_FAMILIES:
            job['verification_dimension'] = 'characterization'
            job['evidence_basis'] = ('SDK 3200 text and worksheet contracts, public text-style resource selector1370 and UCChar buffers; '
                                     'observational ranges validate response shape only, not native semantic success')
            job['prerequisites'].append('Keep characterization results separate from semantic native pass coverage')
    return jobs
