"""Availability must never be confused with successful native execution."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('sdk_presence_test', ROOT / 'tools/check_sdk_host_presence.py')
PRESENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PRESENCE)


def load_tool(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUITE = load_tool('presence_suite_tests', 'sdk_regression_suite.py')
with patch.dict(sys.modules, {'sdk_regression_suite': SUITE}):
    REGRESSION = load_tool('presence_regression_tests', 'run_sdk_regression.py')


class FakeClient:
    """A protocol peer with fault injection, never an SDK implementation."""
    def __init__(self, fixture):
        self.fixture = fixture

    async def __aenter__(self):
        if self.fixture.connect_error is not None:
            raise self.fixture.connect_error
        return self

    async def __aexit__(self, *error):
        self.fixture.on_close()
        return False

    async def call_tool(self, tool, arguments):
        fixture = self.fixture
        fixture.calls.append((tool, copy.deepcopy(arguments)))
        ordinal = len(fixture.calls)
        if ordinal == fixture.fail_at:
            raise fixture.failure
        if tool == 'sdk_call':
            if arguments != {'name': 'GetVersionEx', 'arguments': {}}:
                raise AssertionError('Only host provenance may invoke an SDK API')
            response = fixture.host_response
        elif tool == 'sdk_list':
            if set(arguments) != {'offset', 'limit', 'include_presence'} or arguments['include_presence'] is not True:
                raise AssertionError('Presence requests must be exact typed discovery')
            offset, limit = arguments['offset'], arguments['limit']
            response = {'sdk_version': 3200, 'total': len(fixture.names), 'offset': offset,
                        'functions': copy.deepcopy(fixture.entries[offset:offset + limit])}
            if ordinal == fixture.malformed_at:
                response['functions'].reverse()
        else:
            raise AssertionError('Unexpected tool ' + tool)
        fixture.on_response(ordinal)
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(response))])


class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.names = ['Abs', 'Arc', 'Text']
        self.page = {'sdk_version': 3200, 'total': 3, 'offset': 0,
                     'functions': [{'name': 'Abs', 'host_callable': True},
                                   {'name': 'Arc', 'host_callable': False}]}

    def test_complete_known_and_failed_inspections_are_separate_from_semantics(self):
        first = PRESENCE.validate_page(self.page, self.names, 0, 2)
        page = {'sdk_version': 3200, 'total': 3, 'offset': 2,
                'functions': [{'name': 'Text', 'host_callable': None, 'host_inspection_error': 'lookup failed'}]}
        last = PRESENCE.validate_page(page, self.names, 2, 2)
        summary = PRESENCE.summarize(first + last, self.names)
        self.assertEqual(summary['host_callable'], ['Abs'])
        self.assertEqual(summary['host_missing_or_noncallable'], ['Arc'])
        self.assertEqual(summary['host_inspection_failed'], ['Text'])
        self.assertFalse(summary['native_semantic_coverage_credit'])

    def test_rejects_missing_duplicate_reordered_unknown_and_extra_names(self):
        for names in (['Abs'], ['Abs', 'Abs'], ['Arc', 'Abs'], ['Abs', 'Missing'], ['Abs', 'Arc', 'Text']):
            page = dict(self.page, functions=[{'name': name, 'host_callable': True} for name in names])
            with self.subTest(names=names), self.assertRaises(ValueError):
                PRESENCE.validate_page(page, self.names, 0, 2)

    def test_rejects_false_success_shapes_and_bad_pagination(self):
        for changes in ({'error': 'transport'}, {'sdk_version': 3100}, {'sdk_version': 3200.0}, {'offset': False}, {'offset': 1},
                        {'total': True}, {'total': 2}, {'functions': None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                PRESENCE.validate_page(dict(self.page, **changes), self.names, 0, 2)
        for item in ({'name': 'Abs'}, {'name': 'Abs', 'host_callable': 1},
                     {'name': 'Abs', 'host_callable': None},
                     {'name': 'Abs', 'host_callable': True, 'host_inspection_error': 'failed'}):
            page = copy.deepcopy(self.page)
            page['functions'][0] = item
            with self.subTest(item=item), self.assertRaises(ValueError):
                PRESENCE.validate_page(page, self.names, 0, 2)

    def test_partial_inspection_cannot_report_complete_coverage(self):
        with self.assertRaises(ValueError):
            PRESENCE.summarize(self.page['functions'], self.names)


class PresenceExecutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='vwx-presence-offline-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.source = self.directory / 'source'
        source_plugin = self.source / 'vwx-plugin'
        source_plugin.mkdir(parents=True)
        self.plugin = self.directory / 'installed'
        self.plugin.mkdir()
        for filename in PRESENCE.PYTHON_FILES:
            data = ('offline source: ' + filename).encode('utf-8')
            (source_plugin / filename).write_bytes(data)
            (self.plugin / filename).write_bytes(data)
        self.names = ['Abs', 'Arc', 'Text']
        (source_plugin / 'vs_index.json').write_text(json.dumps(dict.fromkeys(self.names, {})), encoding='utf-8')
        (self.plugin / 'vs_index.json').write_bytes((source_plugin / 'vs_index.json').read_bytes())
        self.entries = [{'name': 'Abs', 'host_callable': True}, {'name': 'Arc', 'host_callable': False},
                        {'name': 'Text', 'host_callable': None, 'host_inspection_error': 'lookup unavailable'}]
        self.output = self.directory / 'observations'
        self.calls = []
        self.host_response = {'status': 'ok', 'function': 'GetVersionEx', 'result': [32, 0, 0, 2, 882075]}
        self.connect_error = None
        self.fail_at = None
        self.failure = RuntimeError('transport interrupted')
        self.malformed_at = None
        self.on_close = lambda: None
        self.on_response = lambda ordinal: None
        self.client_factory = Mock(return_value=FakeClient(self))
        self.transport_factory = Mock(return_value=object())
        self.settle = AsyncMock(return_value={'ready': True})
        self.modules = {'fastmcp': SimpleNamespace(Client=self.client_factory),
                        'fastmcp.client.transports': SimpleNamespace(StdioTransport=self.transport_factory),
                        'run_sdk_regression': REGRESSION,
                        'run_sdk_regression_batch': SimpleNamespace(bridge_readiness=Mock(), settle_readiness=self.settle)}

    def execute(self):
        with patch.object(PRESENCE, 'ROOT', self.source), patch.dict(sys.modules, self.modules):
            return asyncio.run(PRESENCE.execute(self.plugin, self.output, page_size=2))

    def saved(self, filename='result.json'):
        return json.loads((self.output / filename).read_text(encoding='utf-8'))

    def change_deployment(self):
        (self.plugin / 'sdk_runtime.py').write_bytes(b'changed while inspection was outstanding')

    def assert_incomplete(self, count):
        result = self.saved()
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(len(result['entries']), count)
        self.assertFalse(result['native_semantic_coverage_credit'])
        self.assertNotIn('summary', result)
        return result

    def test_executes_only_identity_and_discovery_and_separates_unknown_presence(self):
        result = self.execute()
        self.assertEqual(result['status'], 'inspection_complete')
        self.assertEqual(result['entries'], self.entries)
        self.assertEqual(result['host']['build'], 882075)
        self.assertEqual(result['summary']['host_callable'], ['Abs'])
        self.assertEqual(result['summary']['host_missing_or_noncallable'], ['Arc'])
        self.assertEqual(result['summary']['host_inspection_failed'], ['Text'])
        self.assertFalse(result['summary']['native_semantic_coverage_credit'])
        self.assertEqual([name for name, _ in self.calls], ['sdk_call', 'sdk_list', 'sdk_list'])
        self.assertEqual([args['offset'] for tool, args in self.calls if tool == 'sdk_list'], [0, 2])
        env = self.transport_factory.call_args.kwargs['env']
        self.assertEqual((env['VWX_BACKGROUND_MODE'], env['VWX_CACHE_TTL'], env['VWX_TRANSPORT']), ('1', '0', 'file'))
        self.assertEqual(self.saved(), result)

    def test_deployment_change_during_last_page_preserves_raw_response_without_credit(self):
        self.on_response = lambda ordinal: self.change_deployment() if ordinal == 3 else None
        with self.assertRaisesRegex(ValueError, 'Deployment changed'):
            self.execute()
        self.assert_incomplete(2)
        self.assertEqual(self.saved('page-0002-response.json')['functions'], self.entries[2:])
        self.assertEqual(len(self.calls), 3)

    def test_deployment_change_while_client_closes_cannot_report_complete(self):
        self.on_close = self.change_deployment
        with self.assertRaisesRegex(ValueError, 'Deployment changed'):
            self.execute()
        self.assert_incomplete(3)
        self.assertEqual(len(self.calls), 3)

    def test_deployment_change_during_provenance_stops_before_discovery(self):
        self.on_response = lambda ordinal: self.change_deployment() if ordinal == 1 else None
        with self.assertRaisesRegex(ValueError, 'Deployment changed'):
            self.execute()
        self.assert_incomplete(0)
        self.assertEqual(self.calls, [('sdk_call', {'name': 'GetVersionEx', 'arguments': {}})])
        self.assertEqual(self.saved('host-response.json'), self.host_response)

    def test_transport_failure_preserves_accepted_pages_without_retry_or_resume(self):
        self.fail_at = 3
        with self.assertRaisesRegex(RuntimeError, 'transport interrupted'):
            self.execute()
        result = self.assert_incomplete(2)
        self.assertEqual(len(self.calls), 3)
        self.assertTrue((self.output / 'page-0002-intent.json').exists())
        self.assertFalse((self.output / 'page-0002-response.json').exists())
        with self.assertRaises(FileExistsError):
            self.execute()
        self.assertEqual(self.saved(), result)
        self.assertEqual(len(self.calls), 3)

    def test_cancellation_is_recorded_as_incomplete_and_propagated_without_retry(self):
        self.fail_at = 3
        self.failure = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            self.execute()
        result = self.assert_incomplete(2)
        self.assertEqual(result['error'], 'CancelledError')
        self.assertEqual(len(self.calls), 3)

    def test_malformed_page_or_wrong_host_identity_cannot_report_availability(self):
        self.malformed_at = 2
        with self.assertRaisesRegex(ValueError, 'reordered'):
            self.execute()
        self.assert_incomplete(0)
        self.assertEqual(len(self.calls), 2)
        self.output = self.directory / 'other-observations'
        self.calls.clear()
        self.host_response['function'] = 'GetVersion'
        with self.assertRaisesRegex(ValueError, 'provenance'):
            self.execute()
        self.assert_incomplete(0)
        self.assertEqual(len(self.calls), 1)

    def test_blocked_readiness_or_client_failure_records_incomplete_without_discovery(self):
        self.settle.return_value = {'ready': False, 'error': 'pending trigger'}
        with self.assertRaisesRegex(ValueError, 'Bridge is not idle'):
            self.execute()
        self.assert_incomplete(0)
        self.client_factory.assert_not_called()
        self.transport_factory.assert_not_called()
        self.output = self.directory / 'connection-failure'
        self.settle.return_value = {'ready': True}
        self.connect_error = RuntimeError('client failed to connect')
        with self.assertRaisesRegex(RuntimeError, 'failed to connect'):
            self.execute()
        self.assert_incomplete(0)
        self.assertEqual(self.calls, [])

    def test_initial_deployment_mismatch_never_connects_or_publishes_intent(self):
        self.change_deployment()
        with self.assertRaisesRegex(ValueError, 'Deploy matching'):
            self.execute()
        self.client_factory.assert_not_called()
        self.transport_factory.assert_not_called()
        self.settle.assert_not_awaited()
        self.assertFalse((self.output / 'intent.json').exists())

    def test_landscape_companion_drift_prevents_host_connection(self):
        for name in ('project_guard.py', 'landscape_takeoff.py'):
            with self.subTest(name=name):
                self.output = self.directory / ('drift-' + name)
                path = self.plugin / name
                original = path.read_bytes()
                path.write_bytes(b'outdated companion')
                try:
                    with self.assertRaisesRegex(ValueError, 'Deploy matching'):
                        self.execute()
                finally:
                    path.write_bytes(original)
                self.client_factory.assert_not_called()
                self.transport_factory.assert_not_called()
                self.assertFalse((self.output / 'intent.json').exists())


if __name__ == '__main__':
    unittest.main()
