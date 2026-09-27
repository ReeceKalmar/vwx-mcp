# Native failure investigation

These findings concern Vectorworks 2027 for Windows, app build 882075 and SDK
3200 build 882699. Original failures remain in the saved evidence. A repair's
offline tests are separate from its subsequent native verification.

The final 2026-09-27 default selection passed all **57 routine families and
2,303 unique fixture jobs** across fresh batches A/B/C; see the
[independent default-suite audit](LIVE_DEFAULT_SUITE_2027.json). There were
2,343 passing executions, including 40 extra partial-family passes before a
fresh run. All original failures remain preserved. Diagnostic and
characterization families remain separately selected, so this result does not
resolve the worksheet predicate/border and text-style propagation questions.
Current native evidence records 5,756 passes, 26 failed assertions and one
uncertain attempt; 401 APIs have confirmed native results, 399 have native
passes, and 2,697 remain unconfirmed. The 70 compatibility passes across eight
APIs and seven adapter rejection checks remain separate.

## Wall creation: inherited components and ignored setter failures

The [wall workflow record](WALL_CREATION_2027.json) preserves a separate
2026-09-27 disposable-file investigation. In a drawing measured in inches,
`create_wall` requested height 3 and thickness 0.5 but reported success while
later native getters returned height 120 and thickness 6. The wall was unstyled
with one inherited component. `Wall` adopts document defaults, and the SDK
explicitly excludes component walls from `SetWallThickness`'s contract. The
wrapper ignored setter failures. A separate `SetWallHeights` diagnostic returned
`SDK_RESULT` (non-Boolean result, dispatched); its raw native value was not
captured and must not be called `None` or success. Later heights remained 120.
`DeleteAllComponents` returned false. Neither failed diagnostic was retried,
and the planned component insertion was not dispatched.

The corrected constructor changes only its newly created type-68 UUID. It
preserves inherited components/materials and scales component widths to the
requested total using `SetComponentWidth`, requiring exact native success and
parameter readback. It uses `SetWallOverallHeights` with bottom/top bound to
layer Z at offsets 0/height, then resets. It does not change global wall defaults
or use the failed height/deletion routes. A partial failure returns its UUID,
phase and dispatch state; it never deletes or recreates the wall automatically.
Creation reports `geometry_verified=false` and requires a later inspection job.

After the atomic Python-source deployment under a maintenance lease, a fresh
unstyled, one-component wall returned the requested 3-inch height and 0.5-inch
thickness within `1e-8` in a separate `get_walls` job. The active document and
complete open-document inventory remained unchanged. Native evidence is limited
to that case: styled and multiple-component branches have offline tests only;
zero-component creation is rejected, and save/reopen persistence was not tested.
Eighteen wall tests and the 918-test offline suite passed (one skip). The linked
record pins deployment/source hashes and preserves the earlier failures; this
operational observation has not increased the SDK fixture coverage totals above.

## Wall screen bounds and model geometry

A separate 2026-09-27 read-only reconciliation found an existing straight
Wall with accepted parameters and an all-zero `GetBBox`. Its native
`GetSegPt1/2` endpoints, `Get3DInfo` spans and `Get3DCntr` center matched
independently calculated geometry in a feet-based drawing. The SDK defines
`GetBBox` as a projection on the screen plane and describes wall bounds as a
derived attribute. Treating its zero result as proof of absent model geometry
was therefore an invalid verification rule in this case.

Use endpoint/path-type checks and independent 3D size/center expectations in
later jobs, alongside wall levels, thickness and layer elevation. The measured
`Get3DInfo` outputs were Y/X/Z spans, despite their `height/width/depth` names.
This does not establish the same interpretation for every object type or
transform. The exact native cause of the zero screen box remains unresolved;
no reset, recreation, view change or geometry mutation was needed to reconcile
the Wall. Its intended final layer/elevation and save/reopen persistence were
not established by this check.

