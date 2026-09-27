"""SDK-wide offline binding and runtime contract checks.

These tests never connect to Vectorworks. The old, independently generated SDK
index is the argument-order oracle. Fakes test adapter behavior only; the matrix
keeps unmeasured native APIs pending and imports only explicitly recorded cases.
"""
import importlib.util
import inspect
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "vwx-plugin"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # Dataclasses and some import helpers consult sys.modules during execution.
    with patch.dict(sys.modules, {name: module}):
        spec.loader.exec_module(module)
    return module


MATRIX = load_module("sdk_test_matrix", ROOT / "tools/sdk_test_matrix.py")


class SignatureBoundAPI(ModuleType):
    """Fake SDK with independently indexed signatures and recorded call order."""
    def __init__(self, index):
        super().__init__("vs")
        self.index = index
        self.calls = []
        self.result = None

    def __getattr__(self, name):
        if name not in self.index:
            raise AttributeError(name)
        signature = inspect.Signature([
            inspect.Parameter(argument, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            for argument in self.index[name]["args"]])

        def call(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            self.calls.append((name, tuple(bound.arguments.values())))
            return self.result
        return call


class FakeHandle:
    def __init__(self, uuid):
        self.uuid = uuid


class FakeHost:
    """Resolver/version fixtures used only by the Python adapter."""
    def __init__(self):
        self.handles = {}

    def GetVersion(self):
        return (32, 0, 0, 2)  # Platform code; application/SDK builds are separate.

    def GetObjectByUuid(self, uuid):
        return self.handles.get(uuid)

    def GetObjectUuid(self, handle):
        return handle.uuid if isinstance(handle, FakeHandle) else ""

    def GetTypeN(self, handle):
        return 3 if isinstance(handle, FakeHandle) else 0


def type_name(parameter):
    return " ".join(parameter.get("type", "UNKNOWN").upper().split())


def invalid_values(parameter, function):
    """Deliberate mutations of the public transport contract, not native calls."""
    kind = type_name(parameter)
    if kind == "BOOLEAN":
        return [0, "true", None]
    if kind in {"INTEGER", "LONGINT", "TEXTSTYLE"}:
        bounds = {"INTEGER": (-32768, 32767), "LONGINT": (-2147483648, 2147483647),
                  "TEXTSTYLE": (0, 31)}
        low, high = bounds[kind]
        return [True, 1.5, "1", low - 1, high + 1]
    if kind == "REAL":
        return [True, None, "1", float("nan"), float("inf")]
    if kind == "CHAR":
        return ["", "two", 5]
    if kind in {"STRING", "DYNARRAY[] OF CHAR", "CRITERIA"}:
        return [None, 5, ["text"]]
    if kind in {"POINT", "POINT3D", "VECTOR", "COLOR"}:
        size = 2 if kind == "POINT" else 3
        invalid = [[], [0] * (size + 1), [True] + [0] * (size - 1)]
        if kind == "COLOR":
            invalid += [[-1, 0, 0], [65536, 0, 0]]
        else:
            invalid += [[float("inf")] + [0] * (size - 1)]
        return invalid
    if kind == "HANDLE":
        values = ["invalid UUID", "00000000-0000-0000-0000-000000000000",
                  "ffffffff-ffff-ffff-ffff-ffffffffffff"]
        if (function, parameter["name"]) != ("BeginGroupN", "groupHandle"):
            values += [None]
        return values
    if kind == "PROCEDURE":
        return [{"mode": "eval"}, {"mode": "collect", "limit": 0}]
    if kind == "ARRAY":
        return [{}, [float("nan")]]
    if kind == "ANY":
        return [object(), {"nested": float("inf")}]
    return []


def valid_boundaries(parameter):
    kind = type_name(parameter)
    if kind == "BOOLEAN":
        return [False, True]
    if kind in {"INTEGER", "LONGINT", "TEXTSTYLE"}:
        return {"INTEGER": [-32768, 0, 32767],
                "LONGINT": [-2147483648, 0, 2147483647],
                "TEXTSTYLE": [0, 31]}[kind]
    if kind == "REAL":
        return [-1.25, 0.0, 1.0e308]
    if kind in {"STRING", "DYNARRAY[] OF CHAR", "CRITERIA"}:
        return ["", "Unicode: é / 雪"]
    if kind == "CHAR":
        return ["A", "é"]
    if kind in {"POINT", "POINT3D", "VECTOR"}:
        size = 2 if kind == "POINT" else 3
        return [[0] * size, [-1.25] * size]
    if kind == "COLOR":
        return [[0, 0, 0], [65535, 65535, 65535]]
    return []


class SDKMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads((PLUGIN / "vs_index.json").read_text(encoding="utf-8"))
        cls.catalog = json.loads((PLUGIN / "sdk_catalog.json").read_text(encoding="utf-8"))
        cls.native = SignatureBoundAPI(cls.index)
        with patch.dict(sys.modules, {"vs": cls.native}):
            cls.runtime = load_module("sdk_runtime", PLUGIN / "sdk_runtime.py")
        with patch.dict(sys.modules, {"vs": cls.native, "sdk_runtime": cls.runtime}):
            cls.generated = load_module("sdk_generated", PLUGIN / "sdk_generated.py")
        cls.real_invoke = staticmethod(cls.runtime.invoke)
        cls.host = FakeHost()

    def setUp(self):
        self.native.calls.clear()
        self.native.result = None

    def invoke(self, name, params):
        def relay(function_name, payload, call=None, **kwargs):
            return self.real_invoke(function_name, payload, call,
                                    vs_module=self.host, catalog=self.catalog, **kwargs)
        with patch.object(self.runtime, "invoke", side_effect=relay):
            return getattr(self.generated, "sdk_" + name)(params)

    def value(self, parameter, ordinal=1, function="", output=False):
        kind = type_name(parameter)
        if output and function == 'GetObjMaterialName':
            if kind == 'BOOLEAN':
                return False
            if kind == 'STRING':
                return ''
        if kind == "HANDLE":
            uuid = "12345678-1234-4321-8765-%012d" % ordinal
            handle = self.host.handles.setdefault(uuid, FakeHandle(uuid))
            return handle if output else uuid
        if kind == "BOOLEAN":
            return bool(ordinal % 2)
        if kind in {"INTEGER", "LONGINT", "TEXTSTYLE"}:
            return ordinal % 20 + 1
        if kind == "REAL":
            return ordinal + 0.25
        if kind == "CHAR":
            return "é"
        if kind in {"STRING", "DYNARRAY[] OF CHAR", "CRITERIA"}:
            if function == 'UprString':
                return 'fixture_%d_ascii' % ordinal
            return "fixture_%d_é" % ordinal
        if kind in {"POINT", "POINT3D", "VECTOR"}:
            size = 2 if kind == "POINT" else 3
            return [ordinal + offset + 0.25 for offset in range(size)]
        if kind == "COLOR":
            return [ordinal, 1234, 65535]
        if kind == "PROCEDURE":
            mode = self.catalog['functions'][function].get('callback_contract', {}).get('mode', 'collect')
            descriptor = {'mode': mode, 'limit': 2}
            descriptor.update({'filter': {'object_types': [3]}, 'conflict': {'action': 'skip'},
                               'dialog': {'events': {}}}.get(mode, {}))
            return descriptor
        if kind == "ARRAY":
            if function == "SetListBoxTabStops":
                return [10, 20]
            if parameter.get("name") == "arrOptions":
                return ["category", "setting", "label"]
            return ["first", "second"]
        if kind == "ANY":
            return {"fixture": [ordinal, "value"]}
        raise AssertionError("No independent fixture for SDK type " + kind)

    def prepare(self, name):
        entry = self.catalog["functions"][name]
        arguments = {p["name"]: self.value(p, i + 1, name)
                     for i, p in enumerate(entry["parameters"])}
        returns = entry["returns"]
        if returns["kind"] == "void":
            self.native.result = None
        elif returns["kind"] == "scalar":
            self.native.result = self.value(returns, 500, name, output=True)
        else:
            self.native.result = tuple(self.value(p, i + 500, name, output=True)
                                       for i, p in enumerate(returns["items"]))
        self.native.calls.clear()
        return entry, arguments

    def expected_block(self, name, entry):
        context = entry.get("context", {})
        if context.get("unsupported_reason"):
            return "SDK_UNSUPPORTED"
        if (context.get("required_host_context") or context.get("requires_sequence")
                or context.get("quarantined") or name in {"Layer", "CombineIntoSurface"}):
            return "SDK_CONTEXT"
        for parameter in entry["parameters"]:
            kind = type_name(parameter)
            if kind == "PROCEDURE" and name not in {
                    "ForEachObject", "ForEachObjectInLayer", "ForEachObjectAtPoint"} and not entry.get('callback_contract'):
                return "SDK_UNSUPPORTED"
            if kind == "ANY" and any(token in parameter["name"].lower()
                                     for token in ("ptr", "pointer", "cstr")):
                return "SDK_UNSUPPORTED"
        return None

    def assert_call_mapping(self, name, entry, arguments):
        self.assertEqual(len(self.native.calls), 1)
        actual_name, actual = self.native.calls[0]
        self.assertEqual(actual_name, name)
        self.assertEqual(len(actual), len(self.index[name]["args"]))
        for parameter, value in zip(entry["parameters"], actual):
            expected = arguments[parameter["name"]]
            kind = type_name(parameter)
            if kind == "HANDLE":
                self.assertIs(value, self.host.handles[expected])
            elif kind in {"POINT", "POINT3D", "VECTOR", "COLOR"}:
                self.assertEqual(value, tuple(expected))
            elif kind == "ARRAY" and (name, parameter["name"]) in {
                    ("SetObjectTags", "arrTags"), ("SetResourceTags", "tags")}:
                # These two documented Python interfaces require native tuples.
                self.assertIs(type(value), tuple)
                self.assertEqual(value, tuple(expected))
            elif kind == "PROCEDURE":
                self.assertTrue(callable(value))
            else:
                self.assertEqual(value, expected)

    @staticmethod
    def json_result(value):
        if isinstance(value, FakeHandle):
            return value.uuid
        if isinstance(value, (tuple, list)):
            return [SDKMatrixTests.json_result(part) for part in value]
        if isinstance(value, dict):
            return {key: SDKMatrixTests.json_result(part) for key, part in value.items()}
        return value

    def test_all_sdk_functions_have_matrix_entries_and_precise_live_status(self):
        report = MATRIX.build_matrix(ROOT)
        self.assertEqual(set(report["functions"]), set(self.index))
        self.assertEqual(report["summary"]["sdk_functions"], 3098)
        self.assertEqual(report["summary"]["pending_live_fixtures"] +
                         report["summary"]["functions_observed_live"], 3098)
        self.assertEqual(report["summary"]["full_semantics_verified_functions"], 0)
        for name, entry in report["functions"].items():
            with self.subTest(function=name):
                if entry["live"]["evidence"] is None:
                    self.assertEqual(entry["live"]["status"], "pending_not_executed")
                else:
                    self.assertIn(entry["live"]["status"],
                                  {"passed_cases_observed", "failed_cases_observed", "mixed_cases_observed",
                                   "uncertain_native_attempts", "compatibility_cases_only"})
                self.assertFalse(entry["live"]["full_semantics_verified"])
                self.assertTrue(entry["live"]["fixture_prerequisites"])
                self.assertEqual([p["name"] for p in entry["parameters"]],
                                 self.index[name]["args"])

    def test_live_evidence_tracks_only_explicit_cases_and_keeps_failures(self):
        evidence = {
            "schema_version": 1,
            "host": {"vectorworks_year": 2027, "build": 882075},
            "sdk": {"sdk_version": 3200, "sdk_build": 882699},
            "records": [
                {"function": "Abs", "status": "passed", "test_case": "negative_real",
                 "input": {"v": -3}, "result": 3},
                {"function": "Abs", "status": "failed", "test_case": "another_case",
                 "input": {"v": -4}, "result": None},
            ],
        }
        grouped = MATRIX.validate_live_evidence(evidence, self.catalog)
        self.assertEqual(set(grouped), {"Abs"})
        observed = MATRIX.live_status(grouped["Abs"], evidence)
        self.assertEqual(observed["status"], "mixed_cases_observed")
        self.assertEqual(observed["case_counts"], {"passed": 1, "failed": 1})
        self.assertEqual(observed["evidence"]["record_indices"], [0, 1])
        self.assertFalse(observed["full_semantics_verified"])
        self.assertEqual(MATRIX.live_status(None, evidence)["status"], "pending_not_executed")

    def test_live_evidence_rejects_unknown_names_and_missing_measurements(self):
        base = {"schema_version": 1,
                "host": {"vectorworks_year": 2027, "build": 882075},
                "sdk": {"sdk_version": 3200, "sdk_build": 882699}}
        invalid_records = [
            {"function": "InventedSDKName", "status": "passed", "test_case": "bad",
             "input": {}, "result": None},
            {"function": "Abs", "status": "passed", "test_case": "no_result", "input": {}},
            {"function": "Abs", "status": "fully_verified", "test_case": "broad_claim",
             "input": {}, "result": None},
        ]
        for record in invalid_records:
            with self.subTest(record=record):
                with self.assertRaises(ValueError):
                    MATRIX.validate_live_evidence(dict(base, records=[record]), self.catalog)

    def test_uncertainty_and_compatibility_never_inflate_native_coverage(self):
        evidence = {"schema_version": 1,
                    "host": {"vectorworks_year": 2027, "build": 882075},
                    "sdk": {"sdk_version": 3200, "sdk_build": 882699}, "records": [
            {"function": "Abs", "status": "passed", "test_case": "native_abs", "input": {"v": -3}, "result": 3},
            {"function": "HArea", "status": "failed", "test_case": "native_area_none", "input": {"h": "fixture"}, "result": None},
            {"function": "UprString", "status": "uncertain", "test_case": "host_lost_after_claim",
             "input": {"str": "abc"}, "result": {"code": "VW_DISPATCH_UNCONFIRMED", "error": "unknown", "cid": "123"}},
            {"function": "UprString", "status": "passed", "execution_kind": "compatibility", "test_case": "ascii_upper",
             "input": {"str": "abc"}, "result": {"result": "ABC", "native_dispatched": False}},
            {"function": "HArea", "status": "passed", "execution_kind": "compatibility", "test_case": "area_fallback",
             "input": {"h": "fixture"}, "result": {"result": 600, "compatibility": {"replacement_function": "HAreaN"}}},
            {"function": "Sin", "status": "passed", "execution_kind": "compatibility", "test_case": "test_only_fixture",
             "input": {"v": 0}, "result": 0},
        ]}
        grouped = MATRIX.validate_live_evidence(evidence, self.catalog)
        summary = MATRIX.live_summary(grouped, 3098)
        self.assertEqual(summary['functions_observed_live'], 2)
        self.assertEqual(summary['pending_live_fixtures'], 3096)
        self.assertEqual(summary['functions_attempted_native'], 3)
        self.assertEqual((summary['live_cases_passed'], summary['live_cases_failed'], summary['live_cases_uncertain']), (1, 1, 1))
        self.assertEqual(summary['compatibility_cases_passed'], 3)
        upper = MATRIX.live_status(grouped['UprString'], evidence)
        self.assertEqual(upper['status'], 'uncertain_native_attempts')
        self.assertEqual(upper['case_counts'], {'passed': 0, 'failed': 0})
        self.assertEqual(upper['uncertain_case_count'], 1)
        self.assertEqual(upper['compatibility_case_counts']['passed'], 1)
        self.assertTrue(upper['native_fixture_pending'])
        self.assertFalse(upper['native_outcome_observed'])
        self.assertEqual(upper['evidence']['uncertain_native_record_indices'], [2])
        self.assertEqual(upper['evidence']['compatibility_record_indices'], [3])
        self.assertEqual(MATRIX.live_status(grouped['Sin'], evidence)['status'], 'compatibility_cases_only')
        self.assertEqual(MATRIX.live_status(grouped['HArea'], evidence)['status'], 'failed_cases_observed')

    def test_live_native_pass_cannot_hide_replacement_or_undispatched_result(self):
        base = {"schema_version": 1, "host": {"vectorworks_year": 2027, "build": 882075},
                "sdk": {"sdk_version": 3200, "sdk_build": 882699}}
        for result in ({'result': 'ABC', 'native_dispatched': False},
                       {'result': 600, 'compatibility': {'replacement_function': 'HAreaN'}}):
            record = {'function': 'UprString', 'status': 'passed', 'test_case': 'incorrect_native_claim',
                      'input': {'str': 'abc'}, 'result': result}
            with self.assertRaises(ValueError):
                MATRIX.validate_live_evidence(dict(base, records=[record]), self.catalog)
            record['execution_kind'] = 'compatibility'
            self.assertIn('UprString', MATRIX.validate_live_evidence(dict(base, records=[record]), self.catalog))

    def test_checked_in_matrix_is_current(self):
        expected = MATRIX.render(MATRIX.build_matrix(ROOT))
        actual = (ROOT / MATRIX.REPORT).read_text(encoding="utf-8")
        self.assertEqual(actual, expected,
                         "Regenerate with python tools/sdk_test_matrix.py")

    def test_unassigned_material_baselines_are_coherent_without_repair_or_native_credit(self):
        name = 'GetObjMaterialName'
        entry, arguments = self.prepare(name)
        self.assertEqual(self.native.result, (False, ''))
        result = self.invoke(name, {'arguments': arguments})
        self.assertEqual(result['result'], [False, ''])
        self.assertNotIn('compatibility', result)
        self.assert_call_mapping(name, entry, arguments)
        host = MATRIX._MockHost()
        sample = tuple(MATRIX._fixture_value(p, host, i + 500, name, True)
                       for i, p in enumerate(entry['returns']['items']))
        self.assertEqual(sample, (False, ''))
        self.assertFalse(hasattr(host, 'GetObjMaterialHandle'))
        self.assertFalse(hasattr(host, 'GetName'))
        outcomes = MATRIX.probe_adapters(ROOT, dict(self.catalog, functions={name: entry}), {name: self.index[name]})
        self.assertEqual(outcomes[name], {'status': 'mock_dispatched', 'live_verified': False})

    def test_incoherent_material_baseline_still_requires_independent_verification(self):
        name = 'GetObjMaterialName'
        _, arguments = self.prepare(name)
        self.native.result = (False, 'Unverified material')
        result = self.invoke(name, {'arguments': arguments})
        self.assertEqual(result.get('code'), 'SDK_RESULT', result)
        self.assertEqual(len(self.native.calls), 1)
        self.assertNotIn('compatibility', result)

    def test_every_generated_wrapper_binds_correct_symbol_and_argument_order(self):
        # Bypass the adapter only for this isolated binding check. Distinct
        # sentinels detect swaps even where adjacent SDK types are identical.
        for name, signature in self.index.items():
            with self.subTest(function=name):
                self.native.calls.clear()
                ordered = tuple(object() for _ in signature["args"])
                envelope = {"arguments": dict(zip(signature["args"], ordered))}
                marker = object()
                self.native.result = marker

                def relay(function_name, payload, call=None):
                    self.assertEqual(function_name, name)
                    self.assertIs(payload, envelope)
                    return call(*(payload["arguments"][arg]
                                  for arg in signature["args"]))

                with patch.object(self.runtime, "invoke", side_effect=relay):
                    result = getattr(self.generated, "sdk_" + name)(envelope)
                self.assertIs(result, marker)
                self.assertEqual(self.native.calls, [(name, ordered)])

    def test_every_wrapper_rejects_extra_named_argument_before_dispatch(self):
        for name, signature in self.index.items():
            with self.subTest(function=name):
                params = dict.fromkeys(signature["args"], 0)
                params["__unknown_sdk_parameter__"] = None
                result = self.invoke(name, {"arguments": params})
                self.assertEqual(result.get("code"), "SDK_ARGUMENTS", result)
                self.assertFalse(result.get("dispatched"), result)
        self.assertEqual(self.native.calls, [])

    def test_every_required_parameter_has_missing_argument_rejection(self):
        for name, signature in self.index.items():
            for missing in signature["args"][:signature["required"]]:
                with self.subTest(function=name, missing=missing):
                    params = dict.fromkeys(signature["args"], 0)
                    del params[missing]
                    result = self.invoke(name, {"arguments": params})
                    self.assertEqual(result.get("code"), "SDK_ARGUMENTS", result)
                    self.assertFalse(result.get("dispatched"), result)
        self.assertEqual(self.native.calls, [])

    def test_every_wrapper_rejects_malformed_argument_envelope(self):
        for name in self.index:
            with self.subTest(function=name):
                result = self.invoke(name, {"arguments": []})
                self.assertIn(result.get("code"), {"SDK_ARGUMENTS", "SDK_TYPE"}, result)
                self.assertFalse(result.get("dispatched"), result)
        self.assertEqual(self.native.calls, [])

    def test_every_runtime_adapter_maps_values_or_explicitly_rejects_context(self):
        dispatched, blocked, compatibility = 0, 0, 0
        for name in self.index:
            with self.subTest(function=name):
                entry, arguments = self.prepare(name)
                result = self.invoke(name, {"arguments": arguments})
                blocked_code = self.expected_block(name, entry)
                if blocked_code:
                    self.assertEqual(result.get("code"), blocked_code, result)
                    self.assertFalse(result.get("dispatched"), result)
                    self.assertEqual(self.native.calls, [])
                    blocked += 1
                elif name == 'UprString':
                    self.assertEqual(result.get('status'), 'ok', result)
                    self.assertEqual(result['result'], arguments['str'].upper())
                    self.assertIs(result.get('native_dispatched'), False)
                    self.assertEqual(self.native.calls, [])
                    compatibility += 1
                else:
                    self.assertEqual(result.get("status"), "ok", result)
                    self.assert_call_mapping(name, entry, arguments)
                    self.assertEqual(result.get("result"), self.json_result(self.native.result))
                    dispatched += 1
        self.assertEqual(dispatched + blocked + compatibility, len(self.index))
        print("SDK fake-host mapping: %d dispatched; %d local compatibility; %d explicitly blocked; 0 live calls."
              % (dispatched, compatibility, blocked))

    def test_invalid_parameter_types_and_ranges_never_dispatch(self):
        cases = 0
        for name in self.index:
            entry, arguments = self.prepare(name)
            if self.expected_block(name, entry):
                continue  # Context rejection precedes type conversion by contract.
            for parameter in entry["parameters"]:
                for ordinal, invalid in enumerate(invalid_values(parameter, name)):
                    with self.subTest(function=name, parameter=parameter["name"], mutation=ordinal):
                        mutated = dict(arguments, **{parameter["name"]: invalid})
                        self.native.calls.clear()
                        result = self.invoke(name, {"arguments": mutated})
                        self.assertIn(result.get("code"), {"SDK_TYPE", "SDK_RANGE", "SDK_HANDLE"}, result)
                        self.assertFalse(result.get("dispatched"), result)
                        self.assertEqual(self.native.calls, [])
                        cases += 1
        self.assertGreater(cases, 10000)
        print("SDK invalid-type/range mutations: %d rejected before fake dispatch." % cases)

    def test_documented_primitive_abi_boundaries_map_without_coercion(self):
        # These are transport/ABI boundaries only. A native API may impose much
        # narrower geometric, resource-index or event-ID domains.
        cases = 0
        for name in self.index:
            entry, arguments = self.prepare(name)
            if self.expected_block(name, entry):
                continue
            for parameter in entry["parameters"]:
                for ordinal, value in enumerate(valid_boundaries(parameter)):
                    with self.subTest(function=name, parameter=parameter["name"], boundary=ordinal):
                        mutated = dict(arguments, **{parameter["name"]: value})
                        self.native.calls.clear()
                        result = self.invoke(name, {"arguments": mutated})
                        if name == 'UprString':
                            self.assertEqual(self.native.calls, [])
                            if value.isascii():
                                self.assertEqual(result.get('result'), value.upper())
                                self.assertIs(result.get('native_dispatched'), False)
                            else:
                                self.assertEqual(result.get('code'), 'SDK_UNSUPPORTED')
                                self.assertFalse(result.get('dispatched'))
                            continue  # Local semantic restriction, not a native primitive ABI boundary.
                        self.assertEqual(result.get("status"), "ok", result)
                        self.assert_call_mapping(name, entry, mutated)
                        cases += 1
        self.assertGreater(cases, 10000)
        print("SDK accepted primitive ABI boundary cases: %d (fake host only)." % cases)

    def test_malformed_native_result_is_not_silently_discarded(self):
        for name in self.index:
            entry, arguments = self.prepare(name)
            if self.expected_block(name, entry):
                continue
            if name == 'UprString':
                self.native.result = object()
                result = self.invoke(name, {'arguments': arguments})
                self.assertEqual(result.get('result'), arguments['str'].upper())
                self.assertIs(result.get('native_dispatched'), False)
                self.assertEqual(self.native.calls, [])
                continue  # No native return exists on this compatibility path.
            with self.subTest(function=name):
                returns = entry["returns"]
                self.native.result = () if returns["kind"] == "tuple" else object()
                result = self.invoke(name, {"arguments": arguments})
                self.assertEqual(result.get("code"), "SDK_RESULT", result)
                self.assertTrue(result.get("dispatched"), result)
                self.assertEqual(len(self.native.calls), 1)

    def test_category_fixtures_do_not_assume_menu_context_is_universal(self):
        for category in ("Dialogs - Modern", "Object Events", "Tool Events"):
            fixture = MATRIX.prerequisites({"category": category})
            self.assertTrue(any("context" in requirement.lower()
                                for requirement in fixture))
        handles = MATRIX.prerequisites(
            {"category": "Object Info", "parameters": [{"type": "HANDLE"}]})
        self.assertTrue(any("offline" in requirement for requirement in handles))

    def test_primitive_edge_dimensions_include_known_contract_boundaries(self):
        expected = {"BOOLEAN": "boolean", "INTEGER": "integer", "REAL": "real",
                    "STRING": "text", "HANDLE": "handle", "PROCEDURE": "callback",
                    "POINT": "point", "RGBCOLOR": "color", "ARRAY": "aggregate"}
        for sdk_type, dimension in expected.items():
            self.assertIn(dimension, MATRIX.type_dimensions(sdk_type))
        self.assertEqual(MATRIX.type_dimensions("UNDOCUMENTED_NATIVE_POINTER"), [])


if __name__ == "__main__":
    unittest.main()
