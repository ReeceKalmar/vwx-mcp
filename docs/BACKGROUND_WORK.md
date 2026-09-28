# Working while Vectorworks is in the background

Typed MCP design work uses the Vectorworks API without mouse control,
screenshots or taking application focus. Keep the intended drawing open,
Vectorworks **unminimized**, and the **VWX Bridge** palette open and unpaused.
Other applications may cover it. This runs inside the desktop application;
a headless Vectorworks service is not implemented.

Use the [design workflow](DESIGN_WORKFLOW.md) to distinguish an environmental
pause, a rejected input and an operation needing reconciliation. A routine
pre-publication pause can leave independent design preparation moving; an
outstanding request or existing incident hold must still be resolved before
new native work. This guidance does not add automatic window restoration or
queue recovery.

The installed English palette offers **Pause**, **Resume**, **Queued commands**
and **Last activity**. Add **Show VWX Bridge Palette** from **Extras** to the
workspace if necessary. The separate Python menu command must retain the exact
name **VWX Bridge Start**. V4 invokes that name through the SDK and does not
require a workspace keyboard shortcut.

## Background policy

Keep `VWX_BACKGROUND_MODE=1` and `VWX_CACHE_TTL=0` for live verification. Prefer
handwritten workflow tools, `sdk_Name`, `sdk_call`, or supported `sdk_sequence`
plans. Discover each exact SDK contract with `sdk_list`. Explicit-path saves
are available through typed save tools when saving is part of the task.

[background_policy.py](../mcp-server/background_policy.py) preflights every
batch/sequence member before publication. Raw scripts, arbitrary menu commands,
interactive tracking, known dialogs/file pickers and listed import/export
workflows return `VWX_BACKGROUND_INTERACTION_REQUIRED` with `dispatched=false`.
`options.force` cannot bypass this. `switch_document` is also blocked because
its fallback can restore a window or change focus. Read-only document discovery
does not reserve the document or provide an isolated session.

`DTM6_GetDTMObject` is allowed only with the exact SDK argument
`bPickUpModel=false`; true, omitted, non-Boolean or deferred-reference values
are rejected before publication. This applies to `sdk_call`, its generated
`sdk_DTM6_GetDTMObject` tool, and every nested sequence/batch member. A later
picker request blocks the entire batch, including preceding mutations. Prefer
`site_model_on_layer`, which discovers one layer-local Site Model and rejects
ambiguity without invoking the picker, or a previously verified Site Model UUID.

`list_documents` requires the private native inventory helper (ABI 1) and reads
the SDK open-file list, including exact full paths, file references and the
active flag. Its English `open_documents` rows and legacy `dokumente` aliases
describe the same validated snapshot. Legacy `datei` retains the entire basename,
including hyphens and Unicode; window titles, watermarks and window handles are
not used. Unsaved documents can have an empty path and are explicitly marked
`in_memory_only`. Missing helpers, malformed rows or ambiguous native identity
return an error, with no window-title fallback. A file reference is local to the
current open-file session, not a persistent document UUID.