The private reconciliation retained seventeen typed read jobs and one local
lease-status action, with exact per-job scheduler deltas, four unchanged open
file identities and all eleven source/deployment hashes unchanged. It adds no
SDK fixture coverage credit. Client drawings, coordinates and raw journals
remain outside the published repository.

## Confirmed causes and bounded repairs

- **Opacity flags:** four combinations of `SetOpacityByClassN` were compared
  with `GetOpacityN` and the class's opacity. Effective pen/fill values showed
  that the setter works in the documented order. `GetOpacityByClassN` returns
  the two flags in reverse order on this build. The adapter corrects only the
  exact measured Windows build and discloses the original pair. Unknown builds
  retain native output; invalid shapes remain errors.
- **Material name status:** a new type-19 material was assigned to a new
  rectangle. `GetObjMaterialHandle`, `GetTypeN` and `GetName` confirmed its
  identity, while `GetObjMaterialName` returned `(False, correct_name)`. The
  adapter corrects that status only when a separate resource lookup confirms
  the same name, material type and valid UUID. Empty names, wrong resource
  types, mismatches and helper failures cannot produce invented success.
- **Null handles:** an unassigned object's `GetObjMaterialHandle` returned a
  native type-0 wrapper that the JSON adapter rejected. SDK `vs.py` documents
  `vs.Handle()` as a native NIL representation in `WSScript_GetObject`. The
  adapter now accepts an output wrapper only when it has exactly the native
  null's type and compares equal to a separately constructed native null.
  Falsiness and type zero alone never establish NIL. Batch F verified this
  native equality path on a fresh unassigned object; all 30 material jobs passed.
- **Text leading:** SDK documentation specifies `-1` for noncustom spacing;
  this Python binding returns zero. The adapter uses `GetTextSpace` to confirm
  a noncustom mode before correcting that sentinel. Custom zero and other
  legitimate native values remain unchanged. The response identifies the
  independent getter and original value.
- **Centroid units:** SDK documentation explicitly specifies millimetres for
  `Centroid`. The old test assumed drawing units. Its replacement constructs
  signed, asymmetric geometry from explicit millimetre inputs and checks the
  documented physical coordinates. Independent offline inch/mm/cm/metre
  models verify that the fixture does not depend on the drawing's unit setting.

The adapter corrections above have focused positive and adversarial tests.
Batch E subsequently completed the text-leading, opacity/attribute and assigned
material families: 16, 38 and 28 jobs respectively. Compatibility responses
disclose the original outputs and count separately from direct native passes.
Its centroid fixture passed all 31 jobs with explicit physical-unit geometry.
Batch F separately passed the new unassigned-material probe.

`GetGradientDataN` stopped batch E after 18 successful gradient-opacity jobs:
the SDK Python docstring declares seven outputs including a Boolean, while
its VectorScript procedure and executable stub declare six output values.
A separate read-only native probe returned exactly six values; the legacy
gradient getter independently confirmed position, midpoint and RGB, and
`GetGradientOpacity` confirmed opacity. The generator now corrects this exact
SDK 3200/build 882699 declaration, preserving its original signature and
[hashed evidence](GRADIENT_RETURN_2027.json). It rejects declaration or version
drift and does not manufacture a Boolean. The corrected catalog and wrappers
were hot-deployed with backup `20260926-230715-017710-gradient-six-output`.
Batch F confirmed the corrected six-output shape, then stopped on a separate
opacity mutation discrepancy: setting opacity from 37 to 0 read back as 37.
This semantic failure remains preserved; batch G below isolated its side effect.
Batch G isolated its side effect: after the dedicated opacity setter received
zero, `GetGradientDataN` showed the stop's position changed from 0.25 to 0 while
opacity remained 37. Both opacity getters agreed. The local adapter forwards
the declared function and arguments correctly; a native binding mix-up is a
possible cause, not proven without its implementation. Do not repeatedly call
that setter while investigating. A separate aggregate-setter fixture was
used to test an alternative without invoking the broken dedicated setter.
That 79-job aggregate-setter fixture passed all native checks. The adapter now
bypasses `vs.SetGradientOpacity` on the measured build: it validates the gradient
and segment, reads both getters, preserves the other five fields, calls
`SetGradientDataN` once, then independently verifies identity, count and all
fields. Any post-write mismatch is a dispatched error with no retry or rollback.
Batch I passed all 41 original gradient-opacity jobs through this disclosed
replacement. Eighteen adversarial offline tests cover preflight and post-write
failures. Deployment backup is `20260926-232706-358696-gradient-opacity-repair`.

