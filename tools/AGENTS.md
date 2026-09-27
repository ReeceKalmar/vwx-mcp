# Build, fixture and audit tools context

Read [root guidance](../AGENTS.md), [build setup](../docs/BUILD_SETUP.md) and
[testing instructions](../docs/TESTING_2027.md). Run tools from the repository
root. Plan/report generation is offline; a plan is not authorization to execute.

| Tools | Responsibility |
|---|---|
| `build_2027.py` | Discover configured Windows toolchain and build the SDK 3200 target |
| `build_vs_index.py`, `build_sdk_wrappers.py` | Generate official SDK reference/bindings and verify source contracts |
| `pruefe_konsistenz.py`, `pruefe_vs_aufrufe.py` | Static wrapper/tag/SDK call checks |
| `sdk_test_matrix.py`, `api_coverage.py` | Reproducible source-hashed reports; mocks are not native passes |
| `sdk_*_fixtures.py`, `sdk_regression_suite.py` | Curated independent cases, stable identities, typed plans and registry validation |
| `sdk_design_runner.py`, `sdk_host_suite.py` | Original expected declarations, strict result oracles, journaling and host guards |
| `run_sdk_regression.py`, `run_sdk_regression_batch.py` | Explicit typed MCP execution, source/document checks, stop/no-replay behavior |
| `import_sdk_regression.py`, `sdk_regression_report.py` | Validate saved plans/results and summarize retained evidence |
| `check_sdk_host_presence.py` | Inspect callable names without executing them |
| `check_repository.py` | Read-only publication hygiene: links, empty content/directories and excluded artifacts |
| `check_sdk_background_delivery.py` | Bounded read-only delivery checks with strict host/hash/telemetry identity |
| `restart_vectorworks.py` | Cooperative maintenance lease, native save/quit, bound-process exit, deploy/reopen verification |

New fixtures use fresh named objects/resources and meaningful independent later
readbacks. Respect exact documented SDK types, selectors, units and lifecycles;
never generate arbitrary native arguments from a catalog. Keep creation/reset
separate from dependent inspection and preserve control objects. Existing user
objects, defaults, layer switching and interactive workflows are outside routine
fixtures. Name identities with the shared bounded helper; keep Unicode test
content independent of fixture naming.

Mark exploratory characterization explicitly. Default batches exclude diagnostic
and characterization families; explicit family selection does not waive other
guards. Every native run needs a fresh directory/run ID, exact disposable path,
matching runtime/provider hashes, measured host/SDK and typed MCP. No raw IPC,
keyboard, focus or hidden automatic replay. Stop on uncertain/native/transport
failure; continue an independent family only under the runner's verified mismatch
policy. Never modify source while a live plan is pinned.

The importer recomputes original expected assertions and checks ordered requests,
captures, identities and provenance. Do not trust recorded `passed` flags or add
credit to unexecuted steps. Preserve failures/uncertainty and reject conflicting
IDs. Jobs, APIs, assertions and repeated executions are different units; historical
remaining-plan totals are not a unique backlog. No fixture planning, callable
inspection or maintenance success earns SDK semantic credit.

## Common offline commands

```text
python tools/sdk_regression_suite.py --list
python tools/sdk_test_matrix.py --check
python tools/api_coverage.py --check
python -m unittest discover -s tests -p "test_sdk_regression*.py" -v
python -m unittest discover -s tests -p "test_restart_vectorworks.py" -v
```

Use the documented `--document`, `--plugin-dir`, `--output-dir`, `--family` and
explicit `--execute` flags for live runners. Inspect each CLI's `--help`; some
older harnesses are offline contract diagnostics, not background execution paths.
Maintenance tokens remain local recovery credentials and must not enter Git,
logs intended for publication, or checked-in audit summaries.