The separate [guarded document transition](MAINTENANCE_2027.md#guarded-document-transitions)
uses the maintenance lease and private native document helper. It saves the source,
opens or switches to an exact existing saved target after Python returns, and
requires a later independent confirmation. It leaves original files open and
does not isolate agents or create a new drawing. The legacy `switch_document`
tool remains blocked.

Only explicitly attended work should restart the server with
`VWX_BACKGROUND_MODE=0`; SDK type/context guards still apply. Do not bypass the
user's background preference through direct queue files or controlled-script
harnesses. The policy is an interaction filter, not a security sandbox: native
or third-party failures can still open dialogs. Leave application errors,
developer approval and security prompts for the user.

## Scheduling and document ownership

The current scheduler is `sdk-named-menu-broker-ack-v4`. A private same-thread
broker invokes `gSDK->DoMenuName("VWX Bridge Start", 0)`; the host supplies the
Python menu context. Native timers, notifications and web callbacks never run
Python. A minimized/disabled frame, modal state or active move/menu loop can
hold dispatch. The bridge does not restore windows or manufacture user input.

Each invocation executes at most one job. At most one trigger awaits completion.
`pump.stamp` marks entry; only the outer invocation writes
`pump.complete.stamp` after resetting reentry. Completion is observed after the
synchronous menu call returns. A two-second diagnostic timeout keeps waiting,
never reposting uncertain work. No stamp or lease may be forged to clear a hold.

Completion is not semantic success or proof of deferred object regeneration.
Create/reset objects and inspect regeneration-dependent geometry in separate
requests. A `vwx_batch` or `sdk_sequence` is still one job with no internal
regeneration boundary or rollback.

All clients share one process and its active drawing. A document guard and the
following mutation are separate requests. Coordinate ownership and serialize
native work on different drawings; agents can prepare plans and offline tests
in parallel. During a regression run, keep the disposable drawing active and
avoid concurrent edits to its state. See [TESTING_2027.md](TESTING_2027.md).

## Verify without desktop control

Use `tools/check_sdk_background_delivery.py` for bounded read-only typed checks,
hash verification and telemetry capture. Its [test instructions](TESTING_2027.md#check-background-request-delivery)
require a fresh output directory. It stops on the first failure and never
retries a request or grants native semantic coverage.

1. Require fresh `native.alive` and `native.scheduler.json`, V4 identity, the
   expected SDK frame/process, timer active, palette unpaused and a valid broker.
2. While another app is naturally foreground, record counters and send an
   uncached typed read such as `sdk_GetVersionEx(arguments={})`. Do not change
   focus merely to manufacture a background test.
3. Require the actual successful response with matching function and host
   identity. Wait briefly for outer completion and require equal post,
   invocation, return and completion deltas, no foreground posts or trigger
   errors, and a final empty queue with no pending trigger/broker invocation.
4. Record source/deployment hashes and telemetry with the result. This verifies
   those requests, not all APIs. Geometry verification also requires independent
   later readbacks and, where relevant, an explicit disposable-file save.

Use the configured `VWX_PLUGIN_DIR` for file diagnostics. Publication is atomic,
but a concurrent Windows read can briefly fail. The shared diagnostic reader
retries `PermissionError` four times with at most 30 ms delay. Parsing,
freshness, identity and schema still fail closed; diagnostic reads do not retry
or replay jobs. The two status files are not an atomic pair.

The delivery readiness check also compares scheduler runner/completion values
to the actual stamp-file timestamps in Windows FILETIME units. Fresh idle
telemetry can precede acknowledgment of a newly completed job; that mismatch
returns `SETTLING` until the timer reports the real stamps. Fresh active work
also settles. Any unexplained queue entry (including working/temp files or
directories) or outstanding publication record blocks an otherwise idle host.
Readiness checks preserve these records and never clear or replay them.

| Field/state | Interpretation |
|---|---|
| `posts`, `background_posts`, `foreground_posts` | Successful private event posts, not API results |
| `menu_invocations`, `menu_returns` | SDK menu calls attempted/returned; return code is only diagnostic |
| `runner_completions_observed` | Changed outer completion stamps while a trigger was outstanding |
| `pending`, `pending_age_ms`, `acknowledgment_timeouts` | An outstanding completion fence and delayed observations; no replay |
| `broker_window_available`, `broker_message_pending`, `menu_invocation_active` | Broker lifecycle and queued/active invocation state |
| `trigger_failures`, `broker_rejections`, `last_win32_error` | Delivery/ownership failures, distinct from native API errors |
| `frame_source`, `frame_available`, `frame_has_win32_menu` | Frame comes from `GS_GetMainHWND`; a Win32 menu is not required |
| `last_trigger_state` | Last attempt's label, not a fresh window-state observation |
| `target_minimized`, `target_disabled`, `modal_dialog_open`, `ui_thread_interactive_loop` | Possible reasons the last attempt held dispatch |
| `keyboard_state_modified=false`, `global_input=false`, `focus_changed_by_bridge=false` | Implementation policy, not an independent OS focus measurement |

A fresh timestamp does not refresh an old `modal_dialog_open` label. It can
remain after a dialog closes or the queue becomes idle. Check current heartbeat,
pending/queue state and an authorized typed response; do not manipulate windows
based on the label alone. Idle readiness proves neither document ownership nor
that every modal workflow is safe.

On `VW_JOB_UNCLAIMED`, the server proved it removed the pending request before
dispatch. On a claimed timeout or unknown outcome, retain the journal and
inspect the document and later result before taking new action. A missing result
file may already have been consumed by the server. Never auto-dismiss a dialog,
force-kill Vectorworks or replay a possibly completed mutation.

## Deployment and recorded evidence

Native deployment requires Vectorworks closed. Use [BUILD_SETUP.md](BUILD_SETUP.md)
or the [guarded maintenance controller](MAINTENANCE_2027.md); never overwrite a
loaded binary. Preserve an active user session until the restart is authorized.

The [V4 delivery record](BACKGROUND_DELIVERY_2027.json) passed 100 background
reads on its recorded build; earlier failed V3 and shortcut runs remain historical.
The [second maintenance audit](MAINTENANCE_ENGLISH_ATOMIC_2027.json) identifies
the later English palette/atomic-publisher deployment. The
[diagnostic investigation](NATIVE_REPAIRS_2027.md#atomic-diagnostic-file-publication)
retains the original empty-read race, the initial atomic-only read error, and
13,016 valid complete reads with three recovered access errors after the bounded
reader repair. None of these is a universal interleaving guarantee or SDK
semantic coverage. The earlier [save observation](BACKGROUND_SAVE_2027.json)
and [Boolean workflow](BOOLEAN_WORKFLOW_2027.json) retain their own hashes and
focus/readiness limitations; do not transfer those claims to a new build.