The text-leading repair and installed-callable discovery were hot-deployed
while idle with backup `20260926-221403-550-rootcause-leading`. That installed
`commands.py` SHA-256 is
`70550f67333ed77d2c8f977505e5fe23f5d6302c7a3f3bb1c9017fb7abf05498`;
`sdk_runtime.py` is
`63c7379fa839488a363f71e09cb181570c9ddfc61debc284e30d3c77760d81c4`.
After the user saved and closed Vectorworks, the subsequent opacity,
material-status and null-handle repairs were deployed with the scheduler
correction. Backup: `20260926-222648-151-fence-rootcause`. Installed runtime
SHA-256: `8e0a0e677cd53dccb97a809bc8cbe86a0765c17badbba546f108f9771897bb84`.
Installed native library SHA-256:
`0e3bcd3606176a83980cd195646115b2d5f8f34e489bdbd9fb410aba94b67758`.
The executable was restarted with the disposable test drawing. File hashes
confirm deployment, not native test success.

## Additional probes

`GetTextLength` returned UTF-8 byte counts for six observed text values,
including accented, East Asian, combining and supplementary characters. SDK
`UCChar` and native text insertion use UTF-16. A separate
[formatting-offset probe](TEXT_INDEXING_2027.json) confirmed UTF-16 indexing:
bolding positions 0 and 3 in `A😀B` affected only `A` and `B`, leaving both
surrogate positions unchanged. The adapter now corrects `GetTextLength` only
for the measured Windows build, a valid text object, and a native count equal
to the independently retrieved text's UTF-8 byte length. It returns the UTF-16
unit count with original-result disclosure. Already-correct values and unknown
builds are unchanged; inconsistent helper results cannot invent a length. This
repair passed all 49 native length-fixture jobs, all 22 exact formatting-offset
jobs, and the original seven-job Unicode-length reproduction in batch G.
Six responses disclosed length compatibility; direct results remain separately
counted. The subsequent strict-type/negative-length guard passed focused tests
and another 49-job native length fixture in batch I.
Partial text-style probes read both style references and effective font names
to distinguish a faulty getter from a setter that changes adjacent characters.

Worksheet probes compare literal values, formulas, displayed strings, numeric
and string predicates, header-cell/range validity, and border topology.
Same-range and encompassing-range legacy border clearing are observed before
explicit per-edge clearing and content-preservation checks. These probes
remain characterization; broad response-contract checks do not count as
semantic API passes.

The [worksheet predicate probe](WORKSHEET_LIMITS_2027.json) confirmed that the
database worksheet still had four rows and three columns. `IsValidWSCell` and
`IsValidWSRange` rejected columns 4 and 5, while `IsValidWSSubrowCell` accepted
an existing subrow at those columns. Its documentation concerns the displayed
subrow range, so the adapter preserves that result. The corrected database
fixture checks column bounds explicitly and subrow existence separately; all
54 jobs passed in G. Original mismatches remain in the evidence.

