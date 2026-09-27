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
publisher. Current native SHA-256 values are:

- `VwxBridge.vlb`: `71d91b0f1dc709d4c829f8205f5b6158b9c34d5dc9c4a5510330c2422c49b3a1`
- `VwxBridge.vwr`: `6e7ab97da0f0484bc7bef869c513a98f9df064d2d3c0590d43e04d5207957601`

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
