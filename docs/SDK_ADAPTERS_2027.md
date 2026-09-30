# Generated Vectorworks 2027 SDK adapters

The fork generates one named adapter and MCP tool for every **3,098** top-level
Python API function in SDK 3200, build 882699. Each `sdk_Name` declares a direct
`vs.Name` binding; the runtime can apply the disclosed compatibility paths below.
The catalog supplies exact parameter names, transport types, return
shapes and context restrictions. C++ interfaces and `Handle` class methods are
outside this count.

Generated binding coverage is complete for this Python stub. Native semantic
coverage is not: some functions require tool/PIO events, transient native values,
callbacks or construction scopes that a standalone JSON menu job cannot supply.
Those paths return explicit errors rather than fabricate a successful result.
The per-function [test matrix](SDK_TEST_MATRIX_2027.json) imports only the exact
native cases recorded in [LIVE_SDK_2027.json](LIVE_SDK_2027.json). Other APIs
remain pending, and an observed pass does not certify every input or context.

The SDK's `GetGradientDataN` Python docstring conflicts with its procedure
declaration and executable stub. Its effective catalog signature has six outputs
(`spotPosition`, `midpointPosition`, `red`, `green`, `blue`, `opacity`), matching
the saved native return and independent gradient/opacity getters. The catalog
retains the original declaration and [evidence](GRADIENT_RETURN_2027.json) in
`return_contract_correction`. Generation rejects changed source declarations or
SDK versions until they are reviewed; it does not invent a success Boolean.

## Discover and invoke

Use `sdk_list(name="Abs")` for one complete contract, or search/category filters
with `offset` and `limit` (1–200). Names are case-sensitive. Parameters retain
their SDK spelling, including mixed capitalization.

Equivalent request examples:

```python
sdk_Abs(arguments={"v": -3})
sdk_call(name="Abs", arguments={"v": -3})
vwx(command="sdk_Abs", params={"arguments": {"v": -3}})
```

The dispatcher envelope is:

```json
{"arguments": {"v": -3}, "options": {}}
```

SDK parameters go inside `arguments`, so a native parameter named `name`,
`options` or `force` cannot collide with transport controls. Extra keys and
missing required keys are rejected. `options` currently accepts only a boolean
`force`. Omitting `arguments` is supported for zero-argument APIs on the
dispatcher/runtime path; named MCP tools expose an `arguments` object.

The existing handwritten tools remain the simplest interface for their
workflows. The default `VWX_BACKGROUND_MODE=1` rejects arbitrary `execute_script`
requests and known interactive operations before enqueueing. Raw scripts require
explicitly attended mode; they are not counted as implementation coverage.
See [BACKGROUND_WORK.md](BACKGROUND_WORK.md).

## Transport types and results

| SDK type | JSON input |
|---|---|
| BOOLEAN | `true` or `false` |
| INTEGER / LONGINT | Signed 16-bit / signed 32-bit integer; booleans rejected |
| REAL | Finite JSON number; NaN/infinity rejected |
| STRING / DYNARRAY of CHAR / CRITERIA | String |
| CHAR | One character |
| POINT | Two finite coordinates |
| POINT3D / VECTOR | Three finite coordinates |
| COLOR | Three integer channels, each 0–65535 |
| HANDLE | Object UUID string, resolved and validated in the host |
| TEXTSTYLE | SDK style bitmask, 0–31 |
| ARRAY / ANY | Supported finite JSON data; documented array restrictions apply |
| PROCEDURE | A supported declarative callback descriptor, otherwise an explicit error |

These checks enforce the transport and ABI contract. They do not prove that a
selector, resource index, geometry dimension or object type is meaningful for
the requested API. Only `BeginGroupN.groupHandle` is explicitly nullable among
the currently supported input handle contracts. Transient non-object handles
and native pointers cannot be represented as ordinary document UUIDs.

