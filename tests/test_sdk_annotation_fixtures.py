"""Independent annotation models exercise real adapters and bad-native outcomes."""
import copy
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ANNOTATION = load('sdk_annotation_test_fixtures', ROOT / 'tools/sdk_annotation_fixtures.py')
HOST = ANNOTATION.DESIGN.HOST
RUNTIME = HOST._load_runtime(ROOT)
RUNNER = load('sdk_annotation_typed_runner', ROOT / 'tools/sdk_design_runner.py')
POLICY = load('sdk_annotation_background', ROOT / 'mcp-server/background_policy.py')
CATALOG = json.loads((ROOT / 'vwx-plugin/sdk_catalog.json').read_text(encoding='utf-8'))
INDEX = json.loads((ROOT / 'vwx-plugin/vs_index.json').read_text(encoding='utf-8'))
with patch.dict(sys.modules, {'sdk_runtime': RUNTIME}):
    SEQUENCES = load('sdk_annotation_sequences', ROOT / 'vwx-plugin/sdk_sequences.py')


class _Objects:
    def __init__(self, fault=None):
        self.by_uuid, self.last, self.fault = {}, None, fault

    def _new(self, kind, **values):
        key = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'annotation-model-%d' % len(self.by_uuid)))
        h = SimpleNamespace(kind=kind, uuid=key, name='', **values)
        self.by_uuid[key] = h
        return h

    def GetVersion(self):
        return 32, 0, 0, 2

    def GetObjectUuid(self, h):
        return h.uuid

    def GetObjectByUuid(self, key):
        return self.by_uuid.get(key)

    def GetTypeN(self, h):
        return h.kind if h is not None else 0

    def LNewObj(self):
        return self.last

    def SetName(self, h, name):
        h.name = name[:63]

    def GetName(self, h):
        return h.name


