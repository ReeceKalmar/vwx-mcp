# Vectorworks 2027: current contract

This fork targets **Vectorworks 2027 on Windows**, using **SDK 3200, build
882699**. Recorded native tests use app build **882075**. Start with
[build and setup](BUILD_SETUP.md), [architecture](ARCHITECTURE.md), and
[SDK adapter usage](SDK_ADAPTERS_2027.md). [INDEX.md](INDEX.md) maps the remaining
documentation; subsystem `AGENTS.md` files identify the implementation boundaries.

## Verified status

This is a working bridge for scoped background operations, with incomplete
verification of full unattended design delivery. Successful API adapters,
offline tests and individual native objects do not establish a complete
landscape/house project, its sheets, save/reopen persistence or crash recovery.

| Workflow | Evidence boundary |
|---|---|
| Typed background delivery | Verified scoped runs; Vectorworks must stay open, unminimized and unpaused |
| Native straight Walls, Roof Faces and modern Slabs | [Scoped architectural cases](NATIVE_ARCHITECTURE_2027.md); complex configurations and retained geometry failures remain |
| Native Hardscape, Landscape Area, Plant and site-model workflows | Complete intended workflows still need separate verification |
| Unattended multi-project delivery and unexpected-crash recovery | Not yet established; controlled restarts and existing-file transitions are separate capabilities |