`SetResourceTags.tags` and `SetObjectTags.arrTags` accept flat JSON string
arrays and convert them to Python tuples at the native-call boundary. The
[SetResourceTags reference](https://github.com/Vectorworks/developer-scripting/blob/main/Function%20Reference/Functions/SetResourceTags.md)
points to the tuple convention illustrated by
[SetObjectTags](https://github.com/Vectorworks/developer-scripting/blob/main/Function%20Reference/Functions/SetObjectTags.md).
Offline tests check exact tuple dispatch, Unicode/order preservation, empty
arrays, rejection of nested values, and unchanged unrelated array handling.
A fresh typed native run, `tags-tuple-20260926-b`, passed six jobs covering five
APIs: a Unicode resource tag was set, counted and read back, with material
identity preserved. That is evidence for the `SetResourceTags` fixture; the
parallel `SetObjectTags` conversion and all other tag combinations are not
thereby verified. An earlier `SetResourceTags` call returned null before the
following guard failed to complete. The list conversion has not been established
as the cause, and that earlier run remains incomplete without tag readback.

Solid booleans have a separate return-shape boundary: `AddSolid`, `SubtractSolid`
and `IntersectSolid` return `(errorCode, newSolid)`, with integer zero indicating
success. Generated results retain both fields and translate the returned object
handle to its UUID. The handwritten `boolean_operation` now validates that
tuple, rejects native error codes/malformed values/missing result objects, and
returns only the resulting object's UUID. It previously treated the tuple itself
as a handle. Unknown operation names fail before dispatch. Fifteen focused
offline tests passed. A separate native probe then verified fresh add, intersect
and subtract cases through the handwritten wrapper, with returned UUIDs and
independent dimensions/centroid readbacks. The
[workflow record](BOOLEAN_WORKFLOW_2027.json) is separate from generated SDK
API-case evidence and gives it no additional API-count credit.

Supported synchronous collectors are `ForEachObject.callback`,
`ForEachObjectInLayer.actionFunc`, `ForEachObjectAtPoint.actionFunc`,
`ForEachObjectInList.actionFunc` and `ForEachMaterial.callback`:

```json
{"mode": "collect", "limit": 500}
```

Additional callback contracts are discoverable through `sdk_list`:

| APIs | Descriptor | Prerequisite |
|---|---|---|
| `TrackObject`, `TrackObjectN` | `{"mode":"filter","object_types":[3],"limit":500}` | Attended interactive tracking; blocked in background mode |
| `ImportResToCurFileN` | `{"mode":"conflict","action":"skip","limit":500}` | Valid resource list/index; `replace` is also supported |
| `RunLayoutDialog`, `RunLayoutDialogN`, `RunNamedDialog`, `RunNamedDialogN` | `{"mode":"dialog","events":{},"limit":500}` | Valid dialog and attended event loop; blocked in background mode |

Dialog event maps use integer event IDs encoded as strings and lists of
`{name, arguments}` calls to supported, noninteractive modern-dialog APIs.
`{"$dialog":true}` and `{"$event":"item"}` / `{"$event":"data"}` reference the
current callback values. `SetControlData` requires that real dialog callback
context. Arbitrary callback code and `RunTempTool` remain unsupported. These
declarative adapters still need fixtures in their corresponding native contexts.

Results contain `status`, `function` and `result`. Handles become UUIDs,
point/vector/tuple values become JSON arrays, and procedures return null.
Tuple outputs also appear under `outputs` when the SDK provides distinct names.
Collector results appear under `callbacks`. A malformed native return is
reported as an error after dispatch unless an explicitly disclosed compatibility
path handles it. Such responses include `compatibility`; Python-only replacements
also include `native_dispatched=false`.

Errors include a `code`, `function` and `dispatched`. Codes distinguish argument,
type/range, handle, host version, context, unsupported representation, native
execution and result-shape failures. When `dispatched` is true, document changes
may already have occurred.

Transport codes `VW_DISPATCH_UNCONFIRMED`, `VW_DISPATCH_STUCK` and `VW_UNKNOWN`
mean the native outcome is unknown. The host-suite journal keeps those records
as uncertain, with `passed=null`, and stops without retrying. They are not
ordinary native assertion failures.

## Same-job sequences

`sdk_sequence` accepts up to **200** calls in one menu job. It validates
supported Begin/End construction scopes and earlier-result references before
starting. A reference uses a zero-based step index and a path into that step's
response:

```json
{
  "calls": [
    {"name": "Abs", "arguments": {"v": -9}},
    {"name": "Abs", "arguments": {"v": {"$ref": 0, "path": ["result"]}}}
  ],
  "options": {}
}
```

Use a sequence when an API requires a balanced construction scope inside one
Python execution. It stops on failure and attempts cleanup of known open scopes.
There is **no rollback** and **no regeneration boundary between steps**.
Keep PIO creation/reset and regeneration-dependent inspection in separate jobs,
even when a construction sequence is used for the first job.

`Layer` and `CombineIntoSurface` remain quarantined. An explicit
`options.force=true` is required to reach those SDK adapters; it does not remove
other context/type restrictions or establish that the operation is safe.
Unsupported event contexts, native pointers and unimplemented callback protocols
remain errors.

## Registration and visibility

The default `landscape` profile exposes **257 handwritten tools** and omits
individual SDK registrations. `sdk_call`, `sdk_list`, `sdk_sequence` and the
dispatcher remain available. Set `VWX_TOOLSET=full` or `sdk` at startup to opt
into named SDK registrations, or set `VWX_SDK_TOOLS=1` explicitly. `0`, `false`
or `off` overrides registration for every preset. Visibility changes through
`set_toolset` cannot register SDK wrappers omitted at startup.

The full inventory is **3,392 tools**: **294 handwritten tools** plus
**3,098 named SDK tools**. The dispatcher offers **367 handwritten verbs** plus
**3,098 generated commands**. `list_commands(include_sdk=true)` includes the
generated names. Source registration and live functionality are different
measurements. See [TOOL_COVERAGE.md](TOOL_COVERAGE.md).

## Compatibility and native limits

Repairs retain original values and disclose `compatibility`. Exact-build guards
must keep unknown-build behavior unchanged. A replacement's success never earns
a native pass for the replaced API. Read [NATIVE_REPAIRS_2027.md](NATIVE_REPAIRS_2027.md)
before modifying a guard, fixture assumption or repair.

| API | Bounded behavior |
|---|---|
| `HArea` | After native `None` only, call `HAreaN`; malformed non-null results still fail. Five recorded geometry regressions passed as compatibility cases. |
| `UprString` | Local ASCII uppercasing, no native dispatch; non-ASCII returns `SDK_UNSUPPORTED`. The original claimed native attempt is uncertain and must not be retried. |
| `GetTextLeading` | Independently verify noncustom spacing before correcting the documented `-1` sentinel. Preserve legitimate custom values. |
| `GetOpacityByClassN` | Swap returned pen/fill flags only on the measured affected build; independent opacity readbacks established the getter reversal. |
| `GetObjMaterialName` | Correct a false success flag only after independent UUID/type/name checks confirm the assigned material. Empty/mismatched names remain unchanged or fail validation. |
| `GetTextLength` | On the measured build, corroborate text and a matching native UTF-8 byte count before returning UTF-16 units. This does not define grapheme length. |
| `SetGradientOpacity` | Bypass the broken native setter before writing. Validate both getters, apply one `SetGradientDataN`, then verify identity/count/all fields. Post-write failure stays dispatched; no rollback/retry. |
| `SetArc` | Require private bridge ABI 1, native arc handle and finite degree values; use `GS_SetArcAnglesN`, preserving UUID and checking angles. Original and independent geometry fixtures passed after deployment. |

Native NIL output handles are accepted only if exact wrapper type and equality
match a separately constructed native null; falsiness/type zero alone is
insufficient. `GetGradientDataN` uses the independently verified six-output
contract described above. Private bridge arc/maintenance routines add no names
to the official 3,098-function Python inventory.

Units are API-specific. A 30-by-20 rectangle in the recorded inch-coordinate
drawing returned `HAreaN=600`, while `ObjArea`/`ObjAreaN` reported approximately
4.16667 in square-foot display units. Do not interchange these measurements
without documented unit conversion. Text formatting offsets are UTF-16 units;
see [TEXT_INDEXING_2027.json](TEXT_INDEXING_2027.json). Native angles can have
equivalent circular representations, but arc sweep and directional angle are
different contracts.

The [normalized live record](LIVE_SDK_2027.json) preserves failed, successful,
compatibility and uncertain outcomes. [TOOL_COVERAGE.md](TOOL_COVERAGE.md)
distinguishes all generated adapters from unsupported execution contexts and
unconfirmed native APIs. Callable lookup, setter return and complete default
fixture selection each have narrower scope than full native semantics.

## Regenerate and verify

Use the official SDK `SDKLib/Include/vs.py`, never a runtime module or guessed
signature list. The wrapper generator produces `sdk_catalog.json` and
`sdk_generated.py`; the independent index and its metadata must also agree with
the SDK build. Never hand-edit generated files.

```powershell
python tools/build_sdk_wrappers.py 'C:\path\to\SDKVW(882699)\SDKLib\Include\vs.py'
python tools/build_sdk_wrappers.py 'C:\path\to\SDKVW(882699)\SDKLib\Include\vs.py' --check
python tools/sdk_test_matrix.py
python tools/api_coverage.py
python tools/sdk_test_matrix.py --check
python tools/api_coverage.py --check
python -m unittest discover -s tests -v
```

The adapter suite checks each generated binding against the independent index,
required/unknown arguments, primitive boundaries, return validation and context
restrictions using fake native functions. The recorded 75,700 host adapter
checks also prevented native target execution; the current 75,701-case revision
passed offline. Neither establishes actual geometry. The separate
[host-presence inspection](SDK_HOST_PRESENCE_2027.json) inspected all 3,098 names
and found 3,081 callable/17 absent; it did not execute those functions.

Use [TESTING_2027.md](TESTING_2027.md) for curated plans, the typed MCP runner,
separate regeneration/readback jobs, strict evidence import and no-replay rules.
Default native fixtures use new named resources/objects in a guarded disposable
drawing. Characterization is observation without semantic pass credit.
Build/deployment belongs in [BUILD_SETUP.md](BUILD_SETUP.md); current recorded
native hashes and verified maintenance are linked from
[VECTORWORKS_2027.md](VECTORWORKS_2027.md). There is no supported shortcut/TCP
fallback, and native deployment requires Vectorworks closed.
