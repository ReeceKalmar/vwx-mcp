# Testing the Vectorworks 2027 MCP

The suite separates adapter correctness from native Vectorworks behavior.
Offline tests can prove a rejected argument never reached a mocked host, or
that a fixture detects an incorrect result. They cannot prove that Vectorworks
creates the intended object. A designed native case stays pending until an
actual host run records its inputs, response, and passing assertions.

Read [VECTORWORKS_2027.md](VECTORWORKS_2027.md) and
[BACKGROUND_WORK.md](BACKGROUND_WORK.md) before running native tests.
[TOOL_COVERAGE.md](TOOL_COVERAGE.md),
[SDK_TEST_MATRIX_2027.json](SDK_TEST_MATRIX_2027.json), and
[LIVE_SDK_2027.json](LIVE_SDK_2027.json) distinguish the current measured totals.
The plan generator prints its own current case, assertion, and API counts;
these are fixture availability counts, not native passes.

## Current offline checkpoint

The **2026-09-28 repository consolidation** run completed **1,002 tests in
116.919 seconds: 1,001 passed, zero failures/errors and one skipped**. The skip
was the Windows symlink-creation privilege test; separate reparse-path checks
and the compiled offline C++ harnesses passed. The command was
`python -m unittest discover -s tests -v` using Python 3.12.14 on Windows with
the configured dependencies and normal temporary-file access. The unchanged
runtime/test source was commit `061b48431595e94a800d1008f6a3ad529d3b22c7`;
the consolidation changes documentation only.

The private log is `.audit/context-consolidation-20260928/unittest.log`, SHA-256
`66e9827fd863e3473acc6d5e1f9dad788c3c5e6e6708caeee5e42dfbb6221795`.
It is not distributed with the repository. Earlier sandbox temporary-directory
access failures and the historical Code Integrity block remain separate evidence;
the successful run does not explain those earlier environmental failures.
No live Vectorworks call, new SDK semantic result, plug-in build or deployment
is claimed by this checkpoint. See [publication history](PUBLICATION_2027.md)
for the consolidation scope and [design readiness](DESIGN_WORKFLOW.md) before
using test counts to assess a complete design workflow.

The required handwritten tool/tag consistency, SDK test-matrix freshness,
API-coverage freshness and repository hygiene/link/empty-content checks also
passed. Generated reports were already current and were not rewritten. These
local results do not assert that a new GitHub Actions run has completed.

## Earlier checkpoints and native evidence

