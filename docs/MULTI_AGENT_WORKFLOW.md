# Multiple agents on one landscape project

Agents can plan, analyze sources, prepare geometry and review results in parallel.
Native Vectorworks work is serialized under a persistent **project ownership
lease**. Every owner operation checks the saved drawing inside the same menu
job as the operation. A second agent cannot publish native work until the owner
finishes and releases the lease.

This supports agents sharing one project, not simultaneous editing sessions or
per-agent Vectorworks documents. The application still has one active drawing
and one main thread. Human edits and clients running older bridge code are not
isolated by this cooperative protocol. Update all clients and the host files.

## Setup

Use [installation instructions](BUILD_SETUP.md) on the one Vectorworks host.
Every participating MCP server must resolve the **same** `VWX_PLUGIN_DIR`.
Use the `landscape` toolset and leave `VWX_BACKGROUND_MODE=1` and
`VWX_CACHE_TTL=0`. Keep the host unminimized and its palette open/unpaused.

Maintain a short project handoff containing the exact drawing path, current
owner, scope, object UUIDs, completed and unattempted operations, outstanding
correlation IDs, verification results and saved checkpoint. This supplements
the enforced lease; a note by itself is not a lock.

## Acquire, work, verify, hand off

Generate a fresh 64-character lowercase hexadecimal token locally (for example,
`python -c "import secrets; print(secrets.token_hex(32))"`). Keep it in the
owner's private recovery journal. Never commit it or include it in shared logs.
The bridge persists only its hash; queued jobs carry a nonsecret lease identity.

The following examples are MCP tool arguments. Replace the path, owner and
`<private-token>` with actual values; these strings are not executable defaults.

```text
project_session(action="status")
project_session(action="acquire", token="<private-token>",
                expected_path="C:\\Projects\\Garden\\Garden.vwx",
                owner="site-model-agent")
project_execute(token="<private-token>", command="get_document_info", params={})
project_execute(token="<private-token>", command="get_document_units", params={})
```

Acquisition requires a saved file and fresh idle scheduler with no queued,
unfinished or uncertain publications. Acquisition reserves the bridge; it does
not itself claim the active drawing was inspected. The first and every later
`project_execute` verify the bound host process and actual saved drawing path
before dispatching the requested command.

Use `project_execute` for **all native reads and writes while the lease is
active**, including handwritten commands, `sdk_call`, `sdk_sequence` and
`_batch`. Direct native tools from any client are rejected during ownership.
Supply the underlying command name, not the MCP `vwx` wrapper name.

```text
project_execute(token="<private-token>", command="landscape_duplicate_template",
                params={"source_id":"<template-uuid>",
                        "target_layer":"Hardscape", "dx":20, "dy":0})
# Later request, after creation/reset returns:
project_execute(token="<private-token>", command="landscape_object_info",
                params={"object_id":"<returned-object-uuid>"})
```

Check the actual geometry, native type, path, elevations and fields needed by
the task. A separate request creates the required event-loop boundary, but is
not proof that regeneration completed. A batch/sequence is still one job.

Save through the exact discovered SDK contract; Save As and document switching
are excluded from owned workflows:

```text
sdk_list(name="SaveActiveDocument")
project_execute(token="<private-token>", command="sdk_call",
                params={"name":"SaveActiveDocument",
                        "arguments":{"filePath":"C:\\Projects\\Garden\\Garden.vwx"}})
project_session(action="release", token="<private-token>")
```

Verify the native save result and saved file before handing off. Release requires
fresh idle state and completion acknowledgment; a result arriving before the
outer menu returns may mean release must wait. Poll status/readiness, not the
mutation. The next agent acquires with its own token and rereads relevant
objects, because its preparation may predate intervening edits.

## Failure and recovery

| Condition | Required response |
|---|---|
| Another owner holds the project | Continue offline planning/review; coordinate a handoff. Do not steal the token or delete the lease. |
| Wrong active drawing or changed host process | The job is rejected before its operation. Reconcile project identity; do not switch documents through a fallback. |
| Unclaimed job proven removed | Record nonexecution and repair readiness before a fresh authorized request. |
| Claimed timeout, host crash or uncertain publication | Preserve the lease and correlation ID. Use the ordinary `poll` route and inspect the document; do not replay. |
| Release rejected because work/acknowledgment is outstanding | Keep ownership until the result and completion fence are reconciled. |
| Malformed lease, missing token or unresolved crash | Stop native handoff for operator reconciliation. There is no expiry, force-release or automatic takeover. |
| Maintenance requested during project ownership | Finish/reconcile and release the project first. Project and maintenance leases are mutually exclusive. |

Status and static SDK contract discovery remain available without ownership.
Host-presence inspection is a native operation and needs the owner route.
The lease spans regeneration boundaries, but does not provide rollback or make
native commands transactional. See [architecture](ARCHITECTURE.md) for the
publication/completion protocol and [testing](TESTING_2027.md) for evidence limits.
