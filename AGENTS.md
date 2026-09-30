# Agent entry point: Vectorworks 2027 MCP

Read [docs/VECTORWORKS_2027.md](docs/VECTORWORKS_2027.md) first, then
[docs/INDEX.md](docs/INDEX.md) and the subsystem guide for your task. Do not load
all generated JSON or historical journals into context. Search the exact
function, contract or failure being changed.

## Project identity

- Primary use: landscape architecture. Prioritize verified project workflows
  from [design workflow](docs/DESIGN_WORKFLOW.md) and [roadmap](docs/ROADMAP.md)
  over expanding API counts. Keep generic SDK access for contract discovery.
- Supported native host: Vectorworks 2027 on Windows; SDK 3200/build 882699.
- The generated Python index has 3,098 functions. C++ SDK interfaces and
  `Handle` methods are outside that denominator.
- 294 handwritten MCP tools, 3,098 generated tools, 367 public handwritten verbs.
- Use [coverage](docs/TOOL_COVERAGE.md) for measured support. A wrapper, callable
  name or fake-host pass does not prove native operation.
- Old 2026 implementations and superseded setup notes were removed. Git history
  and the upstream repository retain them; they are not supported alternatives.

## Choose the smallest context

| Task | Read next | Main implementation |
|---|---|---|
| Landscape project workflow and priorities | [design workflow](docs/DESIGN_WORKFLOW.md) and [roadmap](docs/ROADMAP.md) | Existing handwritten workflows, then discovered SDK contracts |
| Client tools, timeout, queue, background policy | [mcp-server/AGENTS.md](mcp-server/AGENTS.md) | `vwx_mcp_server.py`, `background_policy.py`, `maintenance.py` |
| Handwritten commands, generated SDK execution | [vwx-plugin/AGENTS.md](vwx-plugin/AGENTS.md) | `commands.py`, `sdk_runtime.py`, `sdk_sequences.py`, `vwx_pump.py` |
| Native scheduling, palette, C++ helpers | [native/AGENTS.md](native/AGENTS.md) | `Source/Bridge/`, `VwxBridge2027.vcxproj` |
| Fixtures, assertions, fake host, evidence | [tests/AGENTS.md](tests/AGENTS.md) and [testing guide](docs/TESTING_2027.md) | `tests/`, `tools/sdk_*` |
| Generators, reports, maintenance controller | [tools/AGENTS.md](tools/AGENTS.md) | `tools/` |
| Build, deployment, client setup | [build/setup](docs/BUILD_SETUP.md) | `tools/build_2027.py`, `bridge/` |
| Known native discrepancies | [native investigations](docs/NATIVE_REPAIRS_2027.md) | Narrow compatibility branches plus original evidence |

## Invariants that apply everywhere

1. Every `vs.*` call runs on the Vectorworks main thread inside the **Python
   menu-command runner**. Native timers, notifications and palette web callbacks
   never execute Python. The current V4 broker invokes the fixed SDK menu name
   `VWX Bridge Start`. One invocation consumes at most one queued job.
2. A claimed job is consumed before dispatch. Never replay it automatically
   after timeout, crash or uncertain completion. Do not clear a lease, queue or
   completion fence to make a failing test appear healthy.
3. Creation/reset and regeneration-dependent inspection belong in separate
   jobs. `sdk_sequence`, `vwx_batch` and a script each remain one job. A sequence
   has no rollback. Returning to the event loop is necessary but is not itself
   proof that regeneration finished.
4. All clients share the active drawing. Use `project_session` and `project_execute`
   for coordinated multi-agent native work; every owner job verifies the exact
   saved drawing. This is not a transaction. Agents may prepare/review concurrently,
   but only one owner performs native work. Never steal or force-clear a lease.
5. Use UUID strings for document objects. Validate the object type and required
   context. Do not invent handles, resource indices, pointers or event contexts.
6. Preserve the distinction between native results, compatibility replacements,
   undispatched rejection, characterization and uncertainty. A documented
   failure remains evidence after a later repair passes.

## Workstation and deployment

Use typed MCP/API routes so the user can work in other applications. Keep
`VWX_BACKGROUND_MODE=1`; it blocks known interactive operations and unchecked
scripts before queue publication. Do not bypass it with direct IPC, force flags,
mouse/keyboard injection or unsolicited focus changes. Vectorworks must remain
open and unminimized, with its palette open and unpaused.

Use [controlled maintenance](docs/MAINTENANCE_2027.md) for authorized automatic
save/restart work. It requires the one exact saved drawing, a persistent lease,
verified native save, actual process exit and a verified replacement installation.
Do not force-kill Vectorworks, discard changes, suppress security prompts, or
retry a consumed maintenance action. Startup problems may still need the user.

## Implementing changes

- Discover an existing handwritten command before adding a new wrapper.
  `@vtool` in the server must keep `output_schema=None` and a registration-time
  tag in `tool_tags.py`; update the verb in `commands.py` alongside it.
- Use `sdk_list` for effective SDK contracts and `vs_signature` for the source
  index. Do not guess arity or return shape from another year's SDK.
- Generated files are `vs_index.json`, `vs_index_meta.json`, `sdk_catalog.json`
  and `sdk_generated.py`. Change their generator/source correction, then
  regenerate; never patch individual generated signatures by hand.
- Keep measured-build compatibility guards narrow, disclose original results,
  and test both guard rejection and actual corrected behavior. See the native
  investigations before changing HArea, text lengths, opacity or arc handling.
- UTF-16 `.vwstrings` resources retain their BOM/encoding. Python and JSON use
  LF; source provenance is byte-sensitive. Never rewrite empirical source hashes
  merely because current source changed.
- Keep documents, credentials, vendor SDKs, build output and local `.audit/`
  artifacts out of commits. The credential example is a template only.

## Validation and handoff

Run focused tests for changed behavior, then the required offline checks:

```powershell
python -m unittest discover -s tests -v
python tools/pruefe_konsistenz.py .
python tools/sdk_test_matrix.py --check
python tools/api_coverage.py --check
python tools/check_repository.py
```

Use the configured Python environment with `mcp-server/requirements.txt`.
For native changes, build against SDK 3200 and run the compiled harnesses. A
successful build is not deployment or live verification. For generator changes,
use the pinned SDK's `vs.py` and the generator validation commands from the setup
guide. Regenerate current matrix/coverage reports when their source inputs
change; preserve historical run provenance.

Live tests require an explicitly authorized disposable drawing and fresh run
IDs. Design meaningful inputs and independent expected outcomes; never spray
generated invalid arguments into Vectorworks. See [testing](docs/TESTING_2027.md)
for planning, execution, import and stopping rules.

Before handing off, update the relevant subsystem guide or contract if behavior
changed, regenerate affected reports, and state what was tested, what was
deployed and what remains unverified. Keep current instructions concise; put
measured native findings in their evidence documents rather than copying long
session transcripts into every guide.
