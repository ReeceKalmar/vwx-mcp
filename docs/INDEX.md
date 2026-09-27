# Documentation map

Start with [current 2027 context](VECTORWORKS_2027.md). Each guide below owns a
specific topic so an agent can read the relevant part without loading the whole
repository into its context window.

## Use and develop

| Guide | What it owns |
|---|---|
| [README](../README.md) | Project scope, quick start and support boundary |
| [Agent entry point](../AGENTS.md) | Cross-project invariants and task routing |
| [Build and setup](BUILD_SETUP.md) | Prerequisites, compiler, first installation, MCP configuration and verification |
| [Architecture](ARCHITECTURE.md) | Request lifecycle, files, failure semantics and component relationships |
| [Server context](../mcp-server/AGENTS.md) | MCP registration, transport, interaction policy, caching and maintenance leases |
| [Host Python context](../vwx-plugin/AGENTS.md) | Menu runner, commands, UUIDs, adapter and sequence contracts |
| [Native context](../native/AGENTS.md) | C++ scheduling, status publication, palette resources and native helper ABI |
| [Tooling context](../tools/AGENTS.md) | Generators, build/report commands and test runners |
| [Test context](../tests/AGENTS.md) | Test families, fakes, compiled harnesses and failure attribution |
| [SDK adapter contracts](SDK_ADAPTERS_2027.md) | Named arguments, JSON types, contexts, sequences, callbacks and compatibility |
| [Background operation](BACKGROUND_WORK.md) | Unattended use, interactive blocks and delivery diagnostics |
| [Controlled maintenance](MAINTENANCE_2027.md) | Save/quit/deploy/reopen protocol and recovery boundaries |
| [Testing](TESTING_2027.md) | Offline/live commands, fixture inventory, independent oracles and evidence import |
| [Coverage](TOOL_COVERAGE.md) | Meaning of counts and current implementation/native-test limits |
| [Roadmap](ROADMAP.md) | Outstanding work, including unsupported contexts and unconfirmed APIs |
| [Developer credentials](PLUGIN_CREDENTIALS.md) | Request template, issuance and startup approval |
| [Publication notes](PUBLICATION_2027.md) | Cleanup scope, removed legacy paths and validation checkpoint |

## Investigate a native discrepancy

[NATIVE_REPAIRS_2027.md](NATIVE_REPAIRS_2027.md) is the current investigation
entry point. [REGRESSION_FINDINGS_2027.md](REGRESSION_FINDINGS_2027.md) retains
earlier failed expectations and fixture corrections. The
[Vision startup record](VISION_STARTUP_2027.md) describes one installation's
measured repair, not a universal registry or file-copy procedure.

The small evidence records cover [arcs](ARC_REPAIR_2027.json),
[gradient return shape](GRADIENT_RETURN_2027.json),
[text indexing](TEXT_INDEXING_2027.json),
[worksheet bounds](WORKSHEET_LIMITS_2027.json),
[solid Boolean workflows](BOOLEAN_WORKFLOW_2027.json),
[background save](BACKGROUND_SAVE_2027.json),
[background delivery](BACKGROUND_DELIVERY_2027.json),
[first maintenance cycle](MAINTENANCE_2027.json),
[English palette/atomic-status maintenance](MAINTENANCE_ENGLISH_ATOMIC_2027.json),
and [guarded document transitions](DOCUMENT_TRANSITION_2027.json).
They retain their original build/source identities. Do not relabel old evidence
as a measurement of a new revision.

## Query the large inventories

Avoid reading these files in full into an agent conversation. Use a JSON parser
or a targeted search and report only the relevant function/category/counts.

| File | Authority |
|---|---|
| [vs_index.json](../vwx-plugin/vs_index.json) | Original SDK Python signatures |
| [vs_index_meta.json](../vwx-plugin/vs_index_meta.json) | SDK/index provenance |
| [sdk_catalog.json](../vwx-plugin/sdk_catalog.json) | Generated effective transport contracts and restrictions |
| [API_COVERAGE_2027.json](API_COVERAGE_2027.json) | Reproducible current tool/implementation/native counts |
| [SDK_TEST_MATRIX_2027.json](SDK_TEST_MATRIX_2027.json) | Per-function contract dimensions, mock outcome and native evidence |
| [LIVE_SDK_2027.json](LIVE_SDK_2027.json) | Recorded native/compatibility/uncertain API cases |
| [REGRESSION_RESULTS_2027.json](REGRESSION_RESULTS_2027.json) | Historical saved-run summaries, failures and incomplete plans |
| [LIVE_DEFAULT_SUITE_2027.json](LIVE_DEFAULT_SUITE_2027.json) | Audited union of the completed default suite |
| [SDK_HOST_PRESENCE_2027.json](SDK_HOST_PRESENCE_2027.json) | Callable-name inspection, not execution credit |

For example, query one function without loading the whole matrix into context:

```powershell
python -c "import json; from pathlib import Path; d=json.loads(Path('docs/SDK_TEST_MATRIX_2027.json').read_text(encoding='utf-8')); print(json.dumps(d['functions']['HArea'], indent=2))"
```

Local `.audit/` plans, journals, drawings and build logs are deliberately ignored
and are not required for a fresh checkout's offline tests. Published summaries
retain source hashes and may name those local paths; that is provenance, not a
promise that raw local artifacts are bundled. Re-running live tests produces
new evidence and requires a running, authorized host.
