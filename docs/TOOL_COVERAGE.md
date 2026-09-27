# Vectorworks 2027 API coverage

All **3,098 SDK Python function names have generated adapters and named MCP
tools**. The handwritten workflows separately use **463 distinct SDK functions
(14.95%)**. Generated binding coverage is not native semantic verification.

| Measure | Count | Meaning |
|---|---:|---|
| SDK Python functions | 3,098 | Top-level functions in official SDK 3200 / build 882699 `vs.py` |
| Generated direct SDK bindings | 3,098 | Each `sdk_Name` declares a `vs.Name` binding; runtime compatibility paths are separate |
| Missing generated bindings | 0 | Every indexed function has an adapter |
| Handwritten SDK function use | 463 | Distinct calls from reachable handwritten commands/helpers |
| APIs without a handwritten workflow | 2,635 | Still exposed through generated adapters |
| Fake-host baseline dispatched | 2,882 | Runtime adapters reached an injected fake native callable in ordinary menu context |
| Local compatibility baseline | 1 | ASCII `UprString` executes Python uppercasing without calling native `vs.UprString` |
| Fake-host baseline rejected | 215 | Context/representation prerequisites rejected before native dispatch |
| Restrictions after sequence/force validation | 174 | 173 APIs have no supported workflow; `SetControlData` requires its implemented dialog-handler route |
| Handwritten MCP tools | 287 | `@vtool` registrations, including SDK discovery/call/sequence helpers |
| Named SDK MCP tools by default | 3,098 | Controlled by `VWX_SDK_TOOLS` and visibility presets |
| Total MCP tools by default | 3,385 | Handwritten plus generated registrations |
| Handwritten public dispatcher verbs | 362 | Public functions in `commands.py` |
| Generated dispatcher commands | 3,098 | Named `sdk_Name` routes |
| Total public dispatcher commands | 3,460 | Handwritten plus generated commands |
| Host adapter contract checks | 75,700 | Passed across all 3,098 API names under the recorded earlier source hashes; no native target calls |
| Current offline adapter contract checks | 75,701 | Adds the ASCII-workaround constraint; not repeated in the host |
| Planned fixture jobs | 3,362 | 2,439 native cases, three local compatibility cases, 47 conditional compatibility cases, 873 characterization observations |
| Independent fixture families | 78 | Design, numeric, geometry, data, annotation, resource and modeling providers |
| API names in planned native fixtures | 369 | Definite native cases; seven conditional and one local compatibility API are separate |
| Confirmed native API cases | 5,782 | 5,756 passing cases and 26 preserved failed assertions |
| SDK APIs with passing native cases | 399 | At least one measured passing case per API |
| SDK APIs with confirmed native results | 401 | Passing or failing native result, excluding uncertainty/compatibility-only evidence |
| Uncertain native attempts | 1 | `UprString`; no measured result and no native pass credit |
| SDK APIs attempted natively | 402 | Includes the uncertain `UprString` attempt |
| APIs with native fixtures still pending | 2,697 | No confirmed native result; partial passing fixtures do not certify every input |
| Compatibility cases | 70 | Eight APIs: disclosed area, ASCII-uppercase, leading, opacity-flag, material-status, UTF-16-length, gradient-opacity and arc repairs; all passed |
| Separate live adapter rejection checks | 7 | Passed without the requested native API dispatch |

The fake-host baseline uses one ordinary menu job without sequence permission
or `options.force`. Rejections include APIs that need balanced construction
sequences or explicit quarantine overrides, as well as unsupported event/native
pointer/callback contexts. A rejection is not counted as a successful SDK call.
Controlled sequence and quarantine validation reduces the 215 baseline
rejections to 174 direct-call restrictions. Of those, `SetControlData` has an
implemented controlled dialog-handler route; the remaining 173 APIs lack a
supported workflow. Background mode separately blocks interactive operations.
See [SDK_ADAPTERS_2027.md](SDK_ADAPTERS_2027.md) for invocation contracts.

Native fixture work is recorded separately in [LIVE_SDK_2027.json](LIVE_SDK_2027.json).
The table is the current 2026-09-27 aggregate. It retains the earlier typed-MCP
design series of 139 fixture jobs covering 104 APIs, all passed. The expanded
suite's [run report](REGRESSION_RESULTS_2027.json) audits 141 saved run plans,
including one missing result after a blocked provenance prelude. There are
5,519 executed fixture jobs: 4,884 passes, 28 failed assertions and 607
characterization observations. Two additional blocked requests were never
executed and are separate from the executed-job count. There is no
invalid-attribution credit. Jobs, API cases
and distinct APIs are different units; a job may contain several API calls.
Neither uncertain attempts nor compatibility-only results count as confirmed
native results. The report's 1,866 unrecorded jobs sum the exact historical plans,
including repeated and stopped families; they are not a current unique backlog
and are never automatically replayed.

The [default-suite audit](LIVE_DEFAULT_SUITE_2027.json) verifies all **57 routine
families and 2,303 unique fixture jobs** across fresh batches A, B and C. There
were 2,343 passing job executions, including 40 extra passes from an interrupted
family before its fresh run. Those repetitions are not additional unique
coverage. The default selection excludes eight semantic diagnostic families
and thirteen characterization families. Passing that selection does not resolve
their retained discrepancies or certify all 3,098 APIs.

