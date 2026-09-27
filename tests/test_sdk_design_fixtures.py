"""Meaningful offline checks for curated fixtures; no Vectorworks connection."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = r'C:\SDK-tests\VWX-MCP-SDK-TEST-design-offline.vwx'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DESIGN = load('sdk_design_fixtures_test', ROOT / 'tools/sdk_design_fixtures.py')
RUNNER = load('sdk_design_runner_test', ROOT / 'tools/sdk_design_runner.py')
POLICY = load('sdk_design_background_policy_test', ROOT / 'mcp-server/background_policy.py')
HOST = DESIGN.HOST
RUNTIME = HOST._load_runtime(ROOT)
CATALOG = json.loads((ROOT / 'vwx-plugin/sdk_catalog.json').read_text(encoding='utf-8'))
INDEX = json.loads((ROOT / 'vwx-plugin/vs_index.json').read_text(encoding='utf-8'))
with patch.dict(sys.modules, {'sdk_runtime': RUNTIME}):
    SEQUENCES = load('sdk_design_sequences_test', ROOT / 'vwx-plugin/sdk_sequences.py')


class _LineModel:
    """Independent mutable line model, exercising real adapter and sequence code."""
    def __init__(self, ignore_endpoint=False):
        self.point, self.line = None, None
        self.ignore_endpoint = ignore_endpoint
        self.calls = []

    def GetVersion(self):
        return (32, 0, 0, 2)

    def GetFPathName(self):
        return DOCUMENT

    def MoveTo(self, p):
        self.calls.append('MoveTo')
        self.point = list(p)

    def LineTo(self, p):
        self.calls.append('LineTo')
        self.line = SimpleNamespace(start=self.point[:], end=list(p))
        self.point = list(p)

    def LNewObj(self):
        return self.line

    def GetObjectUuid(self, h):
        assert h is self.line
        return HOST.FIXTURE_UUID

    def GetObjectByUuid(self, value):
        assert value == HOST.FIXTURE_UUID
        return self.line

    def GetTypeN(self, h):
        return 2 if h is self.line else 0

    def GetSegPt1(self, h):
        return tuple(h.start)

    def GetSegPt2(self, h):
        return tuple(h.end)

    def HLength(self, h):
        return math.hypot(h.end[0] - h.start[0], h.end[1] - h.start[1])

    def SetSegPt1(self, h, p):
        self.calls.append('SetSegPt1')
        h.start = list(p)

    def SetSegPt2(self, h, p):
        self.calls.append('SetSegPt2')
        if not self.ignore_endpoint:
            h.end = list(p)


def _sender(model, seen):
    def send(request):
        seen.append(copy.deepcopy(request))
        command, params = request['command'], request['params']
        assert command in {'sdk_call', 'sdk_sequence'}
        error = POLICY.check(command, params, sdk_catalog=CATALOG['functions'])
        assert error is None, error
        if command == 'sdk_sequence':
            return SEQUENCES.run(params, vs_module=model, catalog=CATALOG)
        return RUNTIME.invoke(params['name'], {'arguments': params['arguments']}, vs_module=model, catalog=CATALOG)
    return send


class SDKDesignFixtureTests(unittest.TestCase):
    def test_fixture_names_preserve_short_names_and_long_identity_without_native_truncation(self):
        self.assertEqual(DESIGN.fixture_name('SDK-Test-', 'short'), 'SDK-Test-short')
        run_a, run_b = 'x' * 79 + 'a', 'x' * 79 + 'b'
        names = [DESIGN.fixture_name(prefix, run) for prefix in ('SDK-A-', 'SDK-B-') for run in (run_a, run_b)]
        self.assertEqual(len(set(names)), 4)
        self.assertTrue(all(len(name) == 60 and name.isascii() for name in names))
        self.assertEqual(names[0], DESIGN.fixture_name('SDK-A-', run_a))
        for prefix, run in (('', 'a'), ('SDK-', ''), (None, 'a'), ('SDK-', 1), ('SDK-', '\u00e9')):
            with self.subTest(prefix=prefix, run=run), self.assertRaises(ValueError):
                DESIGN.fixture_name(prefix, run)

    @classmethod
    def setUpClass(cls):
        cls.plan = DESIGN.build_plan(DOCUMENT, run_id='offline')

    def job(self, suffix):
        return next(job for job in self.plan['jobs'] if job['id'] == 'design:' + suffix)

    def test_all_curated_inputs_match_independent_index_and_runtime(self):
        names, captures = set(), {}
        for job in self.plan['jobs']:
            self.assertEqual(job['native_status'], 'pending_not_executed')
            self.assertTrue(job['assertions'])
            self.assertNotIn('code', job)
            for call in job.get('calls', [job]):
                name = call['name']
                names.add(name)
                self.assertEqual(set(call['arguments']), set(INDEX[name]['args']), job['id'])
                arguments = HOST._substitute(call['arguments'], captures)
                result = RUNTIME.validate(name, {'arguments': arguments}, catalog=CATALOG,
                            invocation_context={'sequence': True},
                            reference_validator=lambda value, _: isinstance(value, dict) and '$ref' in value)
                self.assertNotIn('error', result, (job['id'], result))
                context = CATALOG['functions'][name]['context']
                self.assertFalse(context['interactive'], name)
                self.assertFalse(context['quarantined'], name)
                self.assertFalse(context['unsupported_reason'], name)
            request = RUNNER.render_typed_job(job, captures)
            self.assertIn(request['command'], ('sdk_call', 'sdk_sequence'))
            self.assertIsNone(POLICY.check(request['command'], request['params'], sdk_catalog=CATALOG['functions']))
            self.assertNotIn('code', request['params'])
            if 'capture' in job:
                self.assertNotIn(job['capture']['name'], captures)
                captures[job['capture']['name']] = HOST.FIXTURE_UUID
        self.assertGreaterEqual(len(names), 100)
        self.assertEqual(len(names), self.plan['summary']['native_apis_with_designed_fixture'])
        self.assertEqual(len(self.plan['jobs']), self.plan['summary']['native_cases'])
        self.assertFalse(names & {'HArea', 'UprString', 'DoMenuTextByName', 'SetPref', 'SetPrefReal',
                                  'Save', 'Open', 'Close', 'DelObject', 'RunScript', 'RunScriptN'})

    def test_each_family_can_run_independently_without_cross_family_captures(self):
        for family in DESIGN.FAMILIES:
            captures = {}
            for job in DESIGN.design_fixtures('independent', [family]):
                self.assertEqual(job['fixture_family'], family)
                HOST._substitute(job.get('calls', job.get('arguments')), captures)
                if 'capture' in job:
                    captures[job['capture']['name']] = HOST.FIXTURE_UUID
        for families in ([], ['unknown'], ['line', 'line']):
            with self.assertRaises(ValueError):
                DESIGN.design_fixtures('test', families)
        for value in ('', '../run', "quote'", 'x' * 81, None):
            with self.assertRaises(ValueError):
                DESIGN.design_fixtures(value)

    def test_mutations_have_independent_later_semantic_readback_jobs(self):
        jobs = self.plan['jobs']
        indices = {job['id']: index for index, job in enumerate(jobs)}
        self.assertEqual(len(indices), len(jobs), 'Case IDs must be unique for audit records')
        verified = set()
        for job in jobs:
            for mutation in job.get('verifies_jobs', []):
                self.assertEqual(job['phase'], 'readback')
                self.assertLess(indices[mutation], indices[job['id']])
                self.assertNotEqual(jobs[indices[mutation]]['phase'], 'readback')
                verified.add(mutation)
        mutations = {job['id'] for job in jobs if job['phase'] == 'mutation'}
        self.assertEqual(mutations - verified, set(), 'No setter gets semantic credit from its own return value')

    def test_rectangle_and_polygon_oracles_follow_independent_geometry(self):
        rectangle = self.job('attributes:create_attributes_rect')['calls'][0]['arguments']
        left, top = rectangle['p1']
        right, bottom = rectangle['p2']
        self.assertEqual(self.job('attributes:HAreaN')['assertions'][0]['equals'], (right-left)*(top-bottom))
        self.assertEqual(self.job('attributes:HPerim')['assertions'][0]['equals'], 2*((right-left)+(top-bottom)))
        points = [call['arguments']['p'] for call in self.job('polygon:create_triangle')['calls'] if call['name'] == 'AddPoint']

        def shoelace(vertices):
            return abs(sum(a[0]*b[1] - b[0]*a[1] for a, b in zip(vertices, vertices[1:]+vertices[:1]))) / 2

        self.assertEqual(self.job('polygon:HAreaN')['assertions'][0]['equals'], shoelace(points))
        changed = self.job('polygon:SetPolyPt')['arguments']
        points[changed['index'] - 1] = [changed['xR'], changed['yR']]
        self.assertEqual(self.job('polygon:area_after_vertex_move')['assertions'][0]['equals'], shoelace(points))
        self.assertEqual(self.job('polygon:area_after_remove')['assertions'][0]['equals'], shoelace(points))

    def test_substantive_oracles_reject_silent_noop_and_wrong_native_type(self):
        for suffix in ('attributes:SetOpacityN', 'attributes:HAreaN', 'polygon:changed_vertex',
                       'text:change_text_read', 'worksheet:GetWSCellValue', 'resources:IsMaterialSimple'):
            job = self.job(suffix)
            expected = job['assertions'][0]['equals']
            self.assertTrue(HOST.evaluate_native(job, {'status': 'ok', 'function': job['name'], 'result': expected})[0])
            self.assertFalse(HOST.evaluate_native(job, {'status': 'ok', 'function': job['name'], 'result': 'wrong/no-op'})[0])
        area = self.job('attributes:HAreaN')
        self.assertFalse(HOST.evaluate_native(area, {'status': 'ok', 'function': area['name'], 'result': True})[0])

    def test_real_adapter_and_sequence_with_line_model_execute_separate_jobs(self):
        plan = dict(self.plan, jobs=DESIGN.design_fixtures('offline', ['line']))
        model, seen = _LineModel(), []
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / 'line.jsonl'
            result = DESIGN.run_plan(_sender(model, seen), plan, journal, deployed_source_hashes=lambda: plan['source_sha256'])
            events = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(len(seen), 2 * len(plan['jobs']))
        self.assertEqual(result['captures']['line'], HOST.FIXTURE_UUID)
        self.assertEqual(model.line.start, [10, 10])
        self.assertEqual(model.line.end, [40, 50])
        self.assertEqual(sum(event['event'] == 'intent' for event in events), 2 * len(plan['jobs']))
        self.assertTrue(all(request['command'] in {'sdk_call', 'sdk_sequence'} for request in seen))
        self.assertIn('HLength', result['native_functions_passed'])
        self.assertEqual(result['adapter_functions_passed'], [])

    def test_silent_setter_noop_fails_later_read_and_stops_without_replay(self):
        plan = dict(self.plan, jobs=DESIGN.design_fixtures('offline', ['line']))
        model, seen = _LineModel(ignore_endpoint=True), []
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / 'broken.jsonl'
            result = DESIGN.run_plan(_sender(model, seen), plan, journal, deployed_source_hashes=lambda: plan['source_sha256'])
            before = len(seen)
            with self.assertRaises(FileExistsError):
                DESIGN.run_plan(_sender(model, seen), plan, journal, deployed_source_hashes=lambda: plan['source_sha256'])
            self.assertEqual(len(seen), before)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['records'][-1]['id'], 'design:line:end_after_move')
        self.assertFalse(result['records'][-1]['passed'])
        self.assertEqual(model.calls.count('SetSegPt2'), 1)
        self.assertLess(len(seen), 2 * len(plan['jobs']))

    def test_exact_document_guard_precedes_object_creation(self):
        model, seen = _LineModel(), []
        model.GetFPathName = lambda: r'C:\Client\VWX-MCP-SDK-TEST-design-offline.vwx'
        plan = dict(self.plan, jobs=DESIGN.design_fixtures('offline', ['line']))
        with tempfile.TemporaryDirectory() as directory:
            result = DESIGN.run_plan(_sender(model, seen), plan, Path(directory) / 'wrong-doc.jsonl',
                                     deployed_source_hashes=lambda: plan['source_sha256'])
        self.assertEqual(result['status'], 'failed')
        self.assertIn('Exact disposable document', result['error'])
        self.assertEqual(len(seen), 1)
        self.assertFalse(model.calls)
        self.assertIsNone(model.line)

    def test_plan_counts_keep_unprovided_native_functions_pending(self):
        self.assertEqual(self.plan['summary']['adapter_cases'], 0)
        self.assertEqual(self.plan['summary']['adapter_jobs'], 0)
        pending = self.plan['summary']['native_apis_without_fixture']
        self.assertEqual(pending + self.plan['summary']['native_apis_with_designed_fixture'], len(CATALOG['functions']))
        self.assertGreater(pending, 0)
        for entry in self.plan['functions'].values():
            self.assertEqual(entry['native_status'], 'pending_not_executed')
            self.assertFalse(entry['semantic_verification'])
        self.assertEqual(self.plan['functions']['UprString']['native_case_ids'], [])
        self.assertTrue(self.plan['source_sha256']['sdk_sequences.py'])


if __name__ == '__main__':
    unittest.main()
