# Vectorworks 2027 bridge architecture

The supported host is Vectorworks 2027 on Windows. MCP clients use stdio or
optional HTTP; the server communicates with Vectorworks through local files.
Both reads and writes follow the same menu-command execution boundary.

```text
MCP client -> vwx_mcp_server.py -> recursive background-policy preflight
  -> maintenance/publication gate -> ipc/jobs/<timestamp>-<cid>.json
  -> native palette timer posts one private UI-thread broker event
  -> broker calls gSDK->DoMenuName("VWX Bridge Start", 0)
  -> Python menu launcher -> vwx_pump.pump_all() -> one command
  -> handwritten workflow / SDK runtime -> vs.*
  -> ipc/results/<cid>.json -> MCP client
  -> outer menu returns; completion fence permits the next job
```

## Components

| Directory/component | Responsibility |
|---|---|
| [mcp-server](../mcp-server/AGENTS.md) | FastMCP tools, input/background preflight, file transport, cooperative maintenance lease and diagnostics |
| [native](../native/AGENTS.md) | SDK menu broker, completion fence, English palette, atomic native diagnostics, private arc/maintenance callbacks |
| [vwx-plugin](../vwx-plugin/AGENTS.md) | Menu launcher, one-job pump, handwritten commands, generated bindings and strict SDK runtime |
| [tools](../tools/AGENTS.md) | SDK generation, static reports, fixture plans, typed runners, evidence importer and restart controller |
| [tests](../tests/AGENTS.md) | Offline adapters/models, adversarial oracles, native C++ harnesses and lifecycle regressions |

Native `.vlb`/`.vwr` files install in the 2027 user Plug-ins folder; Python bridge
files install in its `VWX-MCP` subfolder. See [BUILD_SETUP.md](BUILD_SETUP.md).
There is no active watchdog, notification-context Python executor or TCP bridge.

## Lifecycle and invariants

1. `cmd` validates the complete background request before opening a connection.
   An interactive member rejects the entire batch/sequence before any mutation.
2. The cross-process publication gate checks the maintenance lease and durably
   records ordinary publication ownership before atomic job publication. While
   a lease is held, only its owner's top-level typed maintenance command can
   publish native work. Nested maintenance is rejected even without a lease.
3. The palette obtains the frame with `GS_GetMainHWND`, creates a message-only
   broker on that UI thread, and posts one-use private events. Its handler
   rechecks thread/frame/queue/stamps before calling the fixed SDK menu selector.
   No Win32 menu handle, global input, focus change or Python-engine callback is
   required. Native timer/web/notification callbacks never execute Python.
4. The menu launcher checks host year and installation identity. The pump refuses
   reentry, claims a job as `.working`, and consumes the claim before native
   dispatch. It logs the command start, writes an atomic result, and returns
   after at most one job. A new queued job cannot extend that invocation.
5. Only the outer pump invocation writes its completion stamp in `finally`.
   The native broker stays active until the synchronous SDK menu call returns;
   nested timers cannot acknowledge it early. A changed completion stamp then
   releases the outstanding trigger. The SDK return code alone never does.

The entry stamp is not a completion acknowledgment. A two-second acknowledgment
timeout records a diagnostic and keeps the trigger held; it never reposts
unknown work. Broker destruction invalidates a canceled token without erasing
the completion fence or resetting token identity. Creation/reset and dependent
inspection belong in separate requests; a batch/sequence remains one job with
no rollback or regeneration break.

## File protocol

Paths are relative to the installed `VWX-MCP` folder. Correlation IDs are exactly
twelve lowercase hexadecimal characters; validation precedes result-path access.

| Path | Writer | Purpose |
|---|---|---|
| `ipc/jobs/*.json` | Server | Atomically published pending commands |
| `ipc/jobs/*.json.working` | Pump | Transient claim consumed before dispatch |
| `ipc/results/<cid>.json` | Pump | Atomic result, consumed by server |
| `ipc/pump.stamp` | Pump | Entry stamp |
| `ipc/pump.complete.stamp` | Outer pump | Completion JSON (`schema_version`, `completed_ns`); native watches file modification time |
| `ipc/native.alive` | Palette | Epoch and pause flag |
| `ipc/native.scheduler.json` | Palette | Broker, post/return/completion, queue, hold and failure telemetry |
| `ipc/readonly.json` | Server | Compatibility metadata; never authorizes notification execution |
| `bridge.publish.lock` | Cooperating servers | Shared OS advisory publication/acquisition gate |
| `bridge.maintenance.json` | Maintenance owner | Persistent hashed-token lease, outside IPC deployment archival |
| `bridge.publications/<cid>.json` | Server | Durable ordinary-job publication/uncertainty marker |
| `bridge.log` | Native bridge/pump | Scheduling and command-start/result diagnostics |

The native producer closes complete temporary diagnostic files before atomic
replacement. Python readers retry only transient `PermissionError` with four
attempts and at most 30 ms delay; malformed, stale or invalid snapshots still
fail validation. This read retry never applies to jobs, results or leases, and
the two diagnostic files are independent snapshots.

## Failure handling

The server defaults to a 900-second MCP timeout and an 880-second transport
wait. `VW_JOB_UNCLAIMED` with `dispatched=false` means an atomic removal proved
the queued request was never claimed. A claimed timeout, lost heartbeat or
host exit is uncertain. Preserve its publication marker and journal; inspect
the document and a later `vwx("poll", {"cid": ...})` result before deciding on
new work. Absence of a result file is not proof of failure: the server may have
already consumed it. Python exception handling cannot catch native crashes.

`marionette_recalc` has an attended-only historical early acknowledgment because
its execution can destroy the Python context; that acknowledgment is not
completion. Background policy blocks the workflow.

All clients share the active document. Job serialization does not make a guard
and its following mutation atomic or provide per-agent document isolation.
Maintenance additionally binds the original OS process, validates the sole
saved drawing, confirms actual process exit before deployment, then verifies
the new process/drawing and all installed hashes before releasing its lease.
It is cooperative coordination, not protection from old clients or human edits.

For operational requirements and telemetry interpretation see
[BACKGROUND_WORK.md](BACKGROUND_WORK.md); for maintenance recovery see
[MAINTENANCE_2027.md](MAINTENANCE_2027.md). Actual verified delivery, native
semantics and offline correctness remain separate in [TESTING_2027.md](TESTING_2027.md)
and [the evidence reports](TOOL_COVERAGE.md).