The [design workflow](DESIGN_WORKFLOW.md) defines ownership, useful work during
pauses and focused recovery handoffs. It is operating guidance, not a newly
implemented automatic recovery service. [Current offline validation](TESTING_2027.md#current-offline-checkpoint)
owns the latest suite results; [publication history](PUBLICATION_2027.md) and
the testing guide retain earlier checkpoints.

The native baseline passed the complete default selection:
**57 routine families / 2,303 unique fixture jobs**.
[LIVE_DEFAULT_SUITE_2027.json](LIVE_DEFAULT_SUITE_2027.json) independently checks
the original plans, responses, assertions, guards and provenance across fresh
batches. Its 2,343 successful executions include 40 repeated partial-family jobs;
repetitions are not extra unique coverage. Eight semantic diagnostic families and
thirteen characterization families are outside the default selection.

All **3,098 SDK Python names** have generated adapters. Handwritten workflows use
465 SDK functions; the default MCP inventory is 287 handwritten plus 3,098 SDK
tools. Current evidence confirms native results for **401 APIs**, with native
passes for 399; **2,697 remain unconfirmed**. The 5,756 native passing cases,
26 preserved failures, one uncertain attempt, 70 compatibility passes across
eight APIs and seven separate adapter checks are different evidence categories.
See [TOOL_COVERAGE.md](TOOL_COVERAGE.md) for generated counts and limitations.
No API is claimed to have every input, lifecycle or native semantic edge tested.

The installed Windows scheduler is `sdk-named-menu-broker-ack-v4`. The latest
recorded native deployment adds SDK-backed document inventory and guarded
document transitions; see [transition evidence](DOCUMENT_TRANSITION_2027.json).
It retains the English palette and atomic diagnostic publisher from the
[second verified maintenance cycle](MAINTENANCE_ENGLISH_ATOMIC_2027.json).
Native library SHA-256:
`0291e0b8ee1b0bdd033b90dfb6745999a0c8208c15f8adfb1571992d868506cf`.
Resource archive SHA-256:
`ab795ef6049454e4aa499b9624e788bc43091708eceada14890d1c7d58595ee2`.
These identify the recorded deployment, not a promise that a different
installation has the same files. Check actual source/deployment hashes before
live work. [Maintenance](MAINTENANCE_2027.md) and
[native investigations](NATIVE_REPAIRS_2027.md) retain earlier deployment history.
The separately deployed [wall repair](WALL_CREATION_2027.json) verifies one
unstyled native Wall's requested dimensions in a disposable drawing. It does
not establish every styled/component configuration or add SDK coverage credit.

## Execution contract

- Use the local file transport under the **2027 user Plug-ins/VWX-MCP** folder.
  Set `VWX_TRANSPORT=file`, `VWX_VW_VERSION=2027`, `VWX_PLUGIN_DIR` explicitly,
  and `VWX_CACHE_TTL=0` for verification. Legacy TCP/watchdog execution is not
  supported. MCP stdio or HTTP is separate from the Vectorworks file queue.
- Every read and write runs through the fixed **VWX Bridge Start** Python menu
  command. The UI-thread broker calls the SDK named-menu route; no Python runs
  from a native timer, notification or web callback. One invocation dispatches
  at most one queued job. `pump_readonly()` is a compatibility no-op.
- Keep Vectorworks open, unminimized, with the bridge open and unpaused. Typed
  background design needs no mouse, screenshot, global keyboard event or focus
  change. `VWX_BACKGROUND_MODE=1` rejects known interactive/raw-script routes
  before publication, including every batch/sequence member. `options.force`
  does not bypass that policy. See [background operation](BACKGROUND_WORK.md).
- Separate creation/reset and regeneration-dependent inspection into different
  requests. A `vwx_batch` or `sdk_sequence` remains one job; it provides neither
  a regeneration boundary nor rollback. A completed menu invocation does not
  prove every deferred native object has regenerated.
- `GetBBox` and handwritten `bounds` are screen-plane projections, not world
  extents. A zero screen box alone does not prove missing geometry. Validate a
  native Wall using its endpoints and independent 3D spans/center, together with
  parameter readbacks and layer placement; see [Wall findings](NATIVE_REPAIRS_2027.md#wall-screen-bounds-and-model-geometry).
- A claimed job is consumed before dispatch and never automatically replayed.
  Inspect uncertain results and the actual document before any new mutation.
  Never forge completion stamps, clear an unknown lease or auto-dismiss dialogs.
- Clients share the active drawing. Guards and mutations are separate jobs, so
  the queue is not per-agent isolation. Coordinate document ownership and
  serialize workflows on different files; background mode blocks document
  switching whose fallback can change application focus. The separate lease-owned
  `bridge_maintenance` transition stages an SDK save/open/switch after menu return
  and requires independent inventory confirmation before release; see
  [guarded transitions](MAINTENANCE_2027.md#guarded-document-transitions).

## SDK and object discipline

Prefer a handwritten workflow, then an exact `sdk_Name` or `sdk_call` contract
discovered through `sdk_list`. Transport handles are object UUIDs. Resolve and
validate them before native calls; a type-zero `GetObject` dummy is not a valid
object. Preserve tuple arguments and documented in/out conventions. Collect
handles before modifying objects found by an iterator, bound traversal, and
check each nested child's actual parent. Resource imports, conversions and
booleans can replace handles; use the returned UUID for later requests.

All generated bindings exist, but 173 APIs still lack a supported workflow.
Native pointers, transient handles, tool/PIO events and unsupported callbacks
cannot be fabricated from JSON. `SetControlData` has a controlled dialog-handler
route, not an ordinary menu-job call. Known interactive workflows remain blocked
in background mode. `Layer` and `CombineIntoSurface` are quarantined; a force
option only addresses their explicit quarantine, never other checks.

The effective `GetGradientDataN` return has six numeric outputs. The generator
retains the conflicting original SDK declaration and hashed evidence rather
than inventing a Boolean. Native NIL wrappers are accepted only when exact type
and equality match a constructed native null. Text formatting uses UTF-16
offsets, not Python code-point or grapheme counts. See
[adapter contracts](SDK_ADAPTERS_2027.md) and [repair evidence](NATIVE_REPAIRS_2027.md).

Compatibility responses must remain disclosed. `HArea` falls back to `HAreaN`
only after native `None`; ASCII `UprString` is a local replacement and Unicode
is unsupported. Never retry the uncertain native uppercase binding. Build-gated
leading, opacity flags, material status, text length, gradient opacity and arc
repairs keep independent preconditions/readbacks and unknown-build behavior.
The broken gradient setter is bypassed before any write; the arc helper requires
its private ABI and preserves the original UUID. Compatibility success is not a
native pass for the replaced binding.

Native Hardscape, Landscape Area, Plant PIO, wall, roof and site-model workflows
need separate disposable-file verification. `create_plant` inserts an existing
symbol; it does not promise a native Plant PIO. A newer SDK or successful build
does not establish a crash fix, safe geometry or complete regeneration.
Scoped [architectural cases](NATIVE_ARCHITECTURE_2027.md) verify native Roof Face
and modern Slab creation/edits and several straight-Wall joins, while retaining
the roof size-getter discrepancy and a failed near-collinear join. Their local
operational evidence does not increase the imported SDK coverage counts.

## Build and generated artifacts

Build `native/VwxBridge2027.vcxproj` through `tools/build_2027.py` with MSVC v143
14.42, C++20 and native `wchar_t`. Keep the SDK 3200 compile-time assertion and
separate `native/Output/2027/Release` output. Never overwrite a loaded native
binary. Use [BUILD_SETUP.md](BUILD_SETUP.md) for the reproducible build/deploy
sequence and [MAINTENANCE_2027.md](MAINTENANCE_2027.md) for guarded restarts.

The index and adapters come from the official SDK `vs.py`; regenerate them with
`build_vs_index.py` and `build_sdk_wrappers.py`, preserving provenance metadata.
Do not hand-edit generated JSON/wrappers or commit the SDK, credentials, binaries
or drawings. Relative to the inspected upstream revision
`0a2f554a15ddddf0d43dc9d251d90a42146c9363`, the 2027 index adds 28 names and removes
`Prot_GetLicenseType`, with no changed argument lists among shared names.
Older upstream findings remain Git history, not 2027 test evidence.

## Recorded native cases

The [normalized live record](LIVE_SDK_2027.json) retains exact successful,
failed, compatibility and uncertain API cases. [NATIVE_REPAIRS_2027.md](NATIVE_REPAIRS_2027.md)
is the current diagnosis; [REGRESSION_FINDINGS_2027.md](REGRESSION_FINDINGS_2027.md)
preserves the dated earlier checkpoint. Unresolved worksheet predicates/borders,
text-style propagation and NURBS distance assumptions remain explicit diagnostics.
Historical failures are not erased when a corrected fixture or repair passes.

The [saved-run report](REGRESSION_RESULTS_2027.json) sums historical plans,
including repeated/stopped runs; its remaining count is not the unique backlog.
Only reviewed, plan-bound results are imported. The final default-suite save
succeeded and the bridge returned to fresh idle state in process 50236; that
operational result is not additional API coverage or an independent focus test.
Use [TESTING_2027.md](TESTING_2027.md) for plans, offline tests, native execution,
strict evidence import and report regeneration.
