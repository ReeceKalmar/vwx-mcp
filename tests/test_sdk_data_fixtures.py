"""Contract, independent-oracle, and mutation-fault tests for native data plans."""
import ast
import copy
import importlib.util
import json
import operator
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DATA = load('sdk_data_fixture_test', ROOT / 'tools/sdk_data_fixtures.py')
HOST = DATA.DESIGN.HOST
RUNTIME = HOST._load_runtime(ROOT)
RUNNER = load('sdk_data_typed_runner_test', ROOT / 'tools/sdk_design_runner.py')
POLICY = load('sdk_data_background_test', ROOT / 'mcp-server/background_policy.py')
CATALOG = json.loads((ROOT / 'vwx-plugin/sdk_catalog.json').read_text(encoding='utf-8'))
INDEX = json.loads((ROOT / 'vwx-plugin/vs_index.json').read_text(encoding='utf-8'))
with patch.dict(sys.modules, {'sdk_runtime': RUNTIME}):
    SEQUENCES = load('sdk_data_sequence_test', ROOT / 'vwx-plugin/sdk_sequences.py')


def capture_example(job):
    """Respect each declared capture's actual shape, rather than fake all as UUIDs."""
    assertion = next((a for a in job['assertions'] if a['path'] == job['capture']['path']), {})
    if 'range_inclusive' in assertion:
        return max(1, assertion['range_inclusive'][0])
    if assertion.get('valid_uuid'):
        return HOST.FIXTURE_UUID
    raise AssertionError('Capture has no independent shape assertion: ' + job['id'])


class _RecordModel:
    """Independent record storage model; intentionally unaware of fixture oracles."""
    def __init__(self, *, ignore_writes=False, leak_writes=False):
        self.by_uuid, self.formats, self.rectangles = {}, {}, []
        self.last = None
        self.ignore_writes, self.leak_writes = ignore_writes, leak_writes
        self.native_calls = []

    def _handle(self, kind, **values):
        h = SimpleNamespace(kind=kind, **values)
        key = str(uuid.uuid5(uuid.NAMESPACE_OID, 'data-model-%d' % len(self.by_uuid)))
        self.by_uuid[key] = h
        h.uuid = key
        return h

    def GetVersion(self):
        return 32, 0, 0, 2

    def GetObjectUuid(self, h):
        return h.uuid

    def GetObjectByUuid(self, key):
        return self.by_uuid.get(key)

    def GetTypeN(self, h):
        return 0 if h is None else h.kind

    def Rect(self, p1, p2):
        self.last = self._handle(3, corners=(p1, p2), records={})
        self.rectangles.append(self.last)

    def LNewObj(self):
        return self.last

    def GetBBox(self, h):
        return h.corners

    def NewField(self, recName, fieldName, fieldValue, fType, fFlag):
        if recName not in self.formats:
            self.formats[recName] = self._handle(47, name=recName, fields=[])
        self.formats[recName].fields.append((fieldName, fieldValue, fType, fFlag))

    def GetObject(self, name):
        return self.formats.get(name)

    def GetName(self, h):
        return h.name

    def NumFields(self, h):
        return len(h.fields)

    def GetFldName(self, h, index):
        return h.fields[index - 1][0]

    def GetFldType(self, h, t):
        return h.fields[t - 1][2]

    def GetFldFlag(self, h, t):
        return h.fields[t - 1][3]

    def SetRecord(self, h, record):
        template = self.formats[record]
        h.records[record] = self._handle(48, name=record, fields=template.fields[:],
                                       values={field: default for field, default, *_ in template.fields}, options={})

    def NumRecords(self, h):
        return len(h.records)

    def GetRecord(self, h, cnt):
        return list(h.records.values())[cnt - 1]

    def GetRField(self, h, record, field):
        return h.records[record].values[field]

    def SetRField(self, h, record, field, value):
        self.native_calls.append(('SetRField', value))
        if not self.ignore_writes:
            h.records[record].values[field] = value
        if self.leak_writes:
            for other in self.rectangles:
                other.records[record].values[field] = value

    def SetRFieldOpt(self, h, record, field, isEmpty, isDataLinked):
        h.records[record].options[field] = (isEmpty, isDataLinked)

    def GetRFieldOpt(self, h, record, field):
        return h.records[record].options.get(field, (False, False))

    def DelRecord(self, h, name):
        del h.records[name]


class _NativeMaterialHandle:
    """Model opaque native NIL separately from Python None and stale handles."""
    def __init__(self, pointer=0):
        self.pointer = pointer

    def __eq__(self, other):
        return type(other) is type(self) and other.pointer == self.pointer

    def __bool__(self):
        return False


class _MaterialModel(_RecordModel):
    """Independent resources, assignment state, and extrusion dimensions."""
    Handle = _NativeMaterialHandle

    def __init__(self, fault=None):
        super().__init__()
        self.fault, self.textures, self.materials = fault, [], []

    def GetTypeN(self, h):
        return 0 if type(h) is _NativeMaterialHandle else super().GetTypeN(h)

    def CreateMaterial(self, name, isSimpleMaterial):
        h = self._handle(19, name=name, simple=isSimpleMaterial, texture=0, fill=1)
        self.materials.append(h)
        return h

    def IsMaterialSimple(self, materialHandle): return materialHandle.simple

    def CreateTexture(self):
        h = self._handle(97, name='', size=1)
        self.textures.append(h)
        return h

    def SetName(self, h, name): h.name = name
    def SetTextureSize(self, texture, newSize): texture.size = newSize
    def GetTextureSize(self, texture): return texture.size
    def Name2Index(self, name): return next(i for i, h in enumerate(self.textures, 1) if h.name == name)
    def Index2Name(self, index): return self.textures[index - 1].name

    def SetMaterialTexture(self, materialHandle, textureIndex):
        materialHandle.texture = textureIndex
        return True, materialHandle

    def GetMaterialTexture(self, objectHandle): return objectHandle.texture

    def SetMaterialFillStyle(self, materialHandle, fillStyle):
        materialHandle.fill = fillStyle
        return True

    def GetMaterialFillStyle(self, materialHandle): return materialHandle.fill

    def HExtrude(self, objectH, bottom, top):
        return self._handle(24, profile=objectH, z=(bottom, top), material=None)

    def Get3DInfo(self, h):
        first, second = h.profile.corners
        return abs(first[1] - second[1]), abs(first[0] - second[0]), abs(h.z[1] - h.z[0])

    def SetObjMaterialHandle(self, objectHandle, materialHandle):
        if self.fault != 'assignment_noop': objectHandle.material = materialHandle
        if self.fault == 'assignment_changes_depth': objectHandle.z = (0, 11)
        return True, objectHandle

    def GetObjMaterialHandle(self, h):
        if h.material is not None: return h.material
        if self.fault == 'unassigned_valid_handle': return self.materials[0]
        return self.Handle(999 if self.fault == 'stale_null_handle' else 0)

    def GetObjMaterialName(self, h):
        return (False, '') if h.material is None else (True, h.material.name)