[Hosted CI for `bad5ce3`](https://github.com/ReeceKalmar/vwx-mcp/actions/runs/36315101072)
passed on both platforms, discovering 1,002 tests per job: 997 passed and five
skipped on Windows; 991 passed and eleven skipped on Linux. The Windows
status-file harness was skipped because the configured MSVC 14.42 compiler was
unavailable; Linux skipped it because it requires Windows/MSVC. Those hosted
results did not validate the locally blocked harness at that time. Static
contracts, repository hygiene, report freshness and offline native-plan
generation also passed. These are historical hosted results, not a CI result
for the current consolidation commit.

The document-transition and wall-repair checkpoint passed **924 tests in
105.137 seconds**, including compiled native harnesses, strict inventory and
transition guards, delivery-stamp races, terrain/component contracts and wall
construction failure paths. One Windows symlink-privilege test was skipped;
separate reparse-path checks passed. The local log is
`.audit/incident-002-guard-final-tests.log` (not published). It adds six evidence-size
and document-capacity regressions to the earlier 918-test repair checkpoint.
The earlier 821-test publication run remains in
[publication validation](PUBLICATION_2027.md).

Separate live evidence records [guarded document transitions](DOCUMENT_TRANSITION_2027.json)
and the [native wall dimension repair](WALL_CREATION_2027.json). These operational
checks preserve their earlier failures and do not increase the SDK API totals.

The [default-suite audit](LIVE_DEFAULT_SUITE_2027.json) records **57 routine
families and 2,303 unique fixture jobs**, all passed across batches A, B and C.
There were 2,343 passing executions because 40 jobs in an interrupted family
were later run in a fresh complete fixture. Diagnostic and characterization
families remain outside that default selection. The final guarded save returned
success and the bridge returned to fresh idle state in process 50236.

The current native evidence covers 401 SDK APIs with confirmed results, 399
with at least one native pass; 2,697 still lack a confirmed native result.
It retains 5,756 passing and 26 failed native API cases, one uncertain attempt,
70 compatibility passes across eight APIs, and seven separate adapter rejection
checks. A case count or complete default selection does not establish every API
input or resolve the historical failures.

The [maintenance controller](MAINTENANCE_2027.md) has separate offline tests for
save/quit ordering, document identity, durable no-replay intents, lease ownership,
cross-process publication races, invalid poll identifiers and interrupted
restarts. Native helpers compile against an independent SDK test model as well
as the actual SDK. Maintenance passes do not increase the official SDK API
coverage denominator or certify native save/quit until a host run records them.

The registry now includes annotation, resource and modeling providers alongside
the original numeric, geometry, data and design fixtures. Use the generated plan
summary for the selected families' current counts and the
[run report](REGRESSION_RESULTS_2027.json) for saved execution outcomes.
Planned jobs, offline tests, executed jobs and native API cases are different
counts: a sequence can contain several calls, and compatibility is separate.
The registry continues to expand. Generate its current summary with
`tools/sdk_regression_suite.py`; characterization jobs have separate counts and
receive no semantic coverage credit. Diagnostic families require explicit
selection in the live batch. Available cases include unresolved expectations.

[Native failure investigation](NATIVE_REPAIRS_2027.md) records the current
root causes, narrow compatibility repairs, additional probes and deployment
status. Use `tools/check_sdk_host_presence.py --plugin-dir <installed-folder>
--output-dir <new-output-folder>` for a read-only sweep of all installed SDK
names. Its page-validation tests reject missing, duplicate, reordered or
malformed observations. Callable availability is separate from native behavior.

The V4 scheduler passed 100 consecutive background reads with matching
invocation/completion counts and zero delivery errors. Subsequent typed batches
verified the six-output gradient contract, native NIL handles, UTF-16 text
lengths, projected construction bounds and explicit worksheet bounds. The
gradient-opacity replacement also passed the original failing fixture. The
new C++ arc helper passed its original arc fixture and independent native
geometry measurements after deployment. Historical failed
results and characterization observations remain separate from these repairs.

Retained native failures concern `SetArc`/`GetArc`, reversed pen/fill flags in
`SetOpacityByClassN`/`GetOpacityByClassN`, zero-cell `IsValidWSCell`, and a false
success flag from `GetObjMaterialName` after successful material assignment.
The earlier `HArea` failure is also retained. See the
[exact findings](VECTORWORKS_2027.md#recorded-native-cases). The earlier scheduler
reported `modal_dialog_open` after `SetResourceTags`; that historical label did
not establish a currently open dialog during later idle checks. Causality is
unproven, remaining work was
stopped, and the next blocked document guard receives no fixture-failure or
native-pass credit. A later deliberate run of fresh resource-tag fixtures passed
after the tuple conversion fix. Subsequent worksheet classification mismatches
and heartbeat loss were retained separately; a resumed heartbeat permits fresh
readiness checks but does not resolve the earlier mismatch or replay any work.

## What the suite checks

| Layer | Evidence provided | Limits |
|---|---|---|
| SDK index and generated bindings | Exact function names, named arguments, arities, source hashes, wrapper registration, output-schema suppression | Does not execute native APIs |
| Adapter contracts | Required and unknown arguments, JSON types, numeric boundaries, UUID resolution, callbacks and context restrictions, invalid return shapes | Unsupported calls can pass by being rejected correctly; fake return values do not establish native semantics |
| Runtime and transport regressions | Single-job scheduling, no replay, completion acknowledgments, wrong version/install rejection, background preflight, sequence references and scopes | Offline host/process models are substitutes; actual Windows scheduler behavior needs separate evidence |
| Fixture and oracle tests | Independent geometry/data expectations, meaningful negative results, later setter readbacks, preservation checks, strict function identity, malformed responses and capture failures | Tests the test harness and reviewed cases; does not cover every SDK input or lifecycle |
| Typed native regression run | Concrete calls and later assertions against an active disposable drawing, through ordinary MCP SDK tools | Only completed, attributed native assertions establish evidence for the cases run |

The independent models deliberately simulate broken implementations. Examples
include a setter returning normally without changing data, a record edit leaking
into another instance, worksheet insertion shifting the wrong cells, and an
object translation producing the wrong geometry. Modeling tests also use
independent volume partitions for solid booleans and a NURBS model with a
nonstandard knot domain; copied objects that alias their source, reversed
subtraction and incorrect curve parameters fail their readbacks. Annotation and
resource models check character runs, worksheet edge topology, resource identity
and preservation of control objects. These are tests of the fixture oracles and
transport contracts, not substitutes for Vectorworks' geometry or rendering
engines. A setter's successful return alone does not prove its effect.

Compatibility replacements and uncertain requests are separate evidence kinds.
In particular, the disclosed `HArea` fallback is not proof that native `HArea`
returned a valid area, and the local ASCII `UprString` replacement is not native
`UprString` verification. A timeout or host exit never becomes a native pass.

## Run the offline suite

Use Python 3.12 from the repository root. In a virtual environment:

```text
python -m pip install -r mcp-server/requirements.txt
python -m unittest discover -s tests -v
python tools/pruefe_konsistenz.py .
python tools/sdk_test_matrix.py --check
python tools/api_coverage.py --check
python tools/check_repository.py
```

Installing the server requirements enables the real FastMCP registration tests;
without them, those tests can report a skip. The scheduler's small C++ policy
compilation test requires Windows and the exact configured MSVC toolchain. It
skips when those prerequisites are absent. This does not build or certify the
Vectorworks plug-in binary.

Reports include source hashes. A stale-report failure requires reviewing the
underlying changes, then regenerating and rechecking the reports:

```text
python tools/sdk_test_matrix.py
python tools/api_coverage.py
python tools/sdk_test_matrix.py --check
python tools/api_coverage.py --check
```

Do not edit expected results or regenerate evidence merely to remove a failure.
Preserve recorded host outcomes, including failures and uncertain requests.
SDK source regeneration checks described in [AGENTS.md](../AGENTS.md) additionally
require an authorized local SDK extraction; the offline CI does not fetch it.

## Select native fixture families

The registry is the authoritative list:

```text
python tools/sdk_regression_suite.py --list
```

The semantic fixture families are listed below; characterization families have
a separate table and never receive semantic API coverage credit.

| Provider | Family names | Main cases |
|---|---|---|
| `design` | `attributes`, `line`, `polygon`, `text`, `worksheet`, `records`, `resources`, `solid` | Basic creation and independent edit/readback workflows |
| `numeric` | `scalar_math`, `vector_math`, `coordinate_math`, `string_edges`, `string_encoding` | Known numeric results, transformations, string boundaries, and exact UTF-8 byte/UTF-16 unit counts |
| `geometry` | `geometry_rectangles`, `geometry_ovals`, `geometry_arcs`, `geometry_lines`, `geometry_polygons`, `geometry_loci`, `geometry_poly3d`, `geometry_extrudes`, `geometry_nurbs`, `geometry_harea`, `geometry_arc_repair_geometry` | Analytic geometry, movement and preservation, construction and later measurements, independently measured repaired arc geometry |
| `data` | `data_attributes`, `data_records`, `data_worksheet_values`, `data_worksheet_classification`, `data_worksheet_boundaries`, `data_worksheet_format`, `data_worksheet_structure`, `data_materials`, `data_resource_tags`, `data_worksheet_database`, `data_worksheet_operators`, `data_worksheet_edge_edits` | Opacity boundaries, Unicode and empty records, instance isolation, worksheet ranges/formatting/structural edits, database criteria, formula operators, edge edits, materials and tags; disputed predicates are separate diagnostics |
| `annotation` | `annotation_text_runs`, `annotation_text_layout`, `annotation_text_styles`, `annotation_text_replacements`, `annotation_ws_borders`, `annotation_ws_images`, `annotation_text_leading_sentinel`, `annotation_ws_border_clearing`, `annotation_unicode_length`, `annotation_text_utf16_runs`, `annotation_text_utf16_lengths` | Per-character formatting and preservation, UTF-16 offsets and lengths, text layout/style identity, substring edits, worksheet edge topology and worksheet-image/source relationships; retained diagnostic families remain separate |
| `resource` | `resource_symbols`, `resource_textures`, `resource_lights`, `resource_light_defaults`, `resource_gradient_segments`, `resource_gradient_opacity`, `resource_gradient_aggregate_opacity` | Fresh definitions and instances, texture identity and documented extrude-part assignments, explicit light properties, gradient edits and untouched control objects; default brightness is diagnostic |
| `modeling` | `modeling_bounds`, `modeling_rounded`, `modeling_oriented_primitives`, `modeling_duplicates`, `modeling_planar_conversion`, `modeling_primitive_solids`, `modeling_extrude_info`, `modeling_nurbs_sampling`, `modeling_csg`, `modeling_centroid_units`, `modeling_nurbs_distance` | Analytic bounds and areas, copy/source isolation, replacement handles, spheres/cones, absolute rotation and resize, captured NURBS parameters, positive-overlap solid booleans and documented millimetre centroids; unresolved NURBS distance remains diagnostic |

Pass a qualified name, such as `data:data_records`, to `--family`. Repeat the
argument to select several families. The registry plan generator includes the
full registry when selection is omitted; the batch runner described below
excludes diagnostic and characterization families by default.
Families create their own prerequisites; captures are namespaced to avoid
cross-family collisions. Each fixture records additional prerequisites, such as
Arial for worksheet font tests or no automatic Data Manager record attachments
for record-count assertions. Review these before executing a plan.

Object/resource identity names use `fixture_name(prefix, run_id)`: ASCII names
of at most 60 characters are unchanged; longer names retain a readable prefix
and a 16-character hash of the complete identity. This prevents the observed
63-character native name truncation from removing run identity or merging
fixtures. It is a fixture naming convention, not a universal SDK string limit.
Unicode, empty and long content strings remain separate test inputs.

Annotation character-run tests require both Arial and Courier New under those
exact names and check positive font IDs before assignment. Text offsets are
zero-based; font size and leading are in points. Border tests use reviewed solid
and none styles, a documented palette index and a fixed weight, with no imported
dash resource. Worksheet images are created from each family's own worksheet;
no image file or resource picker is used.
Routine border cases use a fresh worksheet for each side or topology and check
every sampled cell's baseline before editing. They do not assume that clearing
a larger range removes an existing smaller outline. The disputed clear case
is retained separately and checks the corners before the next border setter.

Resource fixtures use fresh symbol definitions, textures, lights and control
objects; they do not change the active symbol, class, layer or document defaults.
Texture assignment checks resource identity and preservation, not rendered
appearance. Light round trips do not certify photometric units or rendering.
Modeling families require an active design layer in Top/Plan and only modify
fresh named fixtures. NURBS piece/degree/control/knot counts are checked before
indexed access, and parameters are captured rather than assuming a unit knot
domain. Solid boolean inputs have a strictly positive overlap; tangent,
degenerate, self-intersecting and arbitrary imported solids are not covered.
Replacement/consumed handles are not reused after conversion or booleans.
The routine `modeling_centroid_units` fixture uses `ValidNumStr` with explicit
millimetre suffixes to construct its inputs and checks `Centroid`'s documented
millimetre outputs. It does not change the drawing's units. Independent offline
inch/mm/cm/metre models detect accidental dependence on the current unit;
the corrected fixture passed its fresh native run.

`data:data_worksheet_boundaries` isolates a documented boundary discrepancy:
SDK 3200's reference XML and legacy API header describe worksheet validity
bounds including zero, while host build 882075 returned `False` for `(0, 0)`.
The original failure is retained. The boundary family runs normal corners and
outside-dimension cases before the disputed zero cases, preserving the SDK
expectation. Ordinary worksheet value tests are independently runnable. This is
an unresolved documentation/host mismatch, not a corrected native implementation.

`data:data_worksheet_classification` retains the numeric-not-string expectation
for a numeric formula. Host build 882075 returned `True` for both
`IsWSCellNumber` and `IsWSCellString` after `=6*7` evaluated to 42. The stored-value
classification contract remains unresolved; the ordinary worksheet value family
does not depend on that disputed predicate. Both classification and boundary
families are diagnostic-only. They are not silently adjusted to match the host.

The eight semantic diagnostic families excluded from default batches are:

| Qualified family | Preserved expectation or unresolved assumption |
|---|---|
| `data:data_worksheet_boundaries` | SDK comments include zero indices; the host rejected `(0, 0)` |
| `data:data_worksheet_classification` | A numeric formula value should not also classify as a stored string |
| `annotation:annotation_text_leading_sentinel` | SDK comments specify `-1.0` with no custom leading; three native requests verified the guarded compatibility repair for modes 2, 3 and 4, preserving original `0.0` responses; the family stopped later on an unclaimed job |
| `annotation:annotation_text_styles` | Clearing a substring's style should preserve neighboring style references |
| `annotation:annotation_ws_border_clearing` | Clearing an enclosing range should remove a previously drawn smaller outline; stale corners are checked before any subsequent setter |
| `annotation:annotation_unicode_length` | Exact Unicode replacement text has 12 code points/UTF-16 units; the host returned 18, matching UTF-8 bytes |
| `resource:resource_light_defaults` | SDK documents 75% default brightness; the fresh light reported 100% |
| `modeling:modeling_nurbs_distance` | Distance output units differ from the fixture's coordinate-distance expectation |

Characterization families require an explicit `--family`, even when
`--include-diagnostics` is supplied. Broad return-contract checks capture
observations without declaring disputed semantics correct. Their saved plans
and results cannot be imported as semantic native or compatibility passes.

| Qualified family | Observation purpose |
|---|---|
| `geometry:geometry_arc_characterization` | Compare documented degree-valued arc edits across constructors, numeric types and reset variants |
| `geometry:geometry_arc_geometry_characterization` | Independently inspect arc geometry after edits, including converted curves and perimeter |
| `data:data_worksheet_type_probe` | Compare stored values, formulas, displayed values and worksheet type predicates |
| `data:data_worksheet_validity_probe` | Compare header, boundary, cell and range validity predicates |
| `annotation:annotation_text_length_encoding` | Distinguish Unicode code-point, UTF-16 and UTF-8 length observations |
| `annotation:annotation_text_offset_units` | Establish the binding's formatting-offset units independently of text length |
| `annotation:annotation_text_style_scope` | Compare substring style references with effective font readbacks |
| `annotation:annotation_text_style_size_scope` | Compare substring style size, preserved neighbors and resource-update propagation |
| `annotation:annotation_ws_border_scope` | Observe legacy range clearing before explicit edge clearing |
| `resource:resource_light_default_probe` | Observe all three light kinds before explicit initialization and independent property/control-object readbacks |
| `resource:resource_gradient_opacity_probe` | Preserve the original dedicated-setter side-effect diagnosis; this historical probe is not a repair verification |
| `modeling:modeling_nurbs_distance_characterization` | Compare physical millimetre query points, both curve directions and endpoints |
| `modeling:modeling_curve_bounds_characterization` | Compare oriented constructors, rotation and reset against tight-curve and enclosing-rectangle bounds |

There are thirteen characterization families. Diagnostic selection preserves
the original expectations and failed evidence.
It does not repair native behavior or authorize retrying uncertain mutations.
Routine cases instead set explicit values or use independent objects where
the disputed default or prior state is irrelevant. New mismatches can still
occur in routine families: a later Unicode replacement returned the exact
expected text, while `GetTextLength` returned 18 for a 12-character string,
matching its UTF-8 byte length. The SDK's generic string-length description
does not settle that encoding-unit question; it is not a failed replacement.
The original 12-character expectation is retained in `annotation_unicode_length`;
later native formatting probes established UTF-16 indexing and the guarded
adapter now discloses its correction of the native UTF-8 byte count.
Routine replacement checks still require the exact Unicode output and can
continue to adjacent matches, expansion and last-character cases independently.

## Generate a plan without connecting

This command creates a new JSON file and validates every planned call against
the SDK index, adapter contract, and background policy. It does not connect to
Vectorworks, create a document, or execute native functions. The Windows
document path is a guarded target string even when generating the plan on Linux.

```text
python tools/sdk_regression_suite.py --document "C:\SDK-tests\VWX-MCP-SDK-TEST-regression.vwx" --run-id review-001 --family data:data_records --output regression-plan.json
```

The output path must not already exist. Review `jobs`, `prerequisites`,
`assertions`, `verifies_jobs`, `source_sha256`, and `fixture_source_sha256` in the
plan. `verifies_jobs` links a later readback to the mutation it checks. Creation
and regeneration-dependent inspection remain separate menu invocations.

## Check background request delivery

The separate delivery checker sends up to 100 sequential read-only typed
`GetVersionEx` requests with uncached background MCP settings. It compares
all eleven deployment hashes, records each request/result, and checks posting
and completion telemetry. It stops on the first failure without replay and
awards no semantic SDK API credit. Leave another application naturally in
the foreground; the checker does not move focus or independently measure the
desktop foreground process.

```powershell
python tools/check_sdk_background_delivery.py --execute `
  --plugin-dir 'C:\Users\YourName\AppData\Roaming\Nemetschek\Vectorworks\2027\Plug-ins\VWX-MCP' `
  --output-dir '.audit\delivery-check-next' `
  --count 100
```

The checker requires V4 (`sdk-named-menu-broker-ack-v4`), including matching
private-event, SDK-invocation, return and outer-completion counts. An SDK return
code is diagnostic and never substitutes for the Python runner's completion.
V3 or older telemetry is rejected before a request is sent.

The output directory must be new. Omit `--execute` to write only a pending
plan; use a different new directory for a later deliberate execution. A
requested count of 100 is not a record of 100 successes.

The installed V3 attempt saved at
`.audit/delivery-v3-20260926-b/result.json` requested 100 reads and stopped
on the first: `VW_JOB_UNCLAIMED`, `dispatched=false`. The scheduler reported
`frame_menu_unavailable` because the frame had no usable `GetMenu` handle.
It posted zero triggers and completed zero native calls. Background delivery
remains unverified for that build; this is a blocked scheduler route, not a
failed `GetVersionEx` result. See [BACKGROUND_WORK.md](BACKGROUND_WORK.md).

## Execute an explicitly selected native run

Native execution requires Vectorworks 2027 on Windows and the matching deployed
bridge. Save and activate a disposable drawing named
`VWX-MCP-SDK-TEST-*.vwx`, on a design layer in Top/Plan. Keep Vectorworks open and
unminimized with the bridge open and unpaused. The current active document must
match the exact absolute path supplied to the runner.

The runner uses ordinary `sdk_call` and `sdk_sequence` tools over stdio MCP with
`VWX_BACKGROUND_MODE=1`, file transport, disabled read caching, and the explicitly
selected plug-in directory. It does not use desktop automation, arbitrary
scripts, or a direct file-IPC bypass of MCP policy. It does not start or restart
Vectorworks, open drawings, change application focus, or dismiss dialogs.

An example PowerShell invocation, after replacing the two absolute paths with
the actual disposable drawing and installed plug-in folder:

```powershell
python tools/run_sdk_regression.py --execute `
  --document 'C:\SDK-tests\VWX-MCP-SDK-TEST-regression.vwx' `
  --plugin-dir 'C:\Users\YourName\AppData\Roaming\Nemetschek\Vectorworks\2027\Plug-ins\VWX-MCP' `
  --output-dir '.audit\native-regression-001' `
  --run-id native-001 `
  --family data:data_records
```

`--execute` is required to connect to the host. Without it, this command only
writes a validated `plan.json` into a new output directory; it does not inspect
the installed plug-in or call Vectorworks. Use a different new output directory
for a later deliberate live run.

Use a new run ID, output directory, and unique fixture names for each deliberate
run. The runner builds and validates a fresh plan from the selected families;
it does not execute an arbitrary previously edited plan file. Review the printed
family list and use a small family first. The `--timeout` option controls the
bounded tool wait; increasing it does not authorize a retry.

The output directory contains `plan.json`, `provenance-intent.json`,
`provenance-response.json`, the append-only `journal.jsonl`, and `result.json`
when the runner completes normally. The typed `GetVersionEx` prelude records the
actual Windows app version and build before fixture execution. It receives no
fixture coverage credit. `result.host` contains that measured app identity;
`result.sdk` records the verified catalog's SDK identity. Fixture/runner and
deployed-source hashes are checked before the MCP client is started.

A failure before final result writing can leave only the files written up to
that point. Intents are flushed before sending requests. The runner checks the
exact document, host version, and deployed source hashes and stops on failed or
unconfirmed execution. Inspect the last journal or provenance record and bridge
diagnostics if the process exits or a result is missing.

No run is automatically resumed or replayed. A request may have mutated the
drawing even when no response arrived. Inspect the drawing and existing journal
before planning a new run; a new output directory alone does not make replaying
the same mutation safe. Fixture objects and resources remain in the disposable
drawing for inspection. The runner is not a transaction or rollback mechanism.

## Run independent families as a sequential batch

`run_sdk_regression_batch.py` prepares one separately guarded plan and fresh run
ID per selected family. It validates every plan before any host connection. By
default it writes pending plans only. For example:

```powershell
python tools/run_sdk_regression_batch.py `
  --document 'C:\SDK-tests\VWX-MCP-SDK-TEST-regression.vwx' `
  --plugin-dir 'C:\Users\YourName\AppData\Roaming\Nemetschek\Vectorworks\2027\Plug-ins\VWX-MCP' `
  --output-dir '.audit\batch-review-001' `
  --run-id batch-review-001 `
  --family modeling:modeling_bounds `
  --family annotation:annotation_text_runs
```

The output directory must be new. After reviewing the plans and prerequisites,
use a separate fresh output directory and run ID and add `--execute` to request
actual typed MCP execution. The planning command does not inspect its plug-in
path. Native batch execution still requires the active disposable document,
matching deployment hashes and measured host provenance used by the single-run
runner; it does not open the drawing or take application focus.

With no `--family`, the batch selects the current routine families and excludes
those declared diagnostic or characterization. An explicit `--family` opts into that family,
including a diagnostic family. `--include-diagnostics` adds diagnostic families
to the default selection but never adds characterization families. It does not bypass their prerequisites or make known
uncertain cases routine-safe. Review those cases deliberately before opting in.

Each family stops on its first failed assertion. The batch may proceed to a
different independent family only after a complete, attributed successful SDK
response contains a measured semantic mismatch. It rechecks that response,
assertions, captures and provenance against the exact plan; a recorded failure
label alone does not authorize continuation. Native exceptions, transport errors,
timeouts, malformed or partial responses, document/source guard failures, or
unavailable bridge readiness stop the batch. A heartbeat that later resumes
does not automatically restart it.

Between families, fresh active scheduler diagnostics may briefly lag a returned
result. With an empty actual queue, the batch allows up to three seconds of
read-only polling for pending completion, legacy modifier-restoration indicators and queue-count
telemetry to settle. It sends no new job during that wait and records its
observations. A paused or stale bridge, queued job, or expired wait stops the
batch; no fixture is retried.

`batch-plan.json` records the selection and per-family directories; `plans/`
retains every exact plan, including families never reached. Execution writes a
readiness snapshot before each family, each started family's normal
`plan.json`, provenance files, `journal.jsonl` and `result.json`, and a
`batch-result.json` summary with pending families. If interrupted, inspect the
files that exist; a missing result is not evidence of no mutation. Neither a
saved plan nor an incomplete result is automatically replayed. Import reviewed
per-family `result.json` files individually, preserving their failures and
uncertain outcomes. The batch summary itself is not native API evidence.

**Multiple agents sharing one Vectorworks instance are not isolated.** Document
guards and mutations are separate requests, so switching the active document
between them creates a race. Serialize native test runs and document ownership;
do not have another agent or user switch drawings, edit the test geometry, or
change Vectorworks state during the run. The user can continue using other
applications while the background bridge operates.

Record passing, failed, uncertain, and compatibility results separately when
importing reviewed native evidence. A successful family verifies its assertions
for that drawing and app build. It does not verify unexecuted families, all
APIs, every object type, or every boundary case.

## Import reviewed results and regenerate reports

The current [saved-run report](REGRESSION_RESULTS_2027.json) contains 141 runs:
7,387 planned jobs, 5,519 executed, 4,884 passed, 28 failed and 607 characterization
observations, with two separately blocked requests. Its 1,866 remaining entries
belong to historical plans, including repeated and stopped fixtures; that number
is not the current unique backlog. Native API cases in `LIVE_SDK_2027.json` use
a different unit and can outnumber jobs because a sequence calls several APIs.

Inspect the original `plan.json`, `result.json` and journal before importing. Keep failed assertions,
uncertain outcomes and incomplete sequences intact. The importer validates the
measured host and SDK identities, runtime and fixture source hashes, API names,
response identities and row statuses. It binds ordered requests, resolved capture
arguments and assertion declarations to the original saved plan, then recomputes
every assertion against the response. Changing an expected value in a result
cannot create pass credit. Partial or uncertain sequences do not earn
credit for unexecuted calls, and compatibility replacements never earn native
pass credit.

From the repository root, with the reviewed run's actual output directory:

```text
python tools/import_sdk_regression.py .audit/native-regression-001/result.json
python tools/sdk_test_matrix.py
python tools/api_coverage.py
python tools/sdk_test_matrix.py --check
python tools/api_coverage.py --check
```

The importer defaults to `docs/LIVE_SDK_2027.json`; `--evidence` selects another
existing evidence file. That file must describe the same measured host and SDK.
The original plan defaults to the result's sibling `plan.json`; `--plan` selects
its explicit location. Missing or mismatched plans are rejected before evidence
is written. Plan hashes are retained in the imported run's audit metadata.
An identical import is idempotent. Conflicting run IDs or API/case identities
are rejected instead of overwriting prior evidence. The import preserves Unicode
and writes validated JSON atomically. Source-hashed matrix and coverage reports
must be regenerated after the evidence changes. The importer cannot establish
that someone has truthfully recorded a native response; reviewed runner journals
and their source provenance remain part of the evidence.

## Continuous integration

[offline-tests.yml](../.github/workflows/offline-tests.yml) configures Python 3.12
on Windows and Linux. It installs the server requirements, runs the offline
unittest suite, checks handwritten contracts and reproducible reports, and
generates pending single and batch plans without connecting. Repository `.gitattributes`,
LF JSON output and checkout settings preserve bytes for source-hash checks on
both platforms. Test logs and the pending plans are uploaded as
diagnostic artifacts.

The workflow never passes `--execute` and requires no Vectorworks
installation, SDK archive, license, or developer credentials. A green CI result
is offline verification only. Adding this workflow does not mean either hosted
job has run; consult the repository's Actions run for actual platform results
and skips.
