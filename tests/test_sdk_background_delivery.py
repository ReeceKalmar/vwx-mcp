"""Delivery verification uses an injected transport and synthetic local files only."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('background_delivery_test', ROOT / 'tools/check_sdk_background_delivery.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
HASHES = {name: 'a' * 64 for name in CHECK.FILES}
VERSION = {'status': 'ok', 'function': 'GetVersionEx', 'result': [32, 0, 0, 2, 882075]}


def scheduler(count=0, **changes):
    value = dict(schema_version=1, scheduler='sdk-named-menu-broker-ack-v4', sdk_version=3200,
                 updated_epoch=1000, process_id=123, timer_active=True, paused=False,
                 queued_jobs=0, pending=False, posts=8 + count, foreground_posts=2, background_posts=6 + count,
                 runner_completions_observed=8 + count, trigger_failures=3, acknowledgment_timeouts=1,
                 runner_stamp=1000 + count, completion_stamp=1000 + count,
                 keyboard_state_modified=False, global_input=False, focus_changed_by_bridge=False,
                 frame_source='GS_GetMainHWND', frame_available=True, frame_has_win32_menu=False,
                 broker_window_available=True, broker_message_pending=False, menu_invocation_active=False,
                 menu_invocations=8 + count, menu_returns=8 + count, broker_rejections=0,
                 menu_return_available=True, last_menu_return=0,
                 menu_caption='VWX Bridge Start')
    value.update(changes)
    return value


class Model:
    def __init__(self, *, bad_at=None, bad_response=None, raise_at=None, final=None, hashes=None):
        self.calls, self.bad_at, self.bad_response, self.raise_at = [], bad_at, bad_response, raise_at
        self.final, self.hashes = final or {}, hashes

    async def send(self, request):
        self.calls.append(copy.deepcopy(request))
        if len(self.calls) == self.raise_at:
            raise TimeoutError('no response')
        if len(self.calls) == self.bad_at:
            return copy.deepcopy(self.bad_response)
        return copy.deepcopy(VERSION)

    def read(self, _):
        return {'ready': True, 'scheduler': scheduler(len(self.calls), **(self.final if self.calls else {}))}

    def hash_reader(self, _):
        return copy.deepcopy(self.hashes if self.hashes is not None and self.calls else HASHES)


class BackgroundDeliveryTests(unittest.TestCase):
    def run_case(self, model=None, *, count=3, **kwargs):
        model = model or Model()
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / 'new-run'
            result = asyncio.run(CHECK.run_delivery(model.send, 'not-a-real-host', output,
                        expected_hashes=HASHES, count=count, hash_reader=model.hash_reader,
                        readiness=model.read, sleep=AsyncMock(), **kwargs))
            persisted = json.loads((output / 'result.json').read_text(encoding='utf-8'))
            self.assertEqual(result, persisted)
            journal = [json.loads(line) for line in (output / 'journal.jsonl').read_text(encoding='utf-8').splitlines()]
            return result, journal, model

    def test_default_100_reads_have_exact_posts_completions_and_no_semantic_credit(self):
        result, journal, model = self.run_case(count=100)
        self.assertEqual(len(model.calls), 100)
        self.assertTrue(all(request == CHECK.REQUEST for request in model.calls))
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(result['background_verified'])
        self.assertEqual(result['completed_reads'], 100)
        self.assertEqual(result['native_functions_passed'], [])
        self.assertFalse(result['native_semantics_fully_verified'])
        self.assertEqual(result['host']['build'], 882075)
        self.assertEqual(result['telemetry_delta'], dict(posts=100, foreground_posts=0, background_posts=100,
                         runner_completions_observed=100, trigger_failures=0, acknowledgment_timeouts=0,
                         menu_invocations=100, menu_returns=100, broker_rejections=0))
        self.assertEqual(sum(e['event'] == 'intent' for e in journal), 100)
        self.assertEqual(sum(e['event'] == 'response' for e in journal), 100)
        self.assertEqual(journal[-1]['event'], 'finished')

    def test_journal_intent_precedes_every_send_and_directory_never_resumes(self):
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / 'fresh'
            model = Model()
            async def send(request):
                entries = [json.loads(line) for line in (output / 'journal.jsonl').read_text().splitlines()]
                self.assertEqual(entries[-1]['event'], 'intent')
                return await model.send(request)
            options = dict(expected_hashes=HASHES, count=1, hash_reader=model.hash_reader, readiness=model.read)
            result = asyncio.run(CHECK.run_delivery(send, 'unused', output, **options))
            before = (output / 'journal.jsonl').read_bytes()
            with self.assertRaises(FileExistsError):
                asyncio.run(CHECK.run_delivery(send, 'unused', output, **options))
            self.assertEqual(len(model.calls), 1)
            self.assertEqual((output / 'journal.jsonl').read_bytes(), before)
            self.assertTrue(result['background_verified'])

    def test_invalid_response_identity_shape_or_compatibility_stops_without_retry(self):
        for bad in [None, [], {}, dict(VERSION, function='GetVersion'), dict(VERSION, result=[32, 0, 0, 2]),
                    dict(VERSION, error=''), dict(VERSION, result=[32, False, 0, 2, 882075]),
                    dict(VERSION, compatibility={}), dict(VERSION, native_dispatched=False),
                    dict(VERSION, dispatched=False), dict(VERSION, result=[31, 0, 0, 2, 882075]),
                    dict(VERSION, result=[32, 0, 0, 1, 882075]), dict(VERSION, result=[32, 0, 0, 2, 0])]:
            with self.subTest(response=bad):
                result, _, model = self.run_case(Model(bad_at=2, bad_response=bad))
                self.assertEqual(result['status'], 'failed')
                self.assertEqual((len(model.calls), result['completed_reads']), (2, 1))
                self.assertFalse(result['background_verified'])

    def test_changed_measured_host_aborts(self):
        result, _, model = self.run_case(Model(bad_at=2, bad_response=dict(VERSION, result=[32, 0, 0, 2, 882076])))
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(result['completed_reads'], 1)
        self.assertIn('host identity changed', result['errors'][0])

    def test_present_dispatch_flags_require_exact_true_boolean(self):
        for key in ('dispatched', 'native_dispatched'):
            for value in (False, None, 0, 1, 'false', 'true', [], {}):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    CHECK.host_identity(dict(VERSION, **{key: value}))
            self.assertEqual(CHECK.host_identity(dict(VERSION, **{key: True}))['build'], 882075)

    def test_unclaimed_is_blocked_and_contradictory_dispatch_is_uncertain(self):
        for contradictory in (False, True):
            response = {'error': 'unclaimed request', 'code': 'VW_JOB_UNCLAIMED', 'dispatched': contradictory}
            result, _, model = self.run_case(Model(bad_at=1, bad_response=response))
            self.assertEqual(result['status'], 'uncertain' if contradictory else 'blocked')
            self.assertEqual((len(model.calls), result['completed_reads']), (1, 0))
            self.assertFalse(result['background_verified'])

    def test_transport_exception_preserves_intent_and_never_retries(self):
        result, journal, model = self.run_case(Model(raise_at=2))
        self.assertEqual(result['status'], 'uncertain')
        self.assertEqual((len(model.calls), result['attempted_reads'], result['completed_reads']), (2, 2, 1))
        self.assertEqual(sum(e['event'] == 'response' for e in journal), 1)
        self.assertIn('no retry', result['errors'][0])
        self.assertIn('source_sha256_after', result)
        self.assertIn('scheduler_after', result)

    def test_cancellation_and_keyboard_interrupt_persist_incomplete_result_before_reraising(self):
        for interruption in (asyncio.CancelledError, KeyboardInterrupt):
            with self.subTest(interruption=interruption), tempfile.TemporaryDirectory() as parent:
                output = Path(parent) / 'interrupted'
                model = Model()
                async def send(request):
                    model.calls.append(copy.deepcopy(request))
                    raise interruption()
                with self.assertRaises(interruption):
                    asyncio.run(CHECK.run_delivery(send, 'unused', output, expected_hashes=HASHES,
                                count=3, hash_reader=model.hash_reader, readiness=model.read))
                result = json.loads((output / 'result.json').read_text(encoding='utf-8'))
                self.assertEqual(result['status'], 'uncertain')
                self.assertEqual((len(model.calls), result['attempted_reads'], result['completed_reads']), (1, 1, 0))
                self.assertFalse(result['background_verified'])
                self.assertEqual(result['native_functions_passed'], [])
                self.assertIn('source_sha256_after', result)
                self.assertIn('scheduler_after', result)
                events = [json.loads(line) for line in (output / 'journal.jsonl').read_text().splitlines()]
                self.assertEqual(sum(e['event'] == 'intent' for e in events), 1)
                self.assertEqual(sum(e['event'] == 'response' for e in events), 0)
                self.assertEqual(events[-1]['event'], 'finished')

    def test_uncertain_transport_response_never_becomes_known_failure_or_retry(self):
        for code in ('VW_DISPATCH_UNCONFIRMED', 'VW_DISPATCH_STUCK', 'VW_UNKNOWN'):
            with self.subTest(code=code):
                result, _, model = self.run_case(Model(bad_at=1, bad_response={'error': 'unknown outcome', 'code': code}))
                self.assertEqual(result['status'], 'uncertain')
                self.assertEqual(len(model.calls), 1)
                self.assertFalse(result['background_verified'])

    def test_source_drift_preserves_successful_responses_but_denies_verification(self):
        changed = dict(HASHES, **{'VwxBridge.vlb': 'b' * 64})
        result, _, _ = self.run_case(Model(hashes=changed))
        self.assertEqual(result['completed_reads'], 3)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['background_verified'])
        self.assertIn('Deployment source drift detected', result['errors'])

    def test_preflight_source_mismatch_sends_nothing(self):
        model = Model()
        model.hash_reader = lambda _: dict(HASHES, **{'sdk_runtime.py': 'b' * 64})
        result, _, _ = self.run_case(model)
        self.assertEqual(model.calls, [])
        self.assertEqual(result['status'], 'failed')

    def test_foreground_posts_fail_even_when_every_request_completed(self):
        result, _, _ = self.run_case(Model(final={'foreground_posts': 3, 'background_posts': 8}))
        self.assertEqual(result['completed_reads'], 3)
        self.assertEqual(result['telemetry_delta']['foreground_posts'], 1)
        self.assertFalse(result['background_verified'])

    def test_changed_process_counter_resets_failures_timeouts_and_extra_posts_fail(self):
        variants = [dict(process_id=999), dict(trigger_failures=4), dict(acknowledgment_timeouts=2),
                    dict(posts=12, background_posts=10), dict(runner_completions_observed=10),
                    dict(posts=3, foreground_posts=0, background_posts=3, runner_completions_observed=3),
                    dict(menu_invocations=12), dict(menu_returns=10), dict(broker_rejections=1)]
        for variant in variants:
            with self.subTest(variant=variant):
                result, _, _ = self.run_case(Model(final=variant))
                self.assertEqual(result['status'], 'failed')
                self.assertFalse(result['background_verified'])

    def test_final_pending_or_queue_or_input_focus_flags_cannot_claim_success(self):
        for changes in [dict(pending=True), dict(queued_jobs=1), dict(keyboard_state_modified=True),
                        dict(focus_changed_by_bridge=True), dict(global_input=True),
                        dict(runner_stamp=9999), dict(modifiers_pending_restore=True),
                        dict(broker_message_pending=True), dict(menu_invocation_active=True)]:
            with self.subTest(changes=changes):
                result, _, _ = self.run_case(Model(final=changes))
                self.assertEqual(result['status'], 'failed')
                self.assertFalse(result['background_verified'])

    def test_incomplete_or_boolean_telemetry_is_rejected(self):
        for key in CHECK.COUNTERS + ('queued_jobs', 'process_id', 'frame_source', 'frame_available',
                                     'broker_window_available', 'broker_message_pending', 'menu_invocation_active',
                                     'menu_return_available', 'frame_has_win32_menu', 'keyboard_state_modified'):
            value = scheduler()
            del value[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                CHECK.validate_scheduler(value)
        for key in CHECK.COUNTERS:
            with self.subTest(boolean=key), self.assertRaises(ValueError):
                CHECK.validate_scheduler(scheduler(**{key: False}))

    def test_v4_accepts_custom_menu_frame_and_rejects_v3_or_incomplete_broker(self):
        CHECK.validate_scheduler(scheduler(frame_has_win32_menu=False))
        CHECK.validate_scheduler(scheduler(frame_has_win32_menu=True))
        for changes in [dict(scheduler='posted-menu-command-ack-v3'), dict(frame_source='EnumWindows'),
                        dict(frame_available=False), dict(broker_window_available=False),
                        dict(frame_has_win32_menu=0), dict(broker_message_pending=0),
                        dict(menu_invocation_active=None), dict(menu_return_available=1)]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                CHECK.validate_scheduler(scheduler(**changes))

    def test_v4_broker_post_invocation_and_return_lifecycle_cannot_disagree(self):
        for changes in [dict(menu_invocations=9), dict(menu_returns=7),
                        dict(menu_invocations=7, menu_returns=7),
                        dict(broker_message_pending=True), dict(menu_invocation_active=True),
                        dict(pending=True, broker_message_pending=True, menu_invocation_active=True),
                        dict(menu_return_available=False), dict(last_menu_return=None),
                        dict(last_menu_return=True), dict(last_menu_return=32768), dict(last_menu_return=-32769)]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                CHECK.validate_scheduler(scheduler(**changes))
        # The SDK's short return code is evidence, not an independently
        # documented success flag; actual typed results and completion decide.
        for code in (-32768, -1, 0, 1, 32767):
            CHECK.validate_scheduler(scheduler(last_menu_return=code))

    def test_fresh_v4_broker_needs_no_prior_menu_return_before_first_request(self):
        fresh = scheduler(posts=0, foreground_posts=0, background_posts=0, runner_completions_observed=0,
                          menu_invocations=0, menu_returns=0, menu_return_available=False)
        del fresh['last_menu_return']
        CHECK.validate_scheduler(fresh)
        with self.assertRaises(ValueError):
            CHECK.validate_scheduler(dict(fresh, last_menu_return=0))

    def test_posted_running_and_returned_v4_requests_remain_pending_until_outer_completion(self):
        before = scheduler()
        posted = scheduler(posts=9, background_posts=7, pending=True, broker_message_pending=True)
        running = dict(posted, broker_message_pending=False, menu_invocation_active=True, menu_invocations=9)
        returned = dict(running, menu_invocation_active=False, menu_returns=9)
        completed = dict(returned, pending=False, runner_completions_observed=9)
        for state in (posted, running, returned):
            CHECK.validate_scheduler(state)
            self.assertTrue(CHECK._busy(state))
            with self.assertRaises(ValueError):
                CHECK.telemetry_delta(before, state, 1)
        self.assertFalse(CHECK._busy(completed))
        self.assertEqual(CHECK.telemetry_delta(before, completed, 1)['menu_returns'], 1)

    def test_v3_preflight_sends_no_request_even_with_complete_old_menu_telemetry(self):
        model = Model()
        model.read = lambda _: {'ready': True, 'scheduler': scheduler(scheduler='posted-menu-command-ack-v3',
                              menu_command_id=914, menu_caption_matches=1, menu_items_inspected=180)}
        result, _, _ = self.run_case(model)
        self.assertEqual(model.calls, [])
        self.assertFalse(result['background_verified'])

    def test_completion_settling_is_bounded_and_does_not_send_extra_calls(self):
        with tempfile.TemporaryDirectory() as parent:
            model = Model()
            observations, sleeps = [], []
            def readiness(_):
                observations.append(len(model.calls))
                if model.calls:
                    return {'ready': False, 'code': 'SETTLING', 'scheduler': scheduler(1, pending=True)}
                return model.read(None)
            async def sleep(seconds):
                sleeps.append(seconds)
            result = asyncio.run(CHECK.run_delivery(model.send, 'unused', Path(parent) / 'new',
                        expected_hashes=HASHES, count=1, hash_reader=model.hash_reader, readiness=readiness, sleep=sleep))
            self.assertEqual(len(model.calls), 1)
            self.assertEqual(len(sleeps), 30)
            self.assertAlmostEqual(sum(sleeps), 3.0)
            self.assertEqual(result['status'], 'failed')
            self.assertIs(result['scheduler_after']['pending'], True)
            self.assertEqual(result['telemetry_delta']['posts'], 1)

    def test_physical_diagnostics_are_fresh_idle_and_read_only(self):
        with tempfile.TemporaryDirectory() as parent:
            ipc = Path(parent) / 'ipc'
            (ipc / 'jobs').mkdir(parents=True)
            path = ipc / 'native.scheduler.json'
            path.write_text(json.dumps(scheduler()), encoding='utf-8')
            (ipc / 'native.alive').write_text('1000 0', encoding='utf-8')
            before = path.read_bytes()
            self.assertTrue(CHECK.read_readiness(parent, now=1001)['ready'])
            self.assertFalse(CHECK.read_readiness(parent, now=1010)['ready'])
            self.assertFalse(CHECK.read_readiness(parent, now=995)['ready'])
            (ipc / 'jobs/leftover.json').write_text('{}', encoding='utf-8')
            self.assertFalse(CHECK.read_readiness(parent, now=1001)['ready'])
            self.assertTrue((ipc / 'jobs/leftover.json').exists())
            self.assertEqual(path.read_bytes(), before)

    def test_all_deployment_files_are_measured_from_correct_locations(self):
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            plugin = root / 'installed' / 'VWX-MCP'
            plugin.mkdir(parents=True)
            for name in CHECK.FILES:
                source = root / ('vwx-plugin' if name in CHECK.PYTHON_FILES else 'native/Output/2027/Release') / name
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(name.encode())
                (plugin if name in CHECK.PYTHON_FILES else plugin.parent).joinpath(name).write_bytes(name.encode())
            self.assertEqual(CHECK.source_hashes(root), CHECK.deployment_hashes(plugin))
            CHECK.validate_hashes(CHECK.deployment_hashes(plugin))

    def test_invalid_count_or_provenance_is_rejected_before_any_directory_or_send(self):
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / 'never-created'
            send = AsyncMock()
            for count in (0, 1001, True, 1.5, '100'):
                with self.subTest(count=count), self.assertRaises(ValueError):
                    asyncio.run(CHECK.run_delivery(send, 'unused', output, expected_hashes=HASHES, count=count))
            for hashes in ({}, dict(HASHES, **{'VwxBridge.vlb': 'x' * 64}), dict(HASHES, unexpected='a' * 64)):
                with self.assertRaises(ValueError):
                    asyncio.run(CHECK.run_delivery(send, 'unused', output, expected_hashes=hashes))
            send.assert_not_awaited()
            self.assertFalse(output.exists())

    def test_cli_requires_explicit_execute_and_uses_default100(self):
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / 'offline'
            with patch.object(CHECK.sys, 'argv', ['check', '--plugin-dir', 'unused', '--output-dir', str(output)]), \
                    patch.object(CHECK, 'execute', new_callable=AsyncMock) as execute:
                self.assertEqual(CHECK.main(), 0)
                execute.assert_not_awaited()
            self.assertEqual(json.loads((output / 'plan.json').read_text())['count'], 100)

    def test_stdio_boundary_forces_background_uncached_and_exact_read_only_tool(self):
        transports, calls, closes = [], [], []
        def transport(*args, **kwargs):
            transports.append((args, kwargs))
            return object()
        class Client:
            def __init__(self, value, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                closes.append(True)
            async def call_tool(self, command, params):
                calls.append((command, params))
                return SimpleNamespace(is_error=False, content=[SimpleNamespace(text=json.dumps(VERSION))])
        async def run(send, plugin, output, **kwargs):
            self.assertEqual(transports, [], 'Client must be lazy until preflight permits the first send')
            self.assertEqual(kwargs['count'], 2)
            self.assertEqual(await send(copy.deepcopy(CHECK.REQUEST)), VERSION)
            self.assertEqual(await send(copy.deepcopy(CHECK.REQUEST)), VERSION)
            with self.assertRaises(ValueError):
                await send({'command': 'execute_script', 'params': {'code': 'forbidden'}})
            return {'status': 'passed'}
        with tempfile.TemporaryDirectory() as plugin, \
                patch.dict(CHECK.sys.modules, {'fastmcp': SimpleNamespace(Client=Client),
                                              'fastmcp.client.transports': SimpleNamespace(StdioTransport=transport)}), \
                patch.object(CHECK, 'source_hashes', return_value=HASHES), \
                patch.object(CHECK, 'run_delivery', side_effect=run):
            result = asyncio.run(CHECK.execute(plugin, 'unused', count=2, timeout=45, python='fixture-python'))
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(len(transports), 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(closes, [True])
        args, options = transports[0]
        self.assertEqual(args[0], 'fixture-python')
        self.assertTrue(args[1][0].endswith('vwx_mcp_server.py'))
        for key, value in {'VWX_BACKGROUND_MODE': '1', 'VWX_CACHE_TTL': '0', 'VWX_TRANSPORT': 'file',
                           'VWX_VW_VERSION': '2027', 'VWX_SDK_TOOLS': '0'}.items():
            self.assertEqual(options['env'][key], value)

    def test_preflight_not_ready_sends_nothing(self):
        model = Model()
        model.read = lambda _: {'ready': False, 'code': 'NOT_READY', 'error': 'stale heartbeat'}
        result, _, _ = self.run_case(model)
        self.assertEqual(model.calls, [])
        self.assertEqual(result['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