G's 42-job oriented-primitive family passed the documented projected
construction-box oracle. Its separate arc probe confirmed a real `SetArc`
no-op on this build: converted NURBS points and perimeter remained those of
the quarter-circle, while a directly constructed semicircle control had the
intended points and doubled perimeter. The native SDK helper was installed with
backup `20260926-233524-231` and verified in process 49096. It registers private scripting routines
`VWXBridgeRevision` (ABI 1) and `VWXBridgeSetArc`; the latter validates context,
argument tags, finite angles and arc type before one `GS_SetArcAnglesN` call.
The measured-build adapter bypasses the faulty Python setter and requires later
angle/identity readback. Native helper status only acknowledges the SDK call,
not geometry success. The scheduler is unchanged. Eighteen adapter tests and
thirteen native-helper/scheduler tests pass. The built library SHA-256 is
`4aef424ff329e45aac4fa8466dc9f5f1c4efe548617d49c07da57bf162469a47`.
The original 20-job arc suite passed in fresh batch J. A separate 40-job
characterization run now measures the intended semicircle: perimeter 10*pi and
converted NURBS start/mid/end points `(320,-250,0)`, `(310,-260,0)`,
`(320,-270,0)`. These agree with analytic predictions and the directly created
control within 1e-6. The unchanged quarter-arc control remains distinct.
The [twelve independent measurement checks](ARC_REPAIR_2027.json) preserve the
raw source hash. Characterization observations do not become semantic fixture
credit. `SetArc` receives compatibility credit; the faulty Python binding is
bypassed, not relabeled as fixed internally.

The earlier offline checkpoints passed 697 tests after arc integration and
781 tests in 81.353 seconds (`.audit/tests-full-20260927-a.log`). The subsequent
2026-09-27 suite passed **793 tests in 95.556 seconds**, including the compiled
native harnesses and no reported skips, recorded in
`.audit/full-offline-diagnostic-20260927-b.log`. The sandbox attempt's
temporary-directory ACL errors are retained; the complete rerun used normal
temporary-file access without weakening assertions. Independent SDK
adapter/index freshness, provenance hashes, test-matrix/coverage freshness and
static wrapper/tag consistency checks also passed. These checks made no host
calls. The later cleanup checks are recorded in
[publication validation](PUBLICATION_2027.md). The deployed runtime for J is
`379dc990fefbbe5ec644d425b9754344c969c88b4b46c6201ac68cf67e38c6e6`.

The first verified [maintenance cycle](MAINTENANCE_2027.md) used native library
SHA-256 `7655b6ce3dfc432865b7759c5bec1faea94b68947ff0c3cc58062d32ab28976b` and
backup `20260927-001256-744143-maintenance`; all eleven deployed hashes matched.
That controlled native maintenance cycle passed on 2026-09-27. The
[checked audit](MAINTENANCE_2027.json) records native save and quit success in
process 41536, independently confirmed process exit before deployment, then
native inventory of the sole expected saved drawing in process 50096 and lease
release. Its timestamps and eleven source-pinned deployment hashes are retained;
no independent desktop-focus measurement was recorded.

Earlier launch process 49672 produced no fresh bridge heartbeat; the user
reported a Vision startup warning. After the application closed, the installed vendor configuration and
binary references identified an absent legacy `CommonPath` compatibility entry.
A targeted UAC-approved restoration was followed by successful startup and
native inventory in process 41536, release of the old lease, and the user's
confirmation that no warning appeared. A later read-only window inventory
found no Vision dialog. See the [scoped startup finding](VISION_STARTUP_2027.md)
for original records and the separately copied files still under review.
The private maintenance routines do not change the 3,098-function SDK catalog,
and the successful maintenance cycle adds no SDK semantic coverage credit.
Original failures and J's successful measurements remain preserved.

Text-style size probes successfully calibrated distinct
styles and partial edits, but `UpdateStyledObjects` did not change the whole
style control after the resource size changed; propagation remains unresolved.

## Atomic diagnostic-file publication

The expanded native suite stopped between families when a readiness check read
malformed diagnostics. A separate read-only reproduction in
`.audit/native-alive-race-samples-20260927.json` found two empty `native.alive`
reads among 6,219 reads in approximately ten seconds. The old native producer
truncated the destination before writing it; readers could observe that empty
interval. This was a diagnostics-publication defect, not a semantic SDK result
or authorization to replay an earlier mutation.

