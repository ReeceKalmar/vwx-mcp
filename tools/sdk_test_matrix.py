#!/usr/bin/env python3
"""Generate an SDK-wide test requirement matrix without invoking Vectorworks.

The matrix combines a test specification and injected mock baseline with optional
recorded native cases from docs/LIVE_SDK_2027.json. Only the exact recorded cases
receive native evidence; other APIs remain pending and no full semantic claim is
made. Generation itself never invokes a live host.

Usage: python tools/sdk_test_matrix.py [--repo ROOT] [--check]
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = "vwx-plugin/sdk_catalog.json"
INDEX = "vwx-plugin/vs_index.json"
REPORT = "docs/SDK_TEST_MATRIX_2027.json"
RUNTIME = "vwx-plugin/sdk_runtime.py"
GENERATED = "vwx-plugin/sdk_generated.py"
LIVE_EVIDENCE = "docs/LIVE_SDK_2027.json"

CONTRACT_DIMENSIONS = {
    "generated_binding": {
        "scope": "offline generated wrapper",
        "requirement": "Every sdk_Name invokes the matching vs.Name and preserves independent SDK-index argument order.",
    },
    "exact_named_arguments": {
        "scope": "offline runtime",
        "requirement": "Reject every missing required parameter and an unknown parameter before native dispatch.",
    },
    "envelope": {
        "scope": "offline runtime",
        "requirement": "Require the arguments/options envelope; reject malformed mappings and unknown envelope keys.",
    },
    "primitive_types": {
        "scope": "offline runtime",
        "requirement": "Reject incompatible JSON values for supported types without calling the native function.",
    },
    "boolean": {
        "scope": "offline runtime",
        "cases": ["true", "false", "reject numeric and string substitutes"],
    },
    "integer": {
        "scope": "offline runtime",
        "cases": ["signed ABI lower/upper bounds", "zero", "negative", "reject fractional, boolean and overflow values"],
    },
    "real": {
        "scope": "offline runtime",
        "cases": ["zero", "negative finite", "positive finite", "reject booleans, NaN and infinity"],
    },
    "text": {
        "scope": "offline runtime",
        "cases": ["empty string", "Unicode", "reject non-string JSON"],
    },
    "point": {
        "scope": "offline runtime",
        "cases": ["exact coordinate count", "mixed integer/real coordinates", "reject wrong length and nonfinite coordinates"],
    },
    "color": {
        "scope": "offline runtime",
        "cases": ["three channels", "0 and 65535 boundaries", "reject wrong length, boolean and out-of-range channels"],
    },
    "handle": {
        "scope": "offline adapters plus pending typed live fixtures",
        "cases": ["UUID resolves to a valid handle", "reject unknown/type-zero handle", "typed return UUID serialization"],
        "restriction": "Invalid native handles are tested against fakes only; never blindly inject them into the host.",
    },
    "callback": {
        "scope": "offline registered callback adapters plus pending native callback fixtures",
        "cases": ["recognized declarative callback descriptor", "unsupported descriptor rejected", "event/procedure signature fixture"],
        "restriction": "Arbitrary callback code and undocumented native callback contexts are not synthesized.",
    },
    "aggregate": {
        "scope": "offline runtime",
        "cases": ["supported finite JSON container", "empty container where allowed", "reject unsupported native objects and nonfinite nested values"],
    },
    "return_contract": {
        "scope": "offline runtime",
        "requirement": "Serialize documented scalar/tuple/handle results using fake return values; native shape/semantics still need fixtures.",
    },
    "native_semantics": {
        "scope": "pending live host",
        "requirement": "Independently verify geometry/data outcomes, units, return values, mutation/consumption and regeneration in the documented context.",
    },
}

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_live_evidence(evidence, catalog):
    """Require explicit native inputs/results; never infer incidental API calls."""
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1:
        raise ValueError("Unsupported live evidence schema")
    host, sdk = evidence.get("host", {}), evidence.get("sdk", {})
    if (host.get("vectorworks_year") != 2027 or type(host.get("build")) is not int
            or host["build"] <= 0):
        raise ValueError("Live evidence must identify the 2027 application build")
    if (sdk.get("sdk_version") != catalog["sdk_version"]
            or sdk.get("sdk_build") != catalog["sdk_build"]):
        raise ValueError("Live evidence SDK provenance does not match the catalog")
    records = evidence.get("records")
    if not isinstance(records, list):
        raise ValueError("Live evidence records must be a list")
    edge_cases = evidence.get("adapter_edge_cases", [])
    if not isinstance(edge_cases, list) or any(
            not isinstance(case, dict) or case.get("name") not in catalog["functions"]
            or type(case.get("passed")) is not bool or not isinstance(case.get("result"), dict)
            for case in edge_cases):
        raise ValueError("Adapter edge cases require known names, results and boolean outcomes")
    by_function = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict) or record.get("function") not in catalog["functions"]:
            raise ValueError("Unknown SDK function in live evidence record %d" % index)
        if record.get("status") not in {"passed", "failed", "uncertain"}:
            raise ValueError("Live evidence status must be passed, failed or uncertain")
        kind = record.get("execution_kind", "native")
        if kind not in {"native", "compatibility"}:
            raise ValueError("Live execution_kind must be native or compatibility")
        if (not isinstance(record.get("test_case"), str) or not record["test_case"].strip()
                or "input" not in record or "result" not in record):
            raise ValueError("Live evidence requires a test_case, exact input and result")
        result = record["result"]
        if (kind == "native" and record["status"] == "passed" and isinstance(result, dict)
                and (result.get("native_dispatched") is False or result.get("compatibility"))):
            raise ValueError("A compatibility result cannot be counted as a native API pass; set execution_kind=compatibility")
        by_function.setdefault(record["function"], []).append((index, record))
    return by_function


def live_status(records, evidence):
    records = records or []
    native = [(i, r) for i, r in records if r.get("execution_kind", "native") == "native"]
    compatibility = [(i, r) for i, r in records if r.get("execution_kind", "native") == "compatibility"]
    counts = Counter(record["status"] for _, record in native)
    compatibility_counts = Counter(record["status"] for _, record in compatibility)
    definitive = [(i, r) for i, r in native if r["status"] in {"passed", "failed"}]
    if definitive:
        status = ("mixed_cases_observed" if counts["passed"] and counts["failed"] else
                  "passed_cases_observed" if counts["passed"] else "failed_cases_observed")
    elif counts["uncertain"]:
        status = "uncertain_native_attempts"
    elif compatibility:
        status = "compatibility_cases_only"
    else:
        status = "pending_not_executed"
    return {"status": status,
            "case_counts": {"passed": counts["passed"], "failed": counts["failed"]},
            "uncertain_case_count": counts["uncertain"],
            "compatibility_case_counts": {key: compatibility_counts[key] for key in ("passed", "failed", "uncertain")},
            "native_outcome_observed": bool(definitive),
            "native_fixture_pending": not bool(definitive),
            "evidence": ({"path": LIVE_EVIDENCE, "record_indices": [i for i, _ in records],
                          "native_result_record_indices": [i for i, _ in definitive],
                          "uncertain_native_record_indices": [i for i, r in native if r["status"] == "uncertain"],
                          "compatibility_record_indices": [i for i, _ in compatibility],
                          "host": evidence["host"], "sdk": evidence["sdk"]} if records else None),
            "full_semantics_verified": False}


def live_summary(by_function, function_count):
    """Definitive native outcomes, unknown attempts and replacements never mix."""
    native, compatibility = [], []
    for records in by_function.values():
        for _, record in records:
            (native if record.get("execution_kind", "native") == "native" else compatibility).append(record)
    observed = {r["function"] for r in native if r["status"] in {"passed", "failed"}}
    uncertain = {r["function"] for r in native if r["status"] == "uncertain"}
    return {
        "pending_live_fixtures": function_count - len(observed),
        "functions_observed_live": len(observed),
        "live_cases_passed": sum(r["status"] == "passed" for r in native),
        "live_cases_failed": sum(r["status"] == "failed" for r in native),
        "live_cases_uncertain": sum(r["status"] == "uncertain" for r in native),
        "functions_with_passed_case": len({r["function"] for r in native if r["status"] == "passed"}),
        "functions_with_failed_case": len({r["function"] for r in native if r["status"] == "failed"}),
        "functions_with_uncertain_case": len(uncertain),
        "functions_with_only_uncertain_native_cases": len(uncertain - observed),
        "functions_attempted_native": len(observed | uncertain),
        "compatibility_cases_passed": sum(r["status"] == "passed" for r in compatibility),
        "compatibility_cases_failed": sum(r["status"] == "failed" for r in compatibility),
        "compatibility_cases_uncertain": sum(r["status"] == "uncertain" for r in compatibility),
        "functions_with_compatibility_case": len({r["function"] for r in compatibility}),
        "functions_with_passed_compatibility_case": len({r["function"] for r in compatibility if r["status"] == "passed"}),
        "full_semantics_verified_functions": 0,
    }


class _MockHandle:
    def __init__(self, uuid):
        self.uuid = uuid


class _MockHost:
    def __init__(self):
        self.handles = {}

    def GetVersion(self):
        return (32, 0, 0, 2)  # SDK: fourth field is platform (2 = Windows).

    def GetObjectByUuid(self, uuid):
        return self.handles.get(uuid)

    def GetObjectUuid(self, handle):
        return handle.uuid if isinstance(handle, _MockHandle) else ""

    def GetTypeN(self, handle):
        return 3 if isinstance(handle, _MockHandle) else 0


def callback_fixture(entry, limit=2):
    """Minimal valid declarative recipe; it never opens a native callback context."""
    mode = (entry or {}).get('callback_contract', {}).get('mode', 'collect')
    result = {'mode': mode, 'limit': limit}
    result.update({'filter': {'object_types': [3]}, 'conflict': {'action': 'skip'},
                   'dialog': {'events': {}}}.get(mode, {}))
    return result


def _fixture_value(parameter, host, ordinal=1, function="", output=False, entry=None):
    kind = " ".join(parameter.get("type", "UNKNOWN").upper().split())
    if output and function == 'GetObjMaterialName':
        # The generic alternating tuple would fabricate (False, nonempty name),
        # a contradictory native result requiring independent resource checks.
        # This transport-only host has no material model: use the coherent
        # unassigned result, leaving repair semantics to dedicated tests.
        if kind == 'BOOLEAN':
            return False
        if kind == 'STRING':
            return ''
    if kind == "HANDLE":
        uuid = "12345678-1234-4321-8765-%012d" % ordinal
        handle = host.handles.setdefault(uuid, _MockHandle(uuid))
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
        return [ordinal + offset + 0.25 for offset in range(2 if kind == "POINT" else 3)]
    if kind == "COLOR":
        return [ordinal, 1234, 65535]
    if kind == "PROCEDURE":
        return callback_fixture(entry)
    if kind == "ARRAY":
        if function == "SetListBoxTabStops":
            return [10, 20]
        if parameter.get("name") == "arrOptions":
            return ["category", "setting", "label"]
        return ["first", "second"]
    if kind == "ANY":
        return {"fixture": [ordinal, "value"]}
    raise ValueError("No offline fixture for SDK type " + kind)


def probe_adapters(root, catalog, index):
    """Execute actual runtime validation/serialization against a signature fake.

    No vs module is imported: invoke receives the resolver and native callable
    explicitly. This records only one transport-valid baseline per API, with
    default menu context, no sequence permission and no force override.
    """
    spec = importlib.util.spec_from_file_location("sdk_matrix_runtime", Path(root) / RUNTIME)
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    host, outcomes = _MockHost(), {}
    for name, entry in sorted(catalog["functions"].items()):
        arguments = {p["name"]: _fixture_value(p, host, i + 1, name, entry=entry)
                     for i, p in enumerate(entry["parameters"])}
        returns = entry["returns"]
        if returns["kind"] == "void":
            raw = None
        elif returns["kind"] == "scalar":
            raw = _fixture_value(returns, host, 500, name, True)
        else:
            raw = tuple(_fixture_value(p, host, i + 500, name, True)
                        for i, p in enumerate(returns["items"]))
        signature = inspect.Signature([
            inspect.Parameter(argument, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            for argument in index[name]["args"]])
        calls = []

        def target(*args):
            signature.bind(*args)
            calls.append(args)
            return raw

        result = runtime.invoke(name, {"arguments": arguments}, target,
                                vs_module=host, catalog=catalog)
        if (name == 'UprString' and result.get('status') == 'ok' and not calls
                and result.get('native_dispatched') is False
                and result.get('result') == arguments['str'].upper()):
            outcomes[name] = {'status': 'compatibility_executed', 'native_called': False,
                              'implementation': 'python.str.upper', 'input_constraint': 'ASCII only',
                              'live_verified': False}
        elif result.get("status") == "ok" and len(calls) == 1:
            outcomes[name] = {"status": "mock_dispatched", "live_verified": False}
        elif result.get("code") in {"SDK_CONTEXT", "SDK_UNSUPPORTED"} and not calls:
            outcomes[name] = {"status": "rejected_before_dispatch", "code": result["code"],
                              "reason": result["error"], "live_verified": False}
        else:
            raise ValueError("Unexpected fake-host adapter outcome for %s: %s" % (name, result))
    return outcomes


def type_dimensions(type_name):
    value = (type_name or "").upper().replace(" ", "")
    if value in {"BOOLEAN", "BOOL"}:
        return ["boolean"]
    if value in {"INTEGER", "LONGINT", "SHORTINT", "BYTE", "SIZE_T", "LONG", "INT", "TEXTSTYLE"}:
        return ["integer"]
    if value in {"REAL", "DOUBLE", "FLOAT"}:
        return ["real"]
    if value in {"STRING", "DYNARRAYOFCHAR", "DYNARRAY[]OFCHAR", "CHAR", "TEXT", "CRITERIA"}:
        return ["text"]
    if value in {"POINT", "POINT2", "POINT3", "POINT3D", "VECTOR", "VECTOR2", "VECTOR3"}:
        return ["point"]
    if value in {"RGBCOLOR", "COLOR"}:
        return ["color"]
    if value == "HANDLE":
        return ["handle"]
    if any(token in value for token in ("PROCEDURE", "FUNCTION", "CALLBACK")):
        return ["callback"]
    if value in {"ANY", "ARRAY", "DYNARRAY", "TEXTSTYLE", "VARIANT"}:
        return ["aggregate"]
    return []


def prerequisites(function):
    """Conservative review prompts; category alone never authorizes invocation."""
    category = function.get("category", "")
    result = ["Vectorworks 2027 main-thread execution in the API's documented context",
              "Per-function SDK documentation review and an independently specified expected result"]
    if category.startswith("Dialogs"):
        result += ["Disposable dialog/layout with valid control IDs",
                   "Documented dialog event lifecycle; a plain menu job may not provide it"]
    elif (category in {"Object Events", "Tool Events"}
          and function.get('context', {}).get('required_host_context')):
        result += ["Real plug-in/tool event fixture and documented event identifiers",
                   "Call only inside the required event context; do not simulate it with arbitrary menu calls"]
    elif category.startswith("Math") or category in {"Strings", "Units", "Color"}:
        result += ["Known input/output examples and documented unit/domain boundary values"]
    elif category in {"Graphic Calculation", "Parametric Constraints"}:
        result += ["Known valid geometry plus separately designed degenerate/no-solution fixtures",
                   "Documented numeric tolerances and coordinate units"]
    elif category in {"File I/O", "ImportExport", "PDF", "Excel", "XML", "XML SAX", "ODBC", "Workspaces"}:
        result += ["Disposable external files/resources and isolated output paths",
                   "Required file/dialog/database session lifecycle; confirm modal behavior"]
    else:
        result += ["Disposable drawing with correctly typed objects/resources and known document units",
                   "Create/reset fixtures in a separate job before regeneration-dependent inspection"]
    if category in {"Project Sharing"}:
        result += ["Disposable project-sharing file, valid checkout/session state and other-user conflict fixture"]
    if category in {"Spotlight", "Truss Analysis", "ConnectCAD", "EnergyAnalysis Interface Library",
                    "PlantObjectCoreTools", "SiteModel Interface Library", "SpaceObjectCoreTools",
                    "Roadway Interface Library", "StructuralMember", "Objects - Custom", "Objects - Cables"}:
        result += ["Required product/module plug-ins, licensed features and native object lifecycle"]
    if any("handle" in type_dimensions(parameter.get("type"))
           for parameter in function.get("parameters", [])):
        result += ["Live UUID handles with the documented object/resource types; stale/null tests stay offline until specifically justified"]
    if any("callback" in type_dimensions(parameter.get("type"))
           for parameter in function.get("parameters", [])):
        result += ["Documented callback arity, return protocol, event context and collector behavior"]
    return result


def build_matrix(root=ROOT):
    root = Path(root)
    catalog = json.loads((root / CATALOG).read_text(encoding="utf-8"))
    index = json.loads((root / INDEX).read_text(encoding="utf-8"))
    functions = catalog["functions"]
    if set(functions) != set(index):
        raise ValueError("Catalog and independent SDK index have different function sets")
    evidence_path = root / LIVE_EVIDENCE
    evidence = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.is_file() else None
    live_by_function = validate_live_evidence(evidence, catalog) if evidence is not None else {}
    outcomes = probe_adapters(root, catalog, index)
    entries = {}
    for name, function in sorted(functions.items()):
        parameters = function.get("parameters", [])
        if [parameter["name"] for parameter in parameters] != index[name]["args"]:
            raise ValueError("Catalog argument order differs from SDK index: " + name)
        entries[name] = {
            "command": function.get("command", "sdk_" + name),
            "category": function.get("category", ""),
            "contract_dimensions": ["generated_binding", "exact_named_arguments", "envelope",
                                    "primitive_types", "return_contract"],
            "parameters": [
                {"name": parameter["name"], "sdk_type": parameter.get("type", ""),
                 "required": parameter.get("required", True),
                 "dimensions": type_dimensions(parameter.get("type")),
                 "native_domain_validation": "pending_documented_fixture"}
                for parameter in parameters
            ],
            "context": function.get("context", {}),
            "offline_baseline": outcomes[name],
            "live": {
                **live_status(live_by_function.get(name), evidence),
                "dimension": "native_semantics",
                "fixture_prerequisites": prerequisites(function),
            },
        }
    categories = Counter(function.get("category", "") for function in functions.values())
    required_cases = sum(parameter.get("required", True)
                         for function in functions.values()
                         for parameter in function.get("parameters", []))
    edge_cases = evidence.get("adapter_edge_cases", []) if evidence else []
    hashes = {path: sha256(root / path) for path in
              (CATALOG, INDEX, RUNTIME, GENERATED, "tools/sdk_test_matrix.py")}
    if evidence is not None:
        hashes[LIVE_EVIDENCE] = sha256(evidence_path)
    return {
        "schema_version": 1,
        "scope": "Vectorworks 2027 Python API wrapper contracts and pending native integration requirements",
        "sdk": {key: catalog.get(key) for key in
                ("vectorworks_year", "sdk_version", "sdk_build")},
        "source_hashes": hashes,
        "live_evidence_source": LIVE_EVIDENCE if evidence is not None else None,
        "evidence_boundary": [
            "This matrix specifies checks and records an injected fake-host baseline plus only explicitly recorded native input/result cases.",
            "Offline tests verify generated binding and transport/type contracts against fakes, not API semantics or every meaningful edge case.",
            "No function is called in the real host by the generator or its offline tests; native evidence is imported from a separate recorded session.",
            "Unsupported callback, pointer and event contexts must return explicit undispatched errors; a wrapper name is not proof those contexts are supported.",
            "APIs without recorded native cases remain pending; a passing or failing case does not establish complete semantic or edge-case coverage.",
            "Unconfirmed native attempts and compatibility replacement results are reported separately; neither earns a native API pass or removes a pending native fixture.",
        ],
        "summary": {
            "sdk_functions": len(functions),
            "generated_binding_case_specs": len(functions),
            "unknown_argument_case_specs": len(functions),
            "missing_required_argument_case_specs": required_cases,
            "mock_dispatched_adapters": sum(outcome["status"] == "mock_dispatched" for outcome in outcomes.values()),
            "mock_rejected_adapters": sum(outcome["status"] == "rejected_before_dispatch" for outcome in outcomes.values()),
            "mock_compatibility_adapters": sum(outcome["status"] == "compatibility_executed" for outcome in outcomes.values()),
            "mock_baseline_context": "single menu job; no sequence permission or force override",
            **live_summary(live_by_function, len(functions)),
            "live_adapter_edge_cases": len(edge_cases),
            "live_adapter_edge_cases_passed": sum(case["passed"] for case in edge_cases),
            "categories": dict(sorted(categories.items())),
        },
        "dimensions": CONTRACT_DIMENSIONS,
        "functions": entries,
    }


def render(matrix):
    return json.dumps(matrix, ensure_ascii=False, indent=2) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    content = render(build_matrix(options.repo))
    path = options.repo / REPORT
    if options.check:
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            print("SDK test matrix is stale; run python tools/sdk_test_matrix.py")
            return 1
        print("SDK test matrix is current; native evidence is limited to explicitly recorded cases.")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print("Wrote " + str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