class _TextModel(_Objects):
    """A character array model; it has no access to fixture assertion vectors."""
    def __init__(self, fault=None, size_scale=2.5):
        super().__init__(fault)
        self.fonts = {17: 'Arial', 91: 'Courier New'}
        self.resources = {}
        self.size_scale = size_scale

    def CreateText(self, theText):
        self.last = self._new(10, text='', characters=[], spacing=2, leading=None,
                              justification=1, vertical=1)
        self.SetText(self.last, theText)

    def GetText(self, objectHd):
        return objectHd.text

    def SetText(self, objectHd, text):
        objectHd.text = text
        objectHd.characters = [dict(font=17, size=12.0, face=0, style=0, by_class=False)
                               for _ in range(len(text.encode('utf-16-le')) // 2)]

    def GetTextLength(self, TextHd):
        if self.fault == 'utf8_text_length':
            return len(TextHd.text.encode('utf-8'))
        if self.fault == 'codepoint_text_length':
            return len(TextHd.text)
        return len(TextHd.characters)

    def _range(self, h, start, count):
        return h.characters[start:start + count]

    def GetFontListSize(self):
        return len(self.fonts)

    def GetFontID(self, fontName):
        return next((key for key, value in self.fonts.items() if value == fontName), 0)

    def GetFontName(self, fontID):
        return self.fonts[fontID]

    def SetTextFont(self, objectHd, Start, Count, FontNum):
        if self.fault == 'font_noop' and Start:
            return
        if self.fault == 'font_off_by_one' and Start:
            Start -= 1
        for character in self._range(objectHd, Start, Count):
            character['font'] = FontNum

    def GetTextFont(self, objectHd, Position):
        return objectHd.characters[Position]['font']

    def SetTextSize(self, objectHd, Start, Count, Size):
        for character in self._range(objectHd, Start, Count):
            character['size'] = Size

    def GetTextSize(self, TextHd, Position):
        return TextHd.characters[Position]['size']

    def SetTextStyle(self, objectHd, Start, Count, Style):
        if self.fault == 'utf16_last_noop' and Start == 3:
            return
        characters = objectHd.characters if self.fault == 'style_leaks' else self._range(objectHd, Start, Count)
        for character in characters:
            character['face'] = Style
            if self.fault == 'style_changes_size' and Style:
                character['size'] = 13.0

    def GetTextStyle(self, TextHd, Position):
        return TextHd.characters[Position]['face']

    def SetTextSpace(self, theText, spacing):
        theText.spacing, theText.leading = spacing, None

    def GetTextSpace(self, theText):
        return theText.spacing

    def SetTextLeading(self, theText, leading):
        theText.leading = leading
        if self.fault != 'custom_spacing_missing':
            theText.spacing = 0

    def GetTextLeading(self, theText):
        if self.fault == 'zero_leading_sentinel' and theText.spacing != 0:
            return 0.0
        return theText.leading if theText.spacing == 0 else -1.0

    def SetTextJustN(self, TextHd, JustFlag):
        TextHd.justification = JustFlag

    def GetTextJust(self, TextHd):
        return TextHd.justification

    def SetTextVertAlignN(self, TextHd, verticalAlignment):
        TextHd.vertical = verticalAlignment

    def GetTextVerticalAlign(self, TextHd):
        return TextHd.vertical

    def CreateTextStyleRes(self, name):
        h = self._new(109, font=17, size=12.0)
        h.name = name[:63]
        self.resources[1000 + len(self.resources)] = h
        return h

    def Name2Index(self, name):
        return next(key for key, value in self.resources.items() if value.name == name)

    def Index2Name(self, index):
        return self.resources[index].name

    def SetTextStyleRef(self, objectId, textStyleRef):
        for character in objectId.characters:
            character.update(style=textStyleRef, by_class=False)
            if textStyleRef:
                character['font'] = self.resources[textStyleRef].font
                character['size'] = self.resources[textStyleRef].size * self.size_scale

    def GetTextStyleRef(self, objectId):
        return objectId.characters[0]['style']

    def SetTextStyleRefN(self, objectId, start, count, textStyleRef):
        if start < 0 or start + count > len(objectId.characters):
            return self.fault == 'accept_past_end'
        if self.fault == 'partial_style_noop':
            return True
        leaking = self.fault == 'unstyle_leaks' or (self.fault == 'clear_loses_outer_links' and textStyleRef == 0)
        characters = objectId.characters if leaking else self._range(objectId, start, count)
        for character in characters:
            character.update(style=textStyleRef, by_class=False)
            if textStyleRef:
                character['font'] = self.resources[textStyleRef].font
                character['size'] = self.resources[textStyleRef].size * self.size_scale
        return True

    def GetTextStyleRefN(self, objectId, position):
        if self.fault == 'global_ref_only' and len({c['style'] for c in objectId.characters}) > 1:
            return 0
        return objectId.characters[position]['style']

    def SetObjectVariableInt(self, h, index, value):
        assert h.kind == 109 and index == 1370 and value in self.fonts
        h.font = value

    def GetObjectVariableInt(self, h, index):
        assert h.kind == 109 and index == 1370
        return h.font

    def SetObjectVariableReal(self, h, index, value):
        assert h.kind == 109 and index == 1361
        if self.fault != 'resource_size_noop':
            h.size = value

    def GetObjectVariableReal(self, h, index):
        assert h.kind == 109 and index == 1361
        return h.size

    def Eq(self, value1, value2, tolerance):
        if self.fault == 'eq_always_true':
            return True
        if self.fault == 'eq_always_false':
            return False
        return abs(value1 - value2) <= tolerance

    def UpdateStyledObjects(self, styleName):
        resource = next(r for r in self.resources.values() if r.name == styleName)
        index = next(i for i, r in self.resources.items() if r is resource)
        if self.fault == 'propagation_noop':
            return
        for h in self.by_uuid.values():
            if h.kind != 10:
                continue
            for character in h.characters:
                linked = character['style'] == index
                linked |= self.fault == 'propagation_cross_resource' and bool(character['style'])
                linked |= self.fault == 'propagation_touches_unstyled' and character['style'] == 0
                if linked:
                    character['size'] = resource.size * self.size_scale

    def IsTextStyleByClass(self, objectId):
        return any(character['by_class'] for character in objectId.characters)

    def IsTextStyleByClassN(self, objectId, position):
        return objectId.characters[position]['by_class']

    def ReplaceText(self, objectHd, oldText, newText, replaceAll, isCaseSens):
        if self.fault == 'replace_always_all':
            replaceAll = True
        if self.fault == 'replace_always_sensitive':
            isCaseSens = True
        value = re.sub(re.escape(oldText), lambda _: newText, objectHd.text,
                       count=0 if replaceAll else 1, flags=0 if isCaseSens else re.IGNORECASE)
        self.SetText(objectHd, value)


class _WorksheetModel(_Objects):
    """Borders live on shared grid edges, independently of T/L/B/R oracles."""
    def CreateWS(self, name, rows, columns):
        h = self._new(18, rows=rows, columns=columns, edges=set(), cells={}, dpi=72, image=None)
        h.name = name[:63]
        return h

    def GetWSRowColumnCount(self, worksheet):
        return worksheet.rows, worksheet.columns

    def SetWSCellFormulaN(self, worksheet, topRow, leftColumn, bottomRow, rightColumn, formula):
        for row in range(topRow, bottomRow + 1):
            for column in range(leftColumn, rightColumn + 1):
                worksheet.cells[row, column] = formula

    def GetWSCellFormulaN(self, worksheet, row, column):
        return worksheet.cells.get((row, column), '')

    def RecalculateWS(self, worksheet):
        pass  # This model handles only literal-string cells, without formulas.

    def GetWSCellStringN(self, worksheet, row, column):
        result = worksheet.cells.get((row, column), '')
        return result[:255] if self.fault == 'truncate_strings' else result

    def SetWSCellsImgDPIRes(self, worksheet, dpiResolution):
        worksheet.dpi = dpiResolution

    def GetWSCellsImgDPIRes(self, worksheet):
        return worksheet.dpi

    def CreateWSImage(self, worksheet, location):
        h = self._new(56, source=worksheet, location=location, scale=1.0, header=True)
        worksheet.image = h
        return h

    def GetWSFromImage(self, worksheetImage):
        if self.fault == 'wrong_image_source':
            return self.CreateWS('Wrong independent worksheet', 3, 3)
        return worksheetImage.source

    def GetWSImage(self, worksheet):
        return worksheet.image

    def SetWSImageScaleF(self, handle, scaleFactor, redraw):
        if self.fault != 'image_scale_noop':
            handle.scale = scaleFactor
        if self.fault == 'image_corrupts_source':
            handle.source.cells[1, 1] = 'Corrupted by image scaling'

    def GetWSImageScaleF(self, handle):
        return handle.scale

    def SetWSImgShowDBHeader(self, hWorksheetImage, show, redrawImage):
        hWorksheetImage.header = show

    def GetWSImgShowDBHeader(self, hWorksheetImage):
        return hWorksheetImage.header

    def _edges(self, mode, top, left, bottom, right):
        if self.fault == 'transpose_border':
            mode = {'top': 'left', 'left': 'top', 'bottom': 'right', 'right': 'bottom'}.get(mode, mode)
        horizontal = {'top': [top - 1], 'bottom': [bottom],
                      'horizontal': range(top, bottom), 'outline': [top - 1, bottom]}.get(mode, [])
        vertical = {'left': [left - 1], 'right': [right],
                    'vertical': range(left, right), 'outline': [left - 1, right]}.get(mode, [])
        edges = {('h', boundary, col) for boundary in horizontal for col in range(left, right + 1)}
        edges |= {('v', row, boundary) for boundary in vertical for row in range(top, bottom + 1)}
        return edges

    def _set_edges(self, h, mode, top, left, bottom, right, style):
        edges = self._edges(mode, top, left, bottom, right)
        if style:
            h.edges.update(edges)
        elif self.fault != 'border_disable_noop':
            h.edges.difference_update(edges)

    def SetWSCellBorders(self, worksheet, topRow, leftColumn, bottomRow, rightColumn, top, left, bottom, right, OutlineInside):
        for mode, enabled in [('top', top), ('left', left), ('bottom', bottom), ('right', right),
                              ('outline', bool(OutlineInside & 1)), ('horizontal', bool(OutlineInside & 2)),
                              ('vertical', bool(OutlineInside & 4))]:
            if self.fault == 'legacy_clear_noop' and not enabled:
                continue
            self._set_edges(worksheet, mode, topRow, leftColumn, bottomRow, rightColumn, int(enabled))

    def GetWSCellBorder(self, worksheet, row, column):
        edges = [('h', row - 1, column), ('v', row, column - 1), ('h', row, column), ('v', row, column)]
        return tuple(edge in worksheet.edges for edge in edges)


def _border_setter(mode):
    def setter(self, worksheet, topRow, leftColumn, bottomRow, rightColumn, style, weight, color):
        self._set_edges(worksheet, mode, topRow, leftColumn, bottomRow, rightColumn, style)
    return setter


for _suffix, _mode in [('Top', 'top'), ('Left', 'left'), ('Bottom', 'bottom'), ('Right', 'right'),
                        ('Outline', 'outline'), ('InsideHz', 'horizontal'), ('InsideVt', 'vertical')]:
    setattr(_WorksheetModel, 'SetWSCell' + _suffix + 'BN', _border_setter(_mode))


def run_model(jobs, model):
    captures, results = {}, []
    for job in jobs:
        request = RUNNER.render_typed_job(job, captures)
        params = request['params']
        if request['command'] == 'sdk_sequence':
            response = SEQUENCES.run(params, vs_module=model, catalog=CATALOG)
        else:
            response = RUNTIME.invoke(params['name'], {'arguments': params['arguments']}, vs_module=model, catalog=CATALOG)
        passed, assertions = HOST.evaluate_native(job, response)
        results.append((job['id'], passed, response, assertions))
        if not passed:
            break
        if 'capture' in job:
            captures[job['capture']['name']] = HOST._at(response, job['capture']['path'])
    return results


def fake_capture(job):
    assertion = next(a for a in job['assertions'] if a['path'] == job['capture']['path'])
    return HOST.FIXTURE_UUID if assertion.get('valid_uuid') else assertion['range_inclusive'][0]


class SDKAnnotationFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jobs = ANNOTATION.annotation_fixtures('offline')

    def test_every_call_matches_index_runtime_and_background_policy(self):
        captures = {}
        for job in self.jobs:
            self.assertEqual(job['native_status'], 'pending_not_executed')
            for c in job.get('calls', [job]):
                name = c['name']
                self.assertEqual(set(c['arguments']), set(INDEX[name]['args']), job['id'])
                validated = RUNTIME.validate(name, {'arguments': HOST._substitute(c['arguments'], captures)},
                    catalog=CATALOG, invocation_context={'sequence': True})
                self.assertNotIn('error', validated, (job['id'], validated))
                for flag in ('interactive', 'quarantined', 'unsupported_reason', 'deprecated'):
                    self.assertFalse(CATALOG['functions'][name]['context'][flag], (name, flag))
            rendered = RUNNER.render_typed_job(job, captures)
            self.assertIn(rendered['command'], ('sdk_call', 'sdk_sequence'))
            self.assertIsNone(POLICY.check(rendered['command'], rendered['params'], sdk_catalog=CATALOG['functions']))
            if 'capture' in job:
                self.assertNotIn(job['capture']['name'], captures)
                captures[job['capture']['name']] = fake_capture(job)

    def test_families_are_independent_and_selection_is_strict(self):
        for family in ANNOTATION.FAMILIES:
            captures = {}
            for job in ANNOTATION.annotation_fixtures('independent', [family]):
                self.assertEqual(job['fixture_family'], family)
                HOST._substitute(job.get('calls', job.get('arguments')), captures)
                if 'capture' in job:
                    captures[job['capture']['name']] = fake_capture(job)
        for bad in ('', None, 5, '../run', 'a b', 'x' * 81):
            with self.assertRaises(ValueError):
                ANNOTATION.annotation_fixtures(bad)
        for bad in ([], ['unknown'], [None], 'annotation_text_runs', [['x']], ['annotation_text_runs'] * 2):
            with self.assertRaises(ValueError):
                ANNOTATION.annotation_fixtures('valid', bad)

    def test_all_mutations_have_later_semantic_readbacks(self):
        positions = {j['id']: i for i, j in enumerate(self.jobs)}
        self.assertEqual(len(positions), len(self.jobs))
        verified = set()
        for job in self.jobs:
            for original in job.get('verifies_jobs', []):
                self.assertLess(positions[original], positions[job['id']])
                self.assertEqual(job['phase'], 'readback')
                verified.add(original)
        self.assertEqual({j['id'] for j in self.jobs if j['phase'] == 'mutation'} - verified, set())

    def test_only_fresh_handles_and_no_global_state_or_selection(self):
        forbidden = {'TextFont', 'TextSize', 'TextFace', 'TextJust', 'TextOrigin', 'TextSpace',
                     'TextLeading', 'TextVerticalAlign', 'SetSelect', 'SetDSelect', 'SelectAll',
                     'DSelectAll', 'Layer', 'NameClass', 'ShowWS', 'SetWSSelection', 'SetWSPlacement',
                     'SetPref', 'SetPrefInt', 'SetObjectVariableInt', 'SetObjectVariableReal',
                     'DoMenuTextByName', 'RunScript', 'GetObject'}
        created_styles = {c['arguments']['name'] for j in self.jobs for c in j.get('calls', [j])
                          if c['name'] == 'CreateTextStyleRes'}
        for job in self.jobs:
            for c in job.get('calls', [job]):
                if job['fixture_family'] == 'annotation_text_style_scope' and c['name'] == 'SetObjectVariableInt':
                    self.assertEqual(c['arguments']['index'], 1370)
                    self.assertTrue(c['arguments']['h']['$capture'].startswith('scope_resource_'))
                elif job['fixture_family'] == 'annotation_text_style_size_scope' and c['name'] == 'SetObjectVariableReal':
                    self.assertEqual(c['arguments']['index'], 1361)
                    self.assertTrue(c['arguments']['h']['$capture'].startswith('size_resource_'))
                else:
                    self.assertNotIn(c['name'], forbidden)
                if c['name'] == 'UpdateStyledObjects':
                    self.assertIn(c['arguments']['styleName'], created_styles)
                self.assertNotIn('options', c)
                for p in CATALOG['functions'][c['name']]['parameters']:
                    if p['type'] == 'HANDLE':
                        self.assertEqual(set(c['arguments'][p['name']]), {'$capture'})
        jobs2 = ANNOTATION.annotation_fixtures('second')
        first_names = {c['arguments']['name'] for j in self.jobs for c in j.get('calls', [j])
                       if c['name'] in ('SetName', 'CreateWS', 'CreateTextStyleRes')}
        second_names = {c['arguments']['name'] for j in jobs2 for c in j.get('calls', [j])
                        if c['name'] in ('SetName', 'CreateWS', 'CreateTextStyleRes')}
        self.assertTrue(first_names.isdisjoint(second_names))

    def test_builds_do_not_share_mutable_plans(self):
        original = copy.deepcopy(self.jobs)
        changed = ANNOTATION.annotation_fixtures('offline')
        changed[0]['calls'][0]['arguments']['theText'] = 'corrupted'
        changed[1]['assertions'][0]['equals'] = 'corrupted'
        self.assertEqual(self.jobs, original)

    def test_all_text_families_pass_independent_character_model(self):
        for family in (name for name in ANNOTATION.FAMILIES if not name.startswith('annotation_ws_')):
            with self.subTest(family=family):
                jobs = ANNOTATION.annotation_fixtures('textmodel', [family])
                results = run_model(jobs, _TextModel())
                self.assertEqual(len(results), len(jobs), results[-1])
                self.assertTrue(all(r[1] for r in results), results[-1])

    def test_all_worksheet_families_pass_independent_model(self):
        for family in (name for name in ANNOTATION.FAMILIES if name.startswith('annotation_ws_')):
            with self.subTest(family=family):
                jobs = ANNOTATION.annotation_fixtures('wsmodel', [family])
                results = run_model(jobs, _WorksheetModel())
                self.assertEqual(len(results), len(jobs), results[-1])
                self.assertTrue(all(r[1] for r in results), results[-1])

    def test_long_run_ids_keep_names_bounded_unique_and_exact_under_native_name_limit(self):
        name_apis = {'SetName', 'CreateWS', 'CreateTextStyleRes'}
        names = []
        for run_id in ('x' * 79 + 'a', 'x' * 79 + 'b'):
            jobs = ANNOTATION.annotation_fixtures(run_id)
            created = [c['arguments']['name'] for j in jobs for c in j.get('calls', [j]) if c['name'] in name_apis]
            self.assertEqual(len(created), len(set(created)))
            self.assertTrue(all(name.isascii() and len(name) <= 60 for name in created))
            names.append(set(created))
        self.assertTrue(names[0].isdisjoint(names[1]))
        for family in ANNOTATION.FAMILIES:
            model = _WorksheetModel() if family.startswith('annotation_ws_') else _TextModel()
            results = run_model(ANNOTATION.annotation_fixtures('x' * 80, [family]), model)
            self.assertTrue(all(r[1] for r in results), results[-1])

    def test_documented_disputes_are_explicit_independent_diagnostics(self):
        expected = {'annotation_text_leading_sentinel', 'annotation_text_styles', 'annotation_ws_border_clearing',
                    'annotation_unicode_length', 'annotation_text_length_encoding',
                    'annotation_text_style_scope', 'annotation_text_offset_units', 'annotation_ws_border_scope',
                    'annotation_text_style_size_scope'}
        self.assertEqual(set(ANNOTATION.DIAGNOSTIC_FAMILIES), expected)
        for job in self.jobs:
            self.assertEqual(job.get('diagnostic_only', False), job['fixture_family'] in expected)
        routine = ANNOTATION.annotation_fixtures('routine', ['annotation_text_layout'])
        self.assertFalse(any(j.get('name') == 'GetTextLeading' and j['assertions'][0].get('equals') == -1 for j in routine))
        # The raw 0.0 still fails the documented oracle. A repaired adapter can
        # pass only with its disclosed compatibility metadata retaining raw0.
        diagnostic = ANNOTATION.annotation_fixtures('sentinel', ['annotation_text_leading_sentinel'])
        read = next(j for j in diagnostic if j.get('name') == 'GetTextLeading')
        self.assertFalse(HOST.evaluate_native(read, {'status': 'ok', 'function': 'GetTextLeading', 'result': 0.0})[0])
        repaired = run_model(diagnostic, _TextModel('zero_leading_sentinel'))
        self.assertTrue(all(r[1] for r in repaired), repaired[-1])
        for _, _, response, _ in repaired:
            if response.get('function') == 'GetTextLeading':
                self.assertEqual(response['compatibility']['native_result'], 0.0)
        results = run_model(routine, _TextModel('zero_leading_sentinel'))
        self.assertTrue(all(r[1] for r in results), results[-1])

    def test_each_border_case_owns_a_fresh_sheet_and_checks_all_sampled_baselines(self):
        jobs = ANNOTATION.annotation_fixtures('fresh', ['annotation_ws_borders'])
        sheets = [j for j in jobs if j.get('name') == 'CreateWS']
        self.assertEqual(len(sheets), 7)
        self.assertEqual(len({j['capture']['name'] for j in sheets}), 7)
        self.assertFalse(any(j.get('name') == 'SetWSCellBorders' for j in jobs))
        for case in ('top', 'left', 'bottom', 'right', 'outline', 'horizontal', 'vertical'):
            before, after = set(), set()
            enable = next(i for i, j in enumerate(jobs) if j['id'].endswith(':' + case + '_enable'))
            handle = jobs[enable]['arguments']['worksheet']
            for index, job in enumerate(jobs):
                if job.get('name') == 'GetWSCellBorder' and job['arguments']['worksheet'] == handle:
                    cell = job['arguments']['row'], job['arguments']['column']
                    (before if index < enable else after).add(cell)
            self.assertTrue(after <= before, case)
        model = _WorksheetModel('legacy_clear_noop')
        results = run_model(jobs, model)
        self.assertTrue(all(r[1] for r in results), results[-1])
        self.assertEqual(len(model.by_uuid), 7)

    def test_disputed_border_clearing_cannot_be_misattributed_to_next_setter(self):
        results = self._fault('annotation_ws_border_clearing', _WorksheetModel('legacy_clear_noop'), 'cleared_corner_2_2')
        self.assertFalse(any(r[0].endswith(':horizontal_enable') for r in results))
        jobs = ANNOTATION.annotation_fixtures('preserved', ['annotation_ws_border_clearing'])
        original_oracle = next(j for j in jobs if j['id'].endswith(':horizontal_2_2'))
        self.assertEqual(original_oracle['assertions'][0]['equals'], [False, False, True, False])

    def _fault(self, family, model, expected_label):
        results = run_model(ANNOTATION.annotation_fixtures('fault', [family]), model)
        self.assertFalse(results[-1][1], results[-1])
        self.assertEqual(results[-1][0], 'design:' + family + ':' + expected_label, results[-1])
        self.assertTrue(all(r[1] for r in results[:-1]))
        return results

    def test_font_noop_is_detected_after_void_setter_success(self):
        results = self._fault('annotation_text_runs', _TextModel('font_noop'), 'courier_middle_font_name_2')
        self.assertTrue(any(r[0].endswith(':courier_middle') and r[1] for r in results))

    def test_off_by_one_font_edit_is_detected_on_preserved_neighbor(self):
        self._fault('annotation_text_runs', _TextModel('font_off_by_one'), 'courier_middle_font_name_1')

    def test_style_leaking_outside_substring_is_detected(self):
        self._fault('annotation_text_runs', _TextModel('style_leaks'), 'bold_first_char_1')

    def test_style_edit_cannot_silently_change_point_sizes(self):
        self._fault('annotation_text_runs', _TextModel('style_changes_size'), 'styles_preserve_sizes_char_0')

    def test_custom_leading_requires_custom_spacing_mode(self):
        self._fault('annotation_text_layout', _TextModel('custom_spacing_missing'), 'leading_12_0_read')

    def test_partial_unstyle_preserves_neighbor_resource_links(self):
        self._fault('annotation_text_styles', _TextModel('unstyle_leaks'), 'preserved_char_0_ref')

    def test_documented_past_end_failure_is_not_accepted_as_success(self):
        self._fault('annotation_text_styles', _TextModel('accept_past_end'), 'past_end_rejected')

    def test_replace_first_and_case_sensitivity_are_independent_oracles(self):
        for fault, label in [('replace_always_all', 'first_only_content'),
                             ('replace_always_sensitive', 'case_insensitive_content')]:
            with self.subTest(fault=fault):
                self._fault('annotation_text_replacements', _TextModel(fault), label)

    def test_unicode_byte_length_is_preserved_as_failure_in_independent_diagnostic(self):
        results = self._fault('annotation_unicode_length', _TextModel('utf8_text_length'), 'unicode_length')
        self.assertEqual(results[-1][2]['result'], 18)
        self.assertEqual(results[-1][3][0]['expected']['equals'], 12)
        self.assertTrue(any(r[0].endswith(':unicode_content') and r[1] for r in results))

    def test_length_characterization_discriminates_codepoints_utf16_and_utf8_without_false_semantic_credit(self):
        jobs = ANNOTATION.annotation_fixtures('encoding', ['annotation_text_length_encoding'])
        self.assertTrue(all(j.get('verification_dimension') == 'characterization' for j in jobs))
        reads = [j for j in jobs if j.get('name') == 'GetTextLength']
        self.assertEqual(len(reads), 6)
        supplementary = next(j for j in reads if j['id'].endswith(':supplementary_length'))
        self.assertEqual(supplementary['comparison_lengths'], {'unicode_codepoints': 3, 'utf16_units': 4, 'utf8_bytes': 6})
        combining = next(j for j in reads if j['id'].endswith(':combining_length'))
        self.assertEqual(combining['comparison_lengths'], {'unicode_codepoints': 2, 'utf16_units': 2, 'utf8_bytes': 3})
        for model in (_TextModel(), _TextModel('utf8_text_length')):
            results = run_model(jobs, model)
            self.assertEqual(len(results), len(jobs))
            self.assertTrue(all(r[1] for r in results), results[-1])
            for job in reads:
                self.assertEqual(set(job['assertions'][0]), {'path', 'range_inclusive'})

    def test_style_scope_probe_distinguishes_global_getter_from_leaking_setter(self):
        jobs = ANNOTATION.annotation_fixtures('scope', ['annotation_text_style_scope'])
        observations = {}
        for fault in ('global_ref_only', 'unstyle_leaks'):
            results = run_model(jobs, _TextModel(fault))
            self.assertEqual(len(results), len(jobs), results[-1])
            self.assertTrue(all(r[1] for r in results), results[-1])
            observations[fault] = {r[0].split(':')[-1]: r[2]['result'] for r in results if 'result' in r[2]}
        self.assertEqual(observations['global_ref_only']['replace_middle_after_0_ref'], 0)
        self.assertEqual(observations['global_ref_only']['replace_middle_after_0_font_name'], 'Arial')
        self.assertEqual(observations['global_ref_only']['replace_middle_after_2_font_name'], 'Courier New')
        self.assertEqual(observations['unstyle_leaks']['replace_middle_after_0_font_name'], 'Courier New')
        self.assertTrue(all(j['verification_dimension'] == 'characterization' for j in jobs))

    def test_supplementary_offset_probe_never_uses_raw_utf8_byte_positions(self):
        jobs = ANNOTATION.annotation_fixtures('offsets', ['annotation_text_offset_units'])
        getters = [j for j in jobs if j.get('name') == 'GetTextStyle']
        self.assertEqual({j['arguments']['Position'] for j in getters}, {0, 1, 2, 3})
        for job in jobs:
            self.assertEqual(job['verification_dimension'], 'characterization')
            if job.get('name') == 'SetTextStyle':
                self.assertLessEqual(job['arguments']['Start'] + job['arguments']['Count'], 4)
        results = run_model(jobs, _TextModel())
        self.assertTrue(all(r[1] for r in results), results[-1])

    def test_utf16_run_semantics_have_fixed_vectors_and_detect_noop_or_leakage(self):
        jobs = ANNOTATION.annotation_fixtures('utf16runs', ['annotation_text_utf16_runs'])
        expected = [0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1]
        reads = [j for j in jobs if j.get('name') == 'GetTextStyle']
        self.assertEqual([j['assertions'][0]['equals'] for j in reads], expected)
        self.assertFalse(any(j.get('verification_dimension') == 'characterization' for j in jobs))
        self._fault('annotation_text_utf16_runs', _TextModel('utf16_last_noop'), 'bold_b_utf16_char_3')
        self._fault('annotation_text_utf16_runs', _TextModel('style_leaks'), 'bold_a_char_1')

    def test_utf16_length_semantics_cover_empty_combining_and_supplementary_strings(self):
        jobs = ANNOTATION.annotation_fixtures('utf16lengths', ['annotation_text_utf16_lengths'])
        reads = [j for j in jobs if j.get('name') == 'GetTextLength']
        self.assertEqual([j['assertions'][0]['equals'] for j in reads], [0, 3, 1, 1, 2, 4, 560])
        self.assertEqual(sum(j.get('name') == 'SetText' for j in jobs), 7)
        self.assertFalse(any(j.get('verification_dimension') == 'characterization' for j in jobs))
        self._fault('annotation_text_utf16_lengths', _TextModel('utf8_text_length'), 'accent_utf16_length')
        self._fault('annotation_text_utf16_lengths', _TextModel('codepoint_text_length'), 'supplementary_utf16_length')

    def test_size_scope_calibrates_effective_units_without_assuming_selector_point_equivalence(self):
        jobs = ANNOTATION.annotation_fixtures('sizescope', ['annotation_text_style_size_scope'])
        self.assertTrue(all(j['verification_dimension'] == 'characterization' for j in jobs))
        for scale in (1.0, 25.4 / 72.0, 2.5):
            with self.subTest(resource_to_points=scale):
                results = run_model(jobs, _TextModel(size_scale=scale))
                self.assertEqual(len(results), len(jobs), results[-1])
                self.assertTrue(all(r[1] for r in results), results[-1])
                measured = next(r[2]['result'] for r in results if r[0].endswith(':control_a_calibrated_size'))
                self.assertAlmostEqual(measured, 12 * scale)
        # The resource getter under dispute is never used to infer substring links.
        results = run_model(jobs, _TextModel('global_ref_only'))
        self.assertTrue(all(r[1] for r in results), results[-1])
        self.assertNotIn('SetObjectVariableInt', {j.get('name') for j in jobs})
        self.assertNotIn('GetTextStyleRefN', {j.get('name') for j in jobs})

    def test_size_scope_fails_calibration_before_inference_when_setter_or_update_does_nothing(self):
        for fault, label in [('resource_size_noop', 'whole_styles_have_distinct_sizes'),
                             ('propagation_noop', 'updated_a_control_changed'),
                             ('eq_always_true', 'compare_unequal'), ('eq_always_false', 'compare_equal')]:
            with self.subTest(fault=fault):
                results = self._fault('annotation_text_style_size_scope', _TextModel(fault), label)
                self.assertFalse(any(r[0].endswith(':after_a_clear_middle_matches_0') for r in results))

    def test_size_scope_distinguishes_cached_unstyled_formatting_from_lost_outer_resource_links(self):
        self._fault('annotation_text_style_size_scope', _TextModel('clear_loses_outer_links'),
                    'after_a_clear_middle_matches_0')
        self._fault('annotation_text_style_size_scope', _TextModel('propagation_touches_unstyled'),
                    'after_a_clear_middle_matches_2')
        self._fault('annotation_text_style_size_scope', _TextModel('partial_style_noop'),
                    'replace_middle_after_edit_matches_2')
        self._fault('annotation_text_style_size_scope', _TextModel('unstyle_leaks'),
                    'replace_middle_after_edit_matches_0')

    def test_size_scope_detects_cross_resource_updates_and_preserves_candidate_associations(self):
        self._fault('annotation_text_style_size_scope', _TextModel('propagation_cross_resource'),
                    'after_a_control_b_matches_0')
        jobs = ANNOTATION.annotation_fixtures('isolatedsizes', ['annotation_text_style_size_scope'])
        first_update = next(i for i, j in enumerate(jobs) if j.get('name') == 'UpdateStyledObjects')
        self.assertFalse(any(j.get('name') in ('SetTextStyleRef', 'SetTextStyleRefN', 'SetTextSize')
                             for j in jobs[first_update:]))
        self.assertEqual(sum(j.get('name') == 'CreateTextStyleRes' for j in jobs), 2)
        self.assertEqual(sum(j.get('name') == 'UpdateStyledObjects' for j in jobs), 2)

    def test_routine_unicode_replacement_keeps_exact_content_and_later_edges_without_length_assumption(self):
        jobs = ANNOTATION.annotation_fixtures('routine', ['annotation_text_replacements'])
        results = run_model(jobs, _TextModel('utf8_text_length'))
        self.assertEqual(len(results), len(jobs))
        self.assertTrue(all(r[1] for r in results), results[-1])
        self.assertFalse(any(j['id'].endswith(':unicode_length') for j in jobs))
        for label in ('unicode_content', 'adjacent_content', 'expanding_content', 'last_character_content',
                      'delete_substring_content', 'no_match_content'):
            self.assertTrue(any(r[0].endswith(':' + label) and r[1] for r in results), label)

    def test_border_axes_and_disabling_are_independently_checked(self):
        for fault, label in [('transpose_border', 'top_enabled'), ('border_disable_noop', 'top_disabled')]:
            with self.subTest(fault=fault):
                self._fault('annotation_ws_borders', _WorksheetModel(fault), label)

    def test_border_scope_observations_preserve_legacy_discrepancy_and_verify_explicit_removal(self):
        jobs = ANNOTATION.annotation_fixtures('borderscope', ['annotation_ws_border_scope'])
        self.assertTrue(all(j['verification_dimension'] == 'characterization' for j in jobs))
        self.assertEqual(sum(j.get('name') == 'CreateWS' for j in jobs), 2)
        self.assertNotIn('ClearWSCell', {j.get('name') for j in jobs})
        good = run_model(jobs, _WorksheetModel())
        legacy_noop = run_model(jobs, _WorksheetModel('legacy_clear_noop'))
        self.assertEqual(len(good), len(jobs), good[-1])
        self.assertEqual(len(legacy_noop), len(jobs), legacy_noop[-1])
        self.assertTrue(all(r[1] for r in good + legacy_noop))
        normal = {r[0].split(':')[-1]: r[2]['result'] for r in good}
        faulty = {r[0].split(':')[-1]: r[2]['result'] for r in legacy_noop}
        self.assertEqual(normal['same_range_legacy_result_2_2'], [False] * 4)
        self.assertEqual(faulty['same_range_legacy_result_2_2'], [True, True, False, False])
        for label in ('same_range', 'enclosing_range'):
            self.assertEqual(faulty[label + '_explicit_clear_2_2'], [False] * 4)
            self.assertEqual(faulty[label + '_content_preserved'], 'Preserve café 東京 ' + label)
        self._fault('annotation_ws_border_scope', _WorksheetModel('border_disable_noop'),
                    'same_range_explicit_clear_2_2')

    def test_long_unicode_worksheet_display_string_is_not_truncated(self):
        self._fault('annotation_ws_images', _WorksheetModel('truncate_strings'), 'long_display_string')

    def test_image_source_identity_scale_and_preservation_are_independent(self):
        for fault, label in [('wrong_image_source', 'image_source_identity'),
                             ('image_scale_noop', 'scale_0_5_read'),
                             ('image_corrupts_source', 'scale_0_5_preserves_source')]:
            with self.subTest(fault=fault):
                self._fault('annotation_ws_images', _WorksheetModel(fault), label)

    def test_font_indices_and_units_are_not_invented_native_arguments(self):
        for job in ANNOTATION.annotation_fixtures('fonts', ['annotation_text_runs']):
            if job.get('name') == 'SetTextFont':
                self.assertEqual(set(job['arguments']['FontNum']), {'$capture'})
            self.assertTrue(any('Arial and Courier New' in p for p in job['prerequisites']))
        layout = ANNOTATION.annotation_fixtures('units', ['annotation_text_layout'])
        self.assertEqual({j['arguments']['spacing'] for j in layout if j.get('name') == 'SetTextSpace'}, {2, 3, 4})
        self.assertTrue(all(any('points' in p for p in j['prerequisites']) for j in layout))

    def test_wrong_function_identity_cannot_pass_a_matching_text_value(self):
        job = next(j for j in self.jobs if j.get('name') == 'GetText')
        value = job['assertions'][0]['equals']
        self.assertFalse(HOST.evaluate_native(job, {'status': 'ok', 'function': 'GetName', 'result': value})[0])
        self.assertTrue(HOST.evaluate_native(job, {'status': 'ok', 'function': 'GetText', 'result': value})[0])


if __name__ == '__main__':
    unittest.main()