`native/Source/Bridge/AtomicStatusFile.h` now writes the full replacement to a
temporary file, closes it, then calls `MoveFileExW` with
`MOVEFILE_REPLACE_EXISTING`. Both the heartbeat and scheduler JSON use this
helper. Failed writing, closing or replacement leaves the previous complete
destination in place; existing freshness checks still apply.

The [second checked maintenance cycle](MAINTENANCE_ENGLISH_ATOMIC_2027.json)
saved and quit process 50096, confirmed exit, deployed under backup
`20260927-002617-559895-maintenance`, and verified the sole expected drawing in
process 50236 before releasing the lease. All eleven installed files matched
the pinned plan. The new native library SHA-256 is
`71d91b0f1dc709d4c829f8205f5b6158b9c34d5dc9c4a5510330c2422c49b3a1`.
The same deployment installed English palette labels and help text, with VWR
SHA-256 `6e7ab97da0f0484bc7bef869c513a98f9df064d2d3c0590d43e04d5207957601`.
The earlier maintenance audit and all original SDK failures remain unchanged.

The deployed read-only sample in
`.audit/native-alive-atomic-samples-20260927.json` checked these native hashes
and process identity before and after its ten-second observation. It found zero
malformed values in 6,177 reads, but one `PermissionError`; its recorded
`sample_passed` is therefore **false**. Atomic replacement prevents the observed
empty-file exposure but does not establish that every concurrent Windows read
succeeds. This sample made no native calls, awarded no semantic coverage, and
did not independently measure desktop focus.

The shared Python `mcp-server/diagnostic_io.py` reader now retries only
`PermissionError`, with four attempts and at most 30 milliseconds of delay.
Malformed contents, stale data and failed schema checks remain errors. The
helper is used for native diagnostic snapshots, never lease records, jobs,
native results or mutation retries. New stdio consumers load this reader
without another native deployment.

The independent actual-helper sample
`.audit/diagnostic-reader-retry-samples-20260927-a.json` (SHA-256
`edadfc64012fb450552bdf4a7033dc012db5edd42b7767487c35569b3d9f86c4`)
then passed: 6,508 valid complete reads of each diagnostic in ten seconds,
13,016 total, with three underlying heartbeat `PermissionError` exceptions
recovered and zero terminal access errors or malformed values. Each file
changed ten times. Process 50236 and all eleven deployed hashes matched before
and after; the reader and validator source hashes were unchanged. This proves
bounded observed recovery, not every possible interleaving. The two files remain
independent snapshots, and the earlier failed raw sample remains preserved.

## Historical scheduler interruption

During the text-style probe, three setup jobs completed. The next document
guard was never claimed. The scheduler had 3,825 background posts and 3,824
observed runner completions, with a fresh heartbeat and an empty job queue
after the client's unclaimed timeout. No mutation was automatically replayed.

That native scheduler restored shortcut modifiers on the next timer tick,
which does not prove queued key messages have been consumed. The correction
keeps the modifiers until a same-thread queue fence has been processed and
pending targeted key messages are cleared. Completion and entry stamps are
sampled immediately before posting, and nested timer execution is guarded.
An unproven timeout still holds the trigger; the bridge never fabricates a
completion or replays a potentially executed mutation. This correction has
been built and deployed. A live rerun completed 30 background invocations and
then lost another trigger; the fence change alone did **not** resolve the
delivery problem. Its final request was never claimed and received no native
pass or semantic failure credit. Scheduler telemetry identifies this build as
`targeted-accelerator-fence-ack-v2`. A direct, validated menu-command trigger
replaced shortcut delivery in the next deployed build. It discovered the exact
enabled Python menu command, rejects ambiguous command IDs and menu metadata,
and posts `WM_COMMAND` asynchronously on the Vectorworks UI thread. No keyboard
state or key messages are used. Completion and no-replay guards remain.