class _WorksheetModel(_RecordModel):
    """Sparse worksheet model exercises dimension shifts and content preservation."""
    def __init__(self, *, wrong_insert_boundary=False):
        super().__init__()
        self.wrong_insert_boundary = wrong_insert_boundary

    def CreateWS(self, name, rows, columns):
        return self._handle(18, name=name, rows=rows, columns=columns, cells={}, merges=[])

    def GetWSRowColumnCount(self, worksheet):
        return worksheet.rows, worksheet.columns

    def IsValidWSCell(self, worksheet, row, column):
        return 0 <= row <= worksheet.rows and 0 <= column <= worksheet.columns

    def IsValidWSRange(self, worksheet, topRow, leftColumn, bottomRow, rightColumn):
        return (0 <= topRow <= bottomRow <= worksheet.rows
                and 0 <= leftColumn <= rightColumn <= worksheet.columns)

    def SetWSCellFormulaN(self, worksheet, topRow, leftColumn, bottomRow, rightColumn, formula):
        for row in range(topRow, bottomRow + 1):
            for col in range(leftColumn, rightColumn + 1):
                worksheet.cells[row, col] = formula

    def GetWSCellFormulaN(self, worksheet, row, column):
        return worksheet.cells.get((row, column), '')

    def InsertWSRows(self, worksheet, beforeRow, numRows):
        worksheet.cells = {(r + numRows if r >= beforeRow else r, c): value
                           for (r, c), value in worksheet.cells.items()}
        worksheet.rows += numRows

    def InsertWSColumns(self, worksheet, beforeColumn, numColumns):
        threshold = beforeColumn + int(self.wrong_insert_boundary)
        worksheet.cells = {(r, c + numColumns if c >= threshold else c): value
                           for (r, c), value in worksheet.cells.items()}
        worksheet.columns += numColumns

    def DeleteWSRows(self, worksheet, startRow, numRows):
        after = startRow + numRows
        worksheet.cells = {(r - numRows if r >= after else r, c): value
                           for (r, c), value in worksheet.cells.items() if not startRow <= r < after}
        worksheet.rows -= numRows

    def DeleteWSColumns(self, worksheet, startColumn, numColumns):
        after = startColumn + numColumns
        worksheet.cells = {(r, c - numColumns if c >= after else c): value
                           for (r, c), value in worksheet.cells.items() if not startColumn <= c < after}
        worksheet.columns -= numColumns

    def WorksheetMergeCells(self, worksheet, topRow, leftColumn, bottomRow, rightColumn):
        worksheet.merges.append((topRow, leftColumn, bottomRow, rightColumn))
        return True

    def GetWSMergedCellRange(self, worksheet, row, column):
        for top, left, bottom, right in worksheet.merges:
            if top <= row <= bottom and left <= column <= right:
                return True, top, left, bottom, right
        return False, 0, 0, 0, 0

    def WorksheetSplitCells(self, worksheet, topRow, leftColumn, bottomRow, rightColumn):
        worksheet.merges.remove((topRow, leftColumn, bottomRow, rightColumn))
        return True


