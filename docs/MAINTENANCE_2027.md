# Controlled maintenance restarts

`tools/restart_vectorworks.py` handles saving, normal shutdown, deployment and
reopening the expected drawing through the typed `bridge_maintenance` MCP tool.
It sends no mouse, keyboard or focus events. This is maintenance of one shared
Vectorworks process, not independent document sessions for multiple agents.

The implementation builds against SDK 3200 and has offline tests for document
guards, native callbacks, lease races and controller failures. The clean
publication suite ran **821 tests** successfully, with one Windows symlink test
skipped; see [publication validation](PUBLICATION_2027.md). SDK adapter/index
freshness, generated reports and static consistency checks also passed.

The first controlled native save/quit/deploy/reopen cycle **passed** on 2026-09-27.
The [checked audit](MAINTENANCE_2027.json) records native save and quit success
in process 41536, separately confirmed process exit, deployment under backup
`20260927-001256-744143-maintenance`, and native inventory of the sole expected
saved drawing in process 50096 before lease release. All eleven deployed hashes
matched the pinned plan. The native library SHA-256 is
`7655b6ce3dfc432865b7759c5bec1faea94b68947ff0c3cc58062d32ab28976b`.
The cycle took 46.675 seconds; no independent desktop-focus measurement was
recorded. This verifies that controlled cycle, not every future restart.

A second [checked maintenance cycle](MAINTENANCE_ENGLISH_ATOMIC_2027.json)
passed from process 50096 to 50236 in 50.642 seconds. Native save and quit each
returned success; the original process exited before deployment under backup
`20260927-002617-559895-maintenance`. The restarted process reported the sole
expected saved drawing, all eleven installed hashes matched the plan, and the
lease was released. This installed the English palette and atomic heartbeat/status
publisher. The recorded native SHA-256 values for that second cycle are:

- `VwxBridge.vlb`: `71d91b0f1dc709d4c829f8205f5b6158b9c34d5dc9c4a5510330c2422c49b3a1`
- `VwxBridge.vwr`: `6e7ab97da0f0484bc7bef869c513a98f9df064d2d3c0590d43e04d5207957601`

The later [document-transition audit](DOCUMENT_TRANSITION_2027.json) pins the
replacement native artifacts and all eleven files deployed for its tests. Keep
each cycle's hashes with its original evidence; later Python hot deployments
do not change the earlier measured manifest.