The user saved and closed Vectorworks again for this deployment. Backup:
`20260926-223849-898-direct-menu`; native library SHA-256:
`8272a73753c5544e53233dd5bb29bf88fb2e5e4c5b903fef2213a88f8145c432`.
Scheduler identity is `posted-menu-command-ack-v3`. Nine native scheduler tests,
including compiled independent menu-tree policies, passed at that checkpoint.
Its first read-only delivery request stopped before native execution:
the scheduler reported `frame_menu_unavailable`, with zero posted commands and
zero runner completions. The client atomically discarded its still-unclaimed
request and reported `VW_JOB_UNCLAIMED`; the drawing was not changed by this
check. This does not prove a dialog was open or that the Python menu is missing.
It establishes that this scheduler could not obtain its expected Win32 menu
handle. Sustained delivery has therefore not passed on V3.

The delivery checker independently requires eleven matching source/deployment
hashes, exact native host identity on every response, matching background-post
and completion deltas, and an idle final queue. The first attempted plan made
no MCP request because three otherwise identical deployed text files used CRLF
instead of the source files' LF. Their byte-for-byte line content was checked,
backed up in `20260926-224528-036963-physical-lf`, and normalized while idle. The
subsequent request above passed those deployment checks. Both outcomes are
preserved in [BACKGROUND_DELIVERY_2027.json](BACKGROUND_DELIVERY_2027.json).

The all-API availability checker, `tools/check_sdk_host_presence.py`, inspects
all 3,098 names without calling the inspected functions. Its output separates
callable, missing/noncallable and failed inspections. Presence is not semantic
coverage or permission to call an API in an unsupported execution context.

## Installed SDK menu broker and verified delivery

The replacement source is `sdk-named-menu-broker-ack-v4`. It obtains the frame
from `GS_GetMainHWND` during palette initialization. The timer posts a private
event to a message-only window on that same UI thread. The event rechecks
ownership, modal/interactive state, the queue and runner stamps before invoking
`gSDK->DoMenuName("VWX Bridge Start", 0)`. SDK 3200's
`APIBase.Legacy.Defs.h` documents the frame accessor and recursive named-menu
invocation; the [public menu-selector reference](https://github.com/Vectorworks/developer-scripting/blob/main/Function%20Reference/Functions/DoMenuTextByName.md)
also identifies script plug-ins by filename. The installed command is
`VWX Bridge Start.vsm`.

This removes the Win32-menu-handle dependency and uses no keyboard messages,
global input, focus changes or direct Python-engine calls. The SDK menu call
is synchronous inside the private event. Nested timers cannot acknowledge or
dispatch while it runs. Its return code is diagnostic; only a later observed
outer-runner completion acknowledges the request. Duplicate/stale event tokens
cannot invoke a second job, and rejected or uncertain invocations are not
automatically replayed. A reviewed close/reopen correction invalidates a token
only after confirmed broker-window destruction, preserving the serial number,
active-call guard and outstanding completion fence.

At the earlier V4 deployment checkpoint, the SDK 3200 Release build succeeded.
That native library SHA-256 was:
`0c1e0493223ddf8f4ebc5ce24422b49f16d197dc3279bc40fbfe733190fac165`.
That checkpoint's offline suite passed 616 tests; the final lifecycle correction also
passed all ten scheduler tests, including nine compiled policy assertion groups.
The strict V4 delivery checker passed 27 tests. These are source/build checks,
not proof of native execution. After the user saved and fully closed Vectorworks,
V4 was installed with verified hashes and backup
`20260926-225522-875-sdk-menu-broker-v4`. Vectorworks was restarted with the
disposable test drawing. The subsequent strict delivery run passed 100 typed
background reads with exactly 100 posts, invocations, returns and completions;
foreground posts, failures, timeouts and broker rejections remained zero.
All eleven deployed file hashes matched before and after that run, and its
final queue was idle. Following batch E and the read-only gradient probe,
telemetry showed 529 completed background invocations with the same zero-error
counts. This verifies those runs, without claiming universal native semantics.
The separate presence scan found 3,081 callable names, 17 absent/noncallable
names and zero inspection errors across the 3,098-name catalog.