class _WorksheetValueModel(_WorksheetModel):
    """Small arithmetic evaluator independent of the fixture's literal answers."""
    def __init__(self, *, number_is_string=False, forbid_classification=False, wrong_numeric_value=False):
        super().__init__()
        self.number_is_string = number_is_string
        self.forbid_classification = forbid_classification
        self.wrong_numeric_value = wrong_numeric_value

    @staticmethod
    def _arithmetic(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -_WorksheetValueModel._arithmetic(node.operand)
        if isinstance(node, ast.BinOp):
            functions = {ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow}
            return functions[type(node.op)](_WorksheetValueModel._arithmetic(node.left),
                                            _WorksheetValueModel._arithmetic(node.right))
        raise AssertionError('The offline worksheet model only evaluates concrete arithmetic')

    def _value(self, worksheet, row, column):
        formula = worksheet.cells.get((row, column), '')
        if formula.startswith('='):
            return self._arithmetic(ast.parse(formula[1:].replace('^', '**'), mode='eval').body)
        try:
            return float(formula)
        except ValueError:
            pass
        return formula

    def SetWSCellFormula(self, worksheet, topRow, leftColumn, bottomRow, rightColumn, formula):
        self.SetWSCellFormulaN(worksheet, topRow, leftColumn, bottomRow, rightColumn, formula)

    def RecalculateWS(self, worksheet):
        pass  # Evaluation on read has no shared implementation with production.

    def GetWSCellValue(self, worksheet, row, column):
        return self._value(worksheet, row, column) + int(self.wrong_numeric_value)

    def GetWSCellStringN(self, worksheet, row, column):
        return str(self._value(worksheet, row, column))

    def GetWSCellString(self, worksheet, row, column):
        return self.GetWSCellStringN(worksheet, row, column)

    def ClearWSCell(self, worksheet, topRow, leftColumn, bottomRow, rightColumn):
        for row in range(topRow, bottomRow + 1):
            for column in range(leftColumn, rightColumn + 1):
                worksheet.cells.pop((row, column), None)

    def IsWSCellNumber(self, worksheet, row, column):
        if self.forbid_classification:
            raise AssertionError('Core values must not call classification predicates')
        return type(self._value(worksheet, row, column)) in (int, float)

    def IsWSCellString(self, worksheet, row, column):
        if self.forbid_classification:
            raise AssertionError('Core values must not call classification predicates')
        return self.number_is_string or isinstance(self._value(worksheet, row, column), str)


class _DatabaseWorksheetModel(_WorksheetValueModel):
    """Independent record query, cached calculation and ordered operator model."""
    def __init__(self, fault=None):
        super().__init__()
        self.fault = fault

    def CreateWS(self, name, rows, columns):
        h = super().CreateWS(name, rows, columns)
        h.autorecalc, h.operators, h.sort_types, h.cache, h.recalculations = True, {}, {}, {}, 0
        return h

    def SetWSAutoRecalcState(self, worksheet, state):
        worksheet.autorecalc = state

    def GetWSAutoRecalcState(self, worksheet):
        return worksheet.autorecalc

    def IsWSDatabaseRow(self, worksheet, databaseRow):
        return worksheet.cells.get((databaseRow, 0), '').startswith('=DATABASE(')

    def _row_value(self, worksheet, row, column, record_values):
        formula = worksheet.cells.get((row, column), '')
        field = re.fullmatch(r"='([^']+)'\.'([^']+)'", formula)
        if field:
            return record_values[field[1]][field[2]]
        return self._arithmetic(ast.parse(formula[1:], mode='eval').body)

    def RecalculateWS(self, worksheet):
        worksheet.recalculations += 1
        if self.fault == 'stale_calculation' and worksheet.recalculations > 1:
            return
        for (row, column), formula in worksheet.cells.items():
            if column != 0:
                continue
            criteria = re.fullmatch(r"=DATABASE\(R IN \['([^']+)'\]\)", formula)
            if criteria is None:
                raise AssertionError('Only documented fresh-record database criteria are modeled')
            members = [obj for obj in self.rectangles if criteria[1] in obj.records]
            if self.fault == 'ignores_record_filter':
                members = list(self.rectangles)
            values = [{name: copy.deepcopy(record.values) for name, record in obj.records.items()} for obj in members]
            sorts = [col for col, kinds in worksheet.operators.get(row, {}).items() if 0 in kinds]
            for sort_column in reversed(sorts):
                descending = worksheet.sort_types.get((row, sort_column), 0) == 1
                if self.fault == 'ignores_descending':
                    descending = False
                values.sort(key=lambda value: self._row_value(worksheet, row, sort_column, value), reverse=descending)
            worksheet.cache[row] = values

    def GetWSSubrowCount(self, worksheet, databaseRow):
        return len(worksheet.cache.get(databaseRow, []))

    def IsValidWSSubrowCell(self, worksheet, row, column, subrow):
        if self.fault == 'subrow_ignores_column':
            return 1 <= subrow <= self.GetWSSubrowCount(worksheet, row)
        return 1 <= column <= worksheet.columns and 1 <= subrow <= self.GetWSSubrowCount(worksheet, row)

    def _subrow(self, worksheet, row, column, subrow):
        return self._row_value(worksheet, row, column, worksheet.cache[row][subrow - 1])

    def GetWSSubrowActualStringN(self, worksheet, row, column, subrow):
        return str(self._subrow(worksheet, row, column, subrow))

    GetWSSubrowActualCellString = GetWSSubrowActualStringN
    GetWSSubrowCellString = GetWSSubrowActualStringN
    GetWSSubrowCellStrN = GetWSSubrowActualStringN

    def GetWSSubrowCellValue(self, worksheet, row, column, subrow):
        return self._subrow(worksheet, row, column, subrow)

    def AddWSColumnOperator(self, worksheet, databaseRow, column, operatorType):
        if self.fault != 'operator_noop':
            worksheet.operators.setdefault(databaseRow, {}).setdefault(column, set()).add(operatorType)

    def HasWSColumnOperator(self, worksheet, databaseRow, column, operatorType):
        return operatorType in worksheet.operators.get(databaseRow, {}).get(column, set())

    def SetWSColumnSortType(self, worksheet, databaseRow, column, sortType):
        worksheet.sort_types[databaseRow, column] = sortType

    def GetWSColumnSortType(self, worksheet, databaseRow, column):
        return worksheet.sort_types.get((databaseRow, column), 0)

    def MoveWSColumnOperator(self, worksheet, databaseRow, fromColumn, toColumn, operatorType):
        if self.fault != 'move_copies_instead':
            self.RemoveWSColumnOperator(worksheet, databaseRow, fromColumn, operatorType)
        self.AddWSColumnOperator(worksheet, databaseRow, toColumn, operatorType)

    def RemoveWSColumnOperator(self, worksheet, databaseRow, column, operatorType):
        worksheet.operators.get(databaseRow, {}).get(column, set()).discard(operatorType)

    def RemoveAllWSColumnOperators(self, worksheet, databaseRow, operatorType):
        if self.fault == 'clear_only_sort':
            operatorType = 0
        for column in list(worksheet.operators.get(databaseRow, {})):
            if operatorType == -1:
                worksheet.operators[databaseRow][column].clear()
            else:
                self.RemoveWSColumnOperator(worksheet, databaseRow, column, operatorType)


class _EdgeWorksheetModel(_WorksheetValueModel):
    def __init__(self, fault=None):
        super().__init__()
        self.fault = fault

    def InsertWSRows(self, worksheet, beforeRow, numRows):
        if self.fault == 'wrong_worksheet':
            worksheet = next(h for h in self.by_uuid.values() if h.kind == 18 and h is not worksheet)
        if self.fault != 'insert_noop':
            super().InsertWSRows(worksheet, beforeRow + int(self.fault == 'wrong_boundary'), numRows)

    def DeleteWSColumns(self, worksheet, startColumn, numColumns):
        if self.fault == 'wrong_delete_count':
            numColumns += 1
        super().DeleteWSColumns(worksheet, startColumn, numColumns)


def run_model(jobs, model):
    """Run actual typed adapters one job at a time; stop on the first bad oracle."""
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
        if not passed:
            break
        if 'capture' in job:
            captures[job['capture']['name']] = HOST._at(response, job['capture']['path'])
    return results


class SDKDataFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jobs = DATA.data_fixtures('offline')

    def test_exact_index_runtime_and_background_policy_for_every_call(self):
        captures, names = {}, set()
        for job in self.jobs:
            self.assertEqual(job['native_status'], 'pending_not_executed')
            for c in job.get('calls', [job]):
                name = c['name']
                names.add(name)
                self.assertEqual(set(c['arguments']), set(INDEX[name]['args']), job['id'])
                result = RUNTIME.validate(name, {'arguments': HOST._substitute(c['arguments'], captures)},
                            catalog=CATALOG, invocation_context={'sequence': True},
                            reference_validator=lambda value, _: isinstance(value, dict) and '$ref' in value)
                self.assertNotIn('error', result, (job['id'], result))
                context = CATALOG['functions'][name]['context']
                self.assertFalse(context['interactive'], name)
                self.assertFalse(context['quarantined'], name)
                self.assertFalse(context['unsupported_reason'], name)
            request = RUNNER.render_typed_job(job, captures)
            self.assertIn(request['command'], ('sdk_call', 'sdk_sequence'))
            self.assertIsNone(POLICY.check(request['command'], request['params'], sdk_catalog=CATALOG['functions']))
            if 'capture' in job:
                self.assertNotIn(job['capture']['name'], captures)
                captures[job['capture']['name']] = capture_example(job)
        self.assertGreaterEqual(len(self.jobs), 250)
        self.assertGreaterEqual(len(names), 100)

    def test_independent_families_and_strict_names(self):
        for family in DATA.FAMILIES:
            captures = {}
            for job in DATA.data_fixtures('isolated', [family]):
                self.assertEqual(job['fixture_family'], family)
                HOST._substitute(job.get('calls', job.get('arguments')), captures)
                if 'capture' in job:
                    captures[job['capture']['name']] = capture_example(job)
        for run_id in ('', None, 1, '../path', 'contains space', 'x' * 81):
            with self.assertRaises(ValueError):
                DATA.data_fixtures(run_id)
        for families in ([], ['absent'], ['data_records', 'data_records']):
            with self.assertRaises(ValueError):
                DATA.data_fixtures('run', families)

    def test_every_mutation_has_a_later_independent_readback(self):
        positions = {j['id']: i for i, j in enumerate(self.jobs)}
        self.assertEqual(len(positions), len(self.jobs), 'Duplicate durable evidence IDs')
        verified = set()
        for job in self.jobs:
            for previous in job.get('verifies_jobs', []):
                self.assertLess(positions[previous], positions[job['id']])
                self.assertEqual(job['phase'], 'readback')
                verified.add(previous)
        mutations = {j['id'] for j in self.jobs if j['phase'] == 'mutation'}
        self.assertEqual(mutations - verified, set())

    def test_no_global_state_or_undocumented_selector_changes(self):
        forbidden = {'NameClass', 'Layer', 'SetPref', 'SetPrefInt', 'SetPrefReal', 'SetPrefLongInt',
                     'SetObjectVariableBoolean', 'SetObjectVariableInt', 'SetObjectVariableReal',
                     'DoMenuTextByName', 'RunScript', 'RunScriptN', 'UprString', 'HArea',
                     'ShowWS', 'SaveActiveDocument', 'DelObject'}
        for job in self.jobs:
            for c in job.get('calls', [job]):
                self.assertNotIn(c['name'], forbidden)
                self.assertNotIn('code', c)
                self.assertNotIn('options', c)
                for key, value in c['arguments'].items():
                    if CATALOG['functions'][c['name']]['parameters'][INDEX[c['name']]['args'].index(key)]['type'] == 'HANDLE':
                        self.assertIsInstance(value, dict, (job['id'], key))
                        self.assertTrue('$capture' in value or '$ref' in value, (job['id'], key))

    def test_record_model_roundtrip_unicode_empty_long_and_instance_isolation(self):
        jobs = DATA.data_fixtures('recordmodel', ['data_records'])
        model = _RecordModel()
        results = run_model(jobs, model)
        self.assertEqual(len(results), len(jobs), results[-1])
        self.assertTrue(all(row[1] for row in results), results[-1])
        writes = [value for name, value in model.native_calls if name == 'SetRField']
        self.assertIn('', writes)
        self.assertTrue(any(len(value) > 255 for value in writes))
        self.assertTrue(any('東京' in value for value in writes))
        self.assertEqual(len(model.rectangles), 2)
        for rect in model.rectangles:
            self.assertEqual(rect.records['SDK-Data-Record-recordmodel'].values['Label'], 'Default')

    def test_silent_record_setter_noop_fails_readback_not_setter_contract(self):
        model = _RecordModel(ignore_writes=True)
        results = run_model(DATA.data_fixtures('noop', ['data_records']), model)
        self.assertFalse(results[-1][1])
        self.assertEqual(results[-1][0], 'design:data_records:set_unicode_read')
        self.assertEqual(len(model.native_calls), 1, 'Failure must stop before further mutations')
        self.assertTrue(results[-2][1], 'Void setter alone cannot establish semantics')

    def test_accidental_cross_instance_write_is_detected(self):
        model = _RecordModel(leak_writes=True)
        results = run_model(DATA.data_fixtures('leak', ['data_records']), model)
        self.assertFalse(results[-1][1])
        self.assertEqual(results[-1][0], 'design:data_records:other_instance_unchanged_unicode')
        self.assertEqual(len(model.native_calls), 1)

    def test_worksheet_numeric_oracles_are_independently_computed(self):
        expectations = {'numeric_1_1_value': 6 * 7, 'numeric_2_1_value': -5 / 2,
                        'numeric_3_1_value': 3 - 3, 'numeric_4_1_value': 2 ** 10,
                        'numeric_5_1_value': 1 / 8}
        jobs = {j['id'].split(':')[-1]: j for j in DATA.data_fixtures('values', ['data_worksheet_values'])}
        for label, value in expectations.items():
            assertion = jobs[label]['assertions'][0]
            self.assertEqual(assertion['equals'], value)
            self.assertTrue(HOST.evaluate_native(jobs[label], {'status': 'ok', 'function': jobs[label]['name'], 'result': value})[0])
            self.assertFalse(HOST.evaluate_native(jobs[label], {'status': 'ok', 'function': jobs[label]['name'], 'result': value + 1})[0])
            self.assertFalse(HOST.evaluate_native(jobs[label], {'status': 'ok', 'function': jobs[label]['name'], 'result': str(value)})[0])
        self.assertFalse(HOST.evaluate_native(jobs['numeric_3_1_value'], {'status': 'ok', 'function': 'GetWSCellValue', 'result': False})[0])

    def test_worksheet_sparse_model_runs_structure_fixture_through_real_adapters(self):
        jobs = DATA.data_fixtures('sheetmodel', ['data_worksheet_structure'])
        model = _WorksheetModel()
        results = run_model(jobs, model)
        self.assertEqual(len(results), len(jobs), results[-1])
        self.assertTrue(all(row[1] for row in results), results[-1])
        sheet = next(value for value in model.by_uuid.values() if value.kind == 18)
        self.assertEqual((sheet.rows, sheet.columns), (4, 4))
        self.assertEqual(sheet.cells, {(2, 2): 'Moving sentinel'})
        self.assertEqual(sheet.merges, [])

    def test_worksheet_off_by_one_insertion_fails_preservation_oracle(self):
        results = run_model(DATA.data_fixtures('sheetfault', ['data_worksheet_structure']),
                            _WorksheetModel(wrong_insert_boundary=True))
        self.assertFalse(results[-1][1])
        self.assertEqual(results[-1][0], 'design:data_worksheet_structure:column_content_moves')
        self.assertTrue(results[-2][1], 'Successful void result cannot hide wrong structural edits')

    def test_database_queries_follow_record_changes_and_removed_membership(self):
        jobs = DATA.data_fixtures('database', ['data_worksheet_database'])
        model = _DatabaseWorksheetModel()
        results = run_model(jobs, model)
        self.assertEqual(len(results), len(jobs), results[-1])
        self.assertTrue(all(r[1] for r in results), results[-1])
        self.assertEqual(len(model.rectangles), 2)
        self.assertTrue(all(not obj.records for obj in model.rectangles))
        actual = {r[0].split(':')[-1]: r[2].get('result') for r in results}
        self.assertEqual(actual['initial_subrow_count'], 1)
        self.assertEqual(actual['numeric_subrow_value'], 6 * 7)
        self.assertEqual(actual['empty_database'], 0)
        self.assertEqual(actual['GetWSSubrowActualStringN_updated'], 'Updated façade')

    def test_database_readbacks_detect_stale_recalculation_and_wrong_membership(self):
        jobs = DATA.data_fixtures('databasefault', ['data_worksheet_database'])
        for fault, label in [('stale_calculation', 'GetWSSubrowActualCellString_updated'),
                             ('ignores_record_filter', 'initial_subrow_count')]:
            with self.subTest(fault=fault):
                results = run_model(jobs, _DatabaseWorksheetModel(fault))
                self.assertFalse(results[-1][1])
                self.assertTrue(results[-1][0].endswith(':' + label), results[-1])

    def test_database_uses_explicit_cell_bounds_without_reinterpreting_subrow_predicate(self):
        jobs = DATA.data_fixtures('separatebounds', ['data_worksheet_database'])
        subrows = [job for job in jobs if job.get('name') == 'IsValidWSSubrowCell']
        self.assertTrue(all(1 <= job['arguments']['column'] <= 3 for job in subrows))
        self.assertTrue(all('worksheet-limits-native-20260926-a' in job['evidence_basis'] for job in jobs))
        self.assertTrue(all('012-78d69a52dec2' in job['evidence_basis'] for job in jobs))
        for fault in (None, 'subrow_ignores_column'):
            with self.subTest(fault=fault):
                results = run_model(jobs, _DatabaseWorksheetModel(fault))
                self.assertEqual(len(results), len(jobs), results[-1])
                self.assertTrue(all(row[1] for row in results), results[-1])
                actual = {row[0].split(':')[-1]: row[2].get('result') for row in results}
                self.assertEqual(actual['database_dimensions_preserved'], [4, 3])
                for column in (3, 4, 5):
                    for kind in ('cell', 'range'):
                        self.assertIs(actual['database_%s_bounds_%d' % (kind, column)], column == 3)
                self.assertFalse(actual['ordinary_row_has_no_subrow'])
                self.assertEqual(actual['GetWSSubrowActualStringN_updated'], 'Updated façade')
                self.assertEqual(actual['empty_database'], 0)

    def test_database_detects_wrong_cell_range_bounds_and_fabricated_subrows(self):
        jobs = DATA.data_fixtures('boundsfault', ['data_worksheet_database'])
        for api, label in (('IsValidWSCell', 'database_cell_bounds_4'),
                           ('IsValidWSRange', 'database_range_bounds_4'),
                           ('IsValidWSSubrowCell', 'valid_subrow_1_2')):
            model = _DatabaseWorksheetModel()
            setattr(model, api, lambda *args: True)
            results = run_model(jobs, model)
            self.assertFalse(results[-1][1])
            self.assertTrue(results[-1][0].endswith(':' + label), results[-1])
            self.assertNotIn('error', results[-1][2])

    def test_operator_lifecycle_checks_actual_sorted_rows_and_clear_all_types(self):
        jobs = DATA.data_fixtures('operators', ['data_worksheet_operators'])
        results = run_model(jobs, _DatabaseWorksheetModel())
        self.assertEqual(len(results), len(jobs), results[-1])
        self.assertTrue(all(r[1] for r in results), results[-1])
        actual = {r[0].split(':')[-1]: r[2].get('result') for r in results}
        self.assertEqual([actual['ascending_item_1'], actual['ascending_item_2']], sorted(['Beta', 'Alpha']))
        self.assertEqual([actual['descending_item_1'], actual['descending_item_2']], sorted(['Beta', 'Alpha'], reverse=True))
        self.assertFalse(actual['old_sort_removed'])
        self.assertTrue(actual['new_sort_present'])
        self.assertEqual(actual['members_preserved'], 2)

    def test_operator_metadata_cannot_hide_noop_bad_sort_or_leaking_move(self):
        jobs = DATA.data_fixtures('operatorfault', ['data_worksheet_operators'])
        for fault, label in [('operator_noop', 'sort_added'), ('ignores_descending', 'descending_item_1'),
                             ('move_copies_instead', 'old_sort_removed'), ('clear_only_sort', 'cleared_operator_2_2')]:
            with self.subTest(fault=fault):
                results = run_model(jobs, _DatabaseWorksheetModel(fault))
                self.assertFalse(results[-1][1])
                self.assertTrue(results[-1][0].endswith(':' + label), results[-1])

    def test_database_criteria_and_operator_constants_are_exact_and_owned(self):
        for family in ('data_worksheet_database', 'data_worksheet_operators'):
            jobs = DATA.data_fixtures('x' * 80, [family])
            criteria = [j['arguments']['formula'] for j in jobs if j.get('name') == 'SetWSCellFormulaN'
                        and j['arguments']['leftColumn'] == 0]
            record = next(j['arguments']['recName'] for j in jobs if j.get('name') == 'NewField')
            self.assertEqual(criteria, ["=DATABASE(R IN ['" + record + "'])"])
            self.assertLessEqual(len(record), 60)
            self.assertTrue(record.isascii())
            for job in jobs:
                args = job.get('arguments', {})
                if 'operatorType' in args:
                    self.assertIn(args['operatorType'], (-1, 0, 1, 2))
                if args.get('leftColumn') == 0:
                    self.assertEqual(job['name'], 'SetWSCellFormulaN')
                    self.assertEqual((args['topRow'], args['bottomRow'], args['rightColumn']), (2, 2, 0))

    def test_first_last_row_column_edits_preserve_formula_and_control_sheet(self):
        jobs = DATA.data_fixtures('edgeedits', ['data_worksheet_edge_edits'])
        model = _EdgeWorksheetModel()
        results = run_model(jobs, model)
        self.assertEqual(len(results), len(jobs), results[-1])
        self.assertTrue(all(r[1] for r in results), results[-1])
        sheets = [h for h in model.by_uuid.values() if h.kind == 18]
        self.assertEqual((sheets[0].rows, sheets[0].columns), (3, 3))
        self.assertEqual(sheets[0].cells, {(1, 1): 'NW', (2, 2): '=6*7'})
        self.assertEqual(sheets[1].cells, {(2, 2): 'Untouched control'})
        self.assertEqual((sheets[1].rows, sheets[1].columns), (4, 4))

    def test_edge_edits_detect_noop_wrong_object_shift_and_delete_boundary(self):
        jobs = DATA.data_fixtures('edgefault', ['data_worksheet_edge_edits'])
        for fault, label in [('insert_noop', 'insert_first_row_dimensions'),
                             ('wrong_worksheet', 'insert_first_row_dimensions'),
                             ('wrong_boundary', 'insert_first_row_cell_2_1'),
                             ('wrong_delete_count', 'delete_last_column_dimensions')]:
            with self.subTest(fault=fault):
                results = run_model(jobs, _EdgeWorksheetModel(fault))
                self.assertFalse(results[-1][1])
                self.assertTrue(results[-1][0].endswith(':' + label), results[-1])

    def test_invalid_worksheet_coordinates_only_enter_documented_validity_predicate(self):
        seen = []
        for job in DATA.data_fixtures('bounds', ['data_worksheet_boundaries']):
            if job.get('name') == 'IsValidWSCell':
                r, c = job['arguments']['row'], job['arguments']['column']
                expected = 0 <= r <= 6 and 0 <= c <= 5
                self.assertEqual(job['assertions'][0]['equals'], expected)
                seen.append((r, c))
            elif 'row' in job.get('arguments', {}):
                self.assertGreaterEqual(job['arguments']['row'], 1)
                self.assertGreaterEqual(job['arguments']['column'], 1)
        self.assertIn((0, 0), seen)
        self.assertIn((-1, 1), seen)
        self.assertIn((7, 5), seen)

    def test_disputed_zero_boundaries_are_independent_and_run_after_normal_cases(self):
        values = DATA.data_fixtures('values', ['data_worksheet_values'])
        self.assertFalse(any(job.get('name') == 'IsValidWSCell' for job in values))
        boundaries = DATA.data_fixtures('boundary', ['data_worksheet_boundaries'])
        self.assertEqual(boundaries[0]['name'], 'CreateWS')
        zero_cases = [job for job in boundaries if job.get('name') == 'IsValidWSCell'
                      and 0 in (job['arguments']['row'], job['arguments']['column'])]
        self.assertEqual(zero_cases, boundaries[-3:])
        self.assertEqual({(job['arguments']['row'], job['arguments']['column']) for job in zero_cases},
                         {(0, 1), (1, 0), (0, 0)})
        for job in zero_cases:
            self.assertTrue(job['assertions'][0]['equals'], 'Do not replace the SDK oracle with the observed failure')
            self.assertIn('unresolved', job['known_issue'])
            self.assertFalse(HOST.evaluate_native(job, {'status': 'ok', 'function': 'IsValidWSCell', 'result': False})[0])

    def test_core_value_family_executes_without_any_classification_predicate(self):
        jobs = DATA.data_fixtures('valuesonly', ['data_worksheet_values'])
        self.assertFalse(any(j.get('name') in ('IsValidWSCell', 'IsWSCellNumber', 'IsWSCellString') for j in jobs))
        results = run_model(jobs, _WorksheetValueModel(forbid_classification=True))
        self.assertEqual(len(results), len(jobs), results[-1])
        self.assertTrue(all(r[1] for r in results), results[-1])

    def test_value_family_still_rejects_wrong_numeric_results(self):
        results = run_model(DATA.data_fixtures('wrongvalue', ['data_worksheet_values']),
                            _WorksheetValueModel(wrong_numeric_value=True))
        self.assertFalse(results[-1][1])
        self.assertEqual(results[-1][0], 'design:data_worksheet_values:numeric_1_1_value')

    def test_classification_remains_independent_with_original_literal_oracles(self):
        jobs = DATA.data_fixtures('classification', ['data_worksheet_classification'])
        self.assertEqual(jobs[0]['name'], 'CreateWS')
        results = run_model(jobs, _WorksheetValueModel())
        self.assertEqual(len(results), len(jobs), results[-1])
        self.assertTrue(all(r[1] for r in results), results[-1])
        numbers = [j for j in jobs if j['id'].endswith('_not_string')]
        strings = [j for j in jobs if j['id'].endswith('_not_number')]
        self.assertEqual(len(numbers), 5)
        self.assertEqual(len(strings), 3)
        self.assertTrue(all(j['assertions'][0]['equals'] is False for j in numbers + strings))

    def test_recorded_both_true_predicate_outcome_is_still_a_diagnostic_failure(self):
        results = run_model(DATA.data_fixtures('bothtrue', ['data_worksheet_classification']),
                            _WorksheetValueModel(number_is_string=True))
        self.assertFalse(results[-1][1])
        self.assertEqual(results[-1][0], 'design:data_worksheet_classification:numeric_1_1_not_string')
        self.assertEqual(results[-1][2]['result'], True)
        self.assertTrue(results[-2][1], 'Number=True passed independently before String=True failed')

    def test_diagnostic_families_remain_available_and_explicitly_marked(self):
        self.assertEqual(DATA.DIAGNOSTIC_FAMILIES,
                         ('data_worksheet_boundaries', 'data_worksheet_classification',
                          'data_worksheet_type_probe', 'data_worksheet_validity_probe'))
        self.assertTrue(set(DATA.DIAGNOSTIC_FAMILIES) <= set(DATA.FAMILIES))
        available = DATA.data_fixtures('alloffline')
        for family in DATA.DIAGNOSTIC_FAMILIES:
            selected = DATA.data_fixtures('alloffline', [family])
            self.assertEqual(selected, [j for j in available if j['fixture_family'] == family])
            self.assertTrue(all(j['diagnostic_only'] is True for j in selected))
            self.assertTrue(all(any('Explicitly select' in p for p in j['prerequisites']) for j in selected))
        routine = [j for j in available if j['fixture_family'] not in DATA.DIAGNOSTIC_FAMILIES]
        self.assertFalse(any(j.get('diagnostic_only') for j in routine))
        zero = next(j for j in available if j['id'].endswith(':bounds_0_0'))
        self.assertIs(zero['assertions'][0]['equals'], True)
        self.assertIn('causality is unproven', zero['known_issue'])

    def test_type_characterization_records_discrepancy_without_false_semantic_credit(self):
        jobs = DATA.data_fixtures('types', ['data_worksheet_type_probe'])
        self.assertTrue(all(j['verification_dimension'] == 'characterization' for j in jobs))
        ordinary = run_model(jobs, _WorksheetValueModel())
        observed_bug = run_model(jobs, _WorksheetValueModel(number_is_string=True))
        self.assertEqual(len(ordinary), len(jobs), ordinary[-1])
        self.assertEqual(len(observed_bug), len(jobs), observed_bug[-1])
        self.assertTrue(all(r[1] for r in ordinary + observed_bug))
        normal = {r[0].split(':')[-1]: r[2]['result'] for r in ordinary}
        faulty = {r[0].split(':')[-1]: r[2]['result'] for r in observed_bug}
        for label in ('literal_integer', 'literal_negative', 'literal_zero', 'numeric_formula'):
            self.assertIs(normal[label + '_number'], True)
            self.assertIs(normal[label + '_string'], False)
            self.assertIs(faulty[label + '_string'], True)
        self.assertEqual(normal['unicode_text_display'], 'café 東京')
        self.assertFalse(run_model(jobs, _WorksheetValueModel(wrong_numeric_value=True))[-1][1])

    def test_validity_probe_never_dereferences_headers_or_invalid_cells(self):
        jobs = DATA.data_fixtures('validity', ['data_worksheet_validity_probe'])
        results = run_model(jobs, _WorksheetModel())
        self.assertEqual(len(results), len(jobs), results[-1])
        self.assertTrue(all(r[1] for r in results))
        allowed = {'CreateWS', 'GetWSRowColumnCount', 'IsValidWSCell', 'IsValidWSRange'}
        self.assertTrue(all(j['name'] in allowed for j in jobs))
        self.assertTrue(all(j['verification_dimension'] == 'characterization' for j in jobs))
        zero = next(j for j in jobs if j['id'].endswith(':cell_0_0'))
        self.assertEqual(zero['assertions'], [{'path': ['status'], 'equals': 'ok'}])
        self.assertTrue(HOST.evaluate_native(zero, {'status': 'ok', 'function': 'IsValidWSCell', 'result': False})[0])
        preserved = next(j for j in DATA.data_fixtures('old', ['data_worksheet_boundaries'])
                         if j['id'].endswith(':bounds_0_0'))
        self.assertFalse(HOST.evaluate_native(preserved, {'status': 'ok', 'function': 'IsValidWSCell', 'result': False})[0])

    def test_format_ranges_check_every_corner_and_outside_sentinel(self):
        jobs = DATA.data_fixtures('format', ['data_worksheet_format'])
        for setter in ('SetWSCellWrapTextFlag', 'SetWSCellAlignment', 'SetWSCellVertAlignment', 'SetWSTextAngle'):
            mutation_id = 'design:data_worksheet_format:' + setter + '_range'
            reads = [j for j in jobs if mutation_id in j.get('verifies_jobs', [])]
            self.assertEqual({(j['arguments']['row'], j['arguments']['column']) for j in reads},
                             {(2, 2), (2, 3), (3, 2), (3, 3), (5, 5)})
            sentinel = next(j for j in reads if j['arguments']['row'] == 5)
            corner = next(j for j in reads if j['arguments']['row'] == 2)
            self.assertNotEqual(sentinel['assertions'][0]['equals'], corner['assertions'][0]['equals'])
            self.assertFalse(HOST.evaluate_native(sentinel, {'status': 'ok', 'function': sentinel['name'], 'result': corner['assertions'][0]['equals']})[0])

    def test_material_inout_handles_and_resource_identity_are_independently_checked(self):
        jobs = DATA.data_fixtures('material', ['data_materials'])
        for name in ('SetMaterialTexture', 'SetObjMaterialHandle'):
            job = next(j for j in jobs if j.get('name') == name)
            self.assertEqual(job['capture']['path'], ['result', 1])
            self.assertTrue(HOST.evaluate_native(job, {'status': 'ok', 'function': job['name'], 'result': [True, HOST.FIXTURE_UUID]})[0])
            for wrong in ([False, HOST.FIXTURE_UUID], [True, None], [True, 'not-a-uuid'], [1, HOST.FIXTURE_UUID]):
                self.assertFalse(HOST.evaluate_native(job, {'status': 'ok', 'function': job['name'], 'result': wrong})[0])
        identity = next(j for j in jobs if j['id'].endswith(':material_texture_identity'))
        self.assertEqual(identity['name'], 'Index2Name')
        self.assertEqual(identity['assertions'][0]['equals'], 'SDK-Data-Texture-material')

    def test_unassigned_material_nil_and_empty_name_precede_assignment_and_preserve_geometry(self):
        jobs = DATA.data_fixtures('material_state', ['data_materials'])
        results = run_model(jobs, _MaterialModel())
        self.assertEqual(len(results), len(jobs))
        self.assertTrue(all(row[1] for row in results), results[-1])
        labels = {job['id'].split(':')[-1]: i for i, job in enumerate(jobs)}
        for label, expected in [('unassigned_material_handle', None), ('unassigned_material_name', [False, ''])]:
            index = labels[label]
            self.assertLess(index, labels['assign_object_material'])
            self.assertEqual(jobs[index]['assertions'][0]['equals'], expected)
            self.assertEqual(results[index][2]['result'], expected)
            self.assertNotIn('compatibility', results[index][2])
        self.assertEqual(results[-1][2]['result'], [20, 30, 10])

    def test_material_model_detects_false_nil_stale_handles_and_silent_assignment_faults(self):
        jobs = DATA.data_fixtures('material_faults', ['data_materials'])
        for fault, label, error_code in [
                ('unassigned_valid_handle', 'unassigned_material_handle', None),
                ('stale_null_handle', 'unassigned_material_handle', 'SDK_RESULT'),
                ('assignment_noop', 'GetObjMaterialName', None),
                ('assignment_changes_depth', 'material_preserves_dimensions', None)]:
            with self.subTest(fault=fault):
                results = run_model(jobs, _MaterialModel(fault))
                self.assertFalse(results[-1][1])
                self.assertTrue(results[-1][0].endswith(':' + label), results[-1])
                self.assertEqual(results[-1][2].get('code'), error_code)

    def test_opacity_boundaries_and_independent_channels(self):
        jobs = DATA.data_fixtures('opacity', ['data_attributes'])
        pairs = {(j['arguments']['inIsPenOpacityByClass'], j['arguments']['inIsFillOpacityByClass'])
                 for j in jobs if j.get('name') == 'SetOpacityByClassN'}
        self.assertEqual(pairs, {(False, False), (False, True), (True, False), (True, True)})
        values = {j['arguments']['opacity'] for j in jobs if j.get('name') == 'SetOpacity'}
        self.assertEqual(values, {0, 37, 100})
        for job in jobs:
            if job.get('name') == 'GetOpacityN':
                value = job['assertions'][0]['equals']
                self.assertFalse(HOST.evaluate_native(job, {'status': 'ok', 'function': job['name'], 'result': [True, value[2], value[1]]})[0])

    def test_opacity_adapter_preserves_documented_pen_fill_order_and_raw_native_result(self):
        model = _RecordModel()
        model.Rect((0, 1), (1, 0))
        native_set = Mock(return_value=None)
        changed = RUNTIME.invoke('SetOpacityByClassN', {'arguments': {
            'inIsFillOpacityByClass': False, 'h': model.last.uuid,
            'inIsPenOpacityByClass': True}}, native_set, vs_module=model, catalog=CATALOG)
        self.assertEqual(changed['status'], 'ok')
        native_set.assert_called_once_with(model.last, True, False)
        # Preserve the exact tuple returned by a native getter, including the
        # reversed pair seen in build 882075; do not hide it by fixing the oracle.
        native_get = Mock(return_value=(False, True))
        result = RUNTIME.invoke('GetOpacityByClassN', {'arguments': {'h': model.last.uuid}},
                                native_get, vs_module=model, catalog=CATALOG)
        native_get.assert_called_once_with(model.last)
        self.assertEqual(result['result'], [False, True])
        self.assertEqual(result['outputs'], {'isPenOpacityByClass': False, 'isFillOpacityByClass': True})

    def test_calls_remain_pending_and_repeated_builds_do_not_share_mutable_state(self):
        first = DATA.data_fixtures('fresh', ['data_records'])
        second = DATA.data_fixtures('fresh', ['data_records'])
        self.assertEqual(first, second)
        first[0]['assertions'].clear()
        self.assertTrue(second[0]['assertions'])
        self.assertTrue(all(job['native_status'] == 'pending_not_executed' for job in second))
        encoded = json.dumps(self.jobs, allow_nan=False, ensure_ascii=False)
        self.assertIn('Grüße 東京', encoded)
        self.assertNotIn('native_passed', encoded)


if __name__ == '__main__':
    unittest.main()