Both cycle audits are preserved separately. Neither independently measured
desktop focus or adds SDK semantic coverage. The post-deployment heartbeat
sample found no malformed values but one transient `PermissionError`; bounded
Python-reader handling subsequently passed a separate sample with 13,016 valid
reads and three recovered access errors. The earlier failed sample remains
preserved. See
[the diagnostic-file investigation](NATIVE_REPAIRS_2027.md#atomic-diagnostic-file-publication).

The earlier launch of process 49672 produced no fresh bridge heartbeat and a
user-reported Vision warning. A targeted vendor-configured
[Vision compatibility registration repair](VISION_STARTUP_2027.md) was followed
by successful startup in process 41536 and the user's confirmation that no
warning appeared. Those earlier records and the original bootstrap save-prompt
observation remain preserved. The original arc-helper build did not include
this extension; successful arc J tests remain evidence for their recorded
build. See [the native investigation record](NATIVE_REPAIRS_2027.md).

## Invocation

Use the repository's Python environment with FastMCP installed. Supply the
one exact saved ordinary `.vwx` drawing, the default installed plug-in directory,
and a fresh audit directory. Without `--execute`, this writes a plan only:

```powershell
python tools/restart_vectorworks.py `
  --document 'C:\path\drawing.vwx' `
  --plugin-dir "$env:APPDATA\Nemetschek\Vectorworks\2027\Plug-ins\VWX-MCP" `
  --output-dir '.audit\maintenance-new-run' `
  --execute
```

Build and test the release before invoking maintenance. The controller records
the eleven source/build hashes before saving. A source change during the run
stops deployment. Reusing a run directory is refused; interrupted runs are not
automatically resumed.

## Protection and failure behavior

1. Acquire a persistent maintenance lease only with fresh idle bridge state,
   no queued or unfinished work, and no unresolved publication records. A
   cross-process publication lock serializes acquisition with job submission.
2. Enumerate documents through the public native SDK. Require exactly one
   active, previously saved ordinary `.vwx` file with the exact expected path.
   Project-sharing working files, extra drawings and unsaved drawings stop it.
3. Bind a Windows process handle to the measured process and verify its
   executable. Save the existing document and require explicit native success.
4. Recheck the drawing and write a durable, single-use quit intent. The native
   quit helper saves and rechecks once more within that same callback, then requests
   `CloseAllFilesAndQuitVectorworks(true, false)`, preserving save prompts if
   changes happen after the save. Never use the discard form of that SDK call.
5. Wait for actual exit of the original process and its Vectorworks children.
   An accepted quit response is insufficient. No force-kill fallback exists.
6. Back up the old IPC queue and installed files, deploy and check all hashes.
   Launch once, wait for a fresh heartbeat, verify the new process and drawing
   through MCP, recheck hashes, then release the lease.

Startup warnings, plug-in approval, a closed palette, or a blocked main thread
can still require the user. The tool reports a stopped phase and retains its
lease; it does not dismiss dialogs, discard documents, replay jobs or claim a
restart passed from process existence alone. A failure after saving or quitting
may have taken effect even when no response arrived.

The first bootstrap observed the exact test drawing's save prompt despite a
successful `SaveActiveDocument` result and no later host jobs. Its cause is not
yet established. The added save within the quit callback still preserves normal
prompts; it is not proof of a completely unattended restart.

The lease coordinates updated MCP servers. It is not a security boundary against
older clients that ignore it, arbitrary scripts or a human editing/switching
documents. Restart existing server clients after upgrading. The native helper
rechecks the document immediately before each save/quit, and normal shutdown
still preserves prompts for subsequent unsaved edits.

## Recovery

Keep the stopped run's `journal.jsonl`, `result.json`, and local
`lease-token.json`. Inspect the actual process, drawing, installed hashes and
queue before deciding the next step. The token is a local recovery credential;
do not publish it in reports. The typed `bridge_maintenance` tool has
`lease_status` and explicit `release` actions. Release requires the original
token; there is no timed expiry or automatic takeover. Releasing a lease does
not establish that the previous save or quit failed, and does not authorize
replaying an uncertain mutation.

Native save and quit intents and confirmed-save receipts live alongside the
lease outside `ipc`, so deployment cannot erase the no-replay evidence when
it archives the old queue. A consumed operation requires inspection, never an
automatic second attempt with the same token.

The private `VWXMaint*` routines have a separate ABI from `VWXBridgeSetArc`.
Neither group adds functions to the official 3,098-entry SDK API catalog or
receives SDK semantic coverage merely by passing maintenance tests.

## Guarded document transitions

`bridge_maintenance` also supports `transition`, `transition_status` and
`transition_confirm` with the separate private `VWXDoc*` ABI 1. This workflow
requires an existing saved ordinary `.vwx` target. It does not create a new
drawing, close drawings, discard changes or provide parallel document sessions.
The old `switch_document` window-message route remains blocked in background mode.
The public Python command rejects a new target when 256 documents are already
open, before native staging; switching to a target already in that inventory is
still allowed. It also checks the UTF-8 size of dispatch evidence and the largest
possible confirmation against the 262,144-byte read limit before staging. These
checks prevent a successful native change from exceeding its verification limits.

The [2026-09-27 native audit](DOCUMENT_TRANSITION_2027.json) confirmed two opens
of existing disposable files and one switch back to an already-open disposable
file, following a verified 51.415-second controlled restart. A later atomic
`commands.py` guard deployment retained the same native binaries; a fourth
confirmed transition returned the original project to active status. Each case
used a separate confirmation job before lease release and preserved every
original document. Its first source and final target were the existing project;
the intermediate drawings were disposable. The audit keeps each case bound to
its actual deployment manifest. The original offline checkpoint ran 918 tests
in 111.037 seconds; the final guard checkpoint ran 924 in 105.137 seconds.
Both passed with one skip.

Across the four successful transitions, 205 foreground samples never observed
the Vectorworks main process. Two foreground windows appeared in the first run;
each later run sampled one. These bounded observations do not prove continuous
unchanged focus or startup behavior. The earlier attempt remains a recorded
prepublication refusal: the preceding status response arrived before its outer
menu acknowledgment. After proving no transition was published, the owner
released that lease and used a fresh run that waited for idle after status.

1. Acquire the normal maintenance lease and read `status`. Require the original
   process, the exact active source path and `document_transition_revision=1`.
   Preserve a disk checkpoint before saving; it does not include unsaved edits.
2. With a fresh idle scheduler, call `transition` using that token,
   `expected_path` and `target_path`. Before queue publication, the server writes
   a durable transition intent. The Python command validates the inventory and
   consumes a separate dispatch intent before calling the native staging helper.
3. The staging response reports `phase=staged`, `completed=false`. The C++ broker
   rechecks every open-file identity after the Python menu returns and its outer
   completion stamp changes. It saves the exact source, rechecks the inventory,
   then switches to an already-open exact target or opens its existing path once.
   It keeps every original document open. No mouse, keyboard, focus, restore or
   close call is involved. SDK/native plug-ins can still display their own errors.
4. Wait for fresh idle telemetry, then use separate `transition_status` and
   `transition_confirm` jobs. Confirmation requires the same request/process,
   native save and transition success, the target active, and every original
   path/file reference preserved in an independently read SDK inventory.
5. Release only after confirmation and another fresh idle check. The server
   validates the intent, consumed dispatch record and confirmation before release.

Large files can keep the UI thread busy during the deferred C++ save/open,
delaying the heartbeat. After a known staged transition, stale telemetry alone
does not establish a crash. Poll only the original process's liveness and local
readiness files within a finite configured wait budget; wait for fresh idle
before publishing another native job. Process exit or budget exhaustion leaves
the lease and records intact for inspection. Do not replay the transition or
clear a completion fence to continue.

The local records are `bridge.maintenance.<request-id>.transition.intent.json`,
`.dispatch.json` and `.confirmed.json`, outside `ipc`. The request ID is the
lease token's SHA-256; keep the original token private. A missing response,
false result, exception, unexpected document change or malformed record keeps
the lease. Never reissue the transition, erase its records or interpret a staged
response as permission to design. Read-only confirmation may be repeated; the
save/open/switch attempt cannot. Cross-process publication serialization protects
updated clients, not a person editing documents or an older server ignoring leases.

Because originals remain open, a successful transition can leave several saved
drawings open. The existing restart controller still requires **one** exact saved
drawing. It will refuse that multi-document state; no automatic close workaround
is implied. New-document creation and unexpected-crash recovery remain separate
workflows. Offline/compiled tests and an SDK build do not establish live transition
or application-focus behavior on their own. The linked native audit establishes
only its recorded existing-file cases and bounded focus observations.