The 26 failed API assertions retain both unresolved native discrepancies and
historical fixture mistakes, such as overlong names or an equivalent angle.
They do not establish 26 native API defects. Later corrected cases preserve the
earlier outcomes. Text leading, material status, opacity flags and Unicode
length now have measured repairs; physical centroid units and projected
primitive bounds have corrected, passing fixtures. Remaining investigations
include text-style propagation and worksheet
predicate/border semantics. A fresh resource-tag fixture passed, and the earlier
idle scheduler label did not establish an open dialog. See
[the classified findings](REGRESSION_FINDINGS_2027.md) and
[earlier recorded cases](VECTORWORKS_2027.md#recorded-native-cases).

Tools, commands, SDK functions and call sites are different units. Several
handwritten tools can share an API, and one workflow can use many APIs.
`execute_script` and signature lookup are not included in generated coverage:
the counted adapters contain actual named bindings. This report excludes C++
interfaces and methods on the SDK stub's `Handle` classes.

## Reproduce the report

```powershell
python tools/sdk_test_matrix.py
python tools/sdk_test_matrix.py --check
python tools/api_coverage.py
python tools/api_coverage.py --check
python -m unittest discover -s tests -v
```

[API_COVERAGE_2027.json](API_COVERAGE_2027.json) records source hashes,
handwritten invocation locations, generated bindings, mock-dispatched/rejected
lists with reasons, registrations, categories and unresolved dynamic lookups.
When [LIVE_SDK_2027.json](LIVE_SDK_2027.json) is present, its source hash and
case-level native pass/fail counts, uncertain native attempts and compatibility
results are included separately. An API with both native outcomes keeps both;
no passing case earns full semantic verification. APIs with only uncertain or
compatibility evidence retain pending native fixtures.
The [native report](LIVE_SDK_2027.json) records application build 882075 and SDK
build 882699. Adapter rejection checks are not counted as executed SDK functions.
[SDK_TEST_MATRIX_2027.json](SDK_TEST_MATRIX_2027.json) records each API's argument
test dimensions, injected fake-host baseline, required native fixtures and
measured native cases or pending live status.

Handwritten analysis follows public commands and explicitly addressed private
targets through local helpers/callbacks, aliases and finite literal `getattr`
names. Branches are conservative; dead private helpers, examples, legacy
bridges and caller-supplied scripts do not count. Generated analysis requires
a correctly named direct `vs.Name` binding. It does not count a catalog entry
or arbitrary dynamic dispatcher as an implementation.

The fake-host probe imports only the runtime adapter and supplies a fake
version/UUID resolver and an independently indexed callable signature. It never
imports the real `vs` module or opens a host connection.

## Test and verification limits

The final publication run passed **821 tests in 91.918 seconds**, with one Windows
symlink test skipped (see [publication details](PUBLICATION_2027.md)), including
all **75,701** current
adapter-contract cases. These include independent fixture models,
adversarial response and provenance checks, and strict evidence-import tests.
Generated-wrapper/report freshness, static API arity and wrapper/tag consistency
checks also passed. Offline success does not clear the native
failures or establish native results for pending APIs.
The earlier 781- and 793-test checkpoints remain historical; publication checks
used normal temporary-file access without weakening assertions.

Verified [maintenance cycles](MAINTENANCE_2027.md),
[background delivery](BACKGROUND_DELIVERY_2027.json), and
[diagnostic-read recovery](NATIVE_REPAIRS_2027.md#atomic-diagnostic-file-publication)
are operational evidence. They do not add SDK semantic pass credit or establish
independent desktop-focus measurements. Their original failed attempts, exact
build hashes and bounded conclusions remain in those records.

The exhaustive binding suite checks all 3,098 generated wrappers, all 6,694
required-parameter omissions, unknown arguments and malformed envelopes.
For APIs allowed in the default mock context it also checks **26,909** invalid
type/range mutations, **12,958** accepted primitive ABI boundaries, argument
conversion and malformed return handling. Context-rejected APIs do not receive
credit for type checks that their context guard prevents from running.

`tools/sdk_host_suite.py` produces executable deployed-adapter checks and
separate curated native fixtures. Its dispatch canaries and validation-only
checks establish adapter behavior without calling the requested native APIs.
`tools/sdk_regression_suite.py` combines design, numeric, geometry, data,
annotation, resource and modeling
recipes with independent assertions and later setter readbacks.
`tools/run_sdk_regression.py --execute` sends only typed MCP SDK calls through
the normal background-policy path. Plans pin the exact disposable document and
deployed source hashes; journals record intent before dispatch and never replay
uncertain mutations. The importer binds requests, resolved captures and expected
declarations to the original saved plan, recomputes assertions and rejects
incorrect identity, provenance or pass credit. Imported regression runs retain
that plan binding. Characterization-only plans cannot be imported as semantic
API passes.
See [TESTING_2027.md](TESTING_2027.md) for reproduction and import commands.
The [callable-presence probe](SDK_HOST_PRESENCE_2027.json) inspected all 3,098
names: 3,081 callable and 17 absent, with no inspection errors. It establishes
availability only, not invocation context or semantics. The
[delivery record](BACKGROUND_DELIVERY_2027.json) keeps earlier blocked V3 and
later successful V4 requests separate from API fixture evidence.

These tests establish Python transport contracts against fakes. A range-valid
resource index or geometry value may still be invalid for a specific native
operation. All possible semantic edge cases have not been implemented or tested.
Native geometry, callbacks, modal UI, plug-in objects and deferred regeneration
require separately designed, controlled host fixtures.

All reads and writes use the Python menu-command runner, one queued job per
invocation. A sequence is one job and has no regeneration break between steps.
See [VECTORWORKS_2027.md](VECTORWORKS_2027.md) for the current host/build evidence.
