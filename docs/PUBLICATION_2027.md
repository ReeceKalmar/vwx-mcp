# 2027 source publication checkpoint

This checkpoint packages the SDK 3200 bridge, generated adapters, offline/live
test tooling and measured results as a documented Windows source project.
It does not claim complete SDK functionality or add native passes merely by
publishing source. See [coverage](TOOL_COVERAGE.md) for the verification limits.

## Cleanup

- Removed the unused modal/TCP bridge scripts and unreachable server TCP and
  watchdog paths. The server accepts only the supported Vectorworks file
  transport; MCP stdio/HTTP remains available.
- Removed the 2026 native project and unreferenced macOS scaffold. The 2027
  Windows target is the sole supported native build.
- Removed obsolete FastMCP migration instructions and the duplicated 2026
  documentation archive. Their originals remain in Git/upstream history.
- Consolidated current architecture, SDK contracts, background instructions
  and roadmap. Added a documentation map, complete build/setup guide and
  focused agent guides for all five implementation/test subsystems.
- Strengthened SDK/compiler/resource-tool preflight and complete deployment
  input/path checks. Deployment verifies copied files using .NET SHA-256 and
  creates unique backups before replacing existing files.
- Added repository hygiene checks to CI for empty files/directories, relative
  documentation links and private/build artifact exclusions. No runtime cache,
  local audit journal or installed plug-in folder is part of the publication set.

Recorded native evidence remains intact, including original failed and
uncertain results. Large JSON evidence files are intentionally retained as
machine-queryable records rather than copied into agent entry guides. Local
paths in those records identify the original observations; `.audit/` artifacts
and drawings are not distributed. No issued developer credentials are included.

## Validation scope

The cleanup's actual SDK 3200 Release build succeeded. That is an offline build;
it was not deployed and does not replace the artifact identities in the saved
native evidence. Build/deployment changes have separate offline tests using
temporary SDK/install fixtures.

The initial staged-source export passed **818 offline tests in 91.704 seconds**
on Windows, with one symlink-creation test skipped because this account could
not create a symlink. The separate reparse-path tests and compiled native
harnesses passed. The earlier 793-test run predates the cleanup tests.

The clean export also passed repository hygiene/documentation links,
handwritten tool/tag consistency, SDK test-matrix and API-coverage freshness.
The generated wrappers and index matched SDK 3200 build 882699, and the
handwritten SDK-call audit reported no hard signature findings. Pending native
plans were generated offline without connecting to Vectorworks. No new native
verification or deployment is claimed by these checks.

The first GitHub run passed on Linux but exposed Windows 8.3 path aliases in
the hosted runner's temporary directory. Follow-up fixes canonicalize installer
and maintenance paths without relaxing reparse checks. The build and repository
hygiene test fixtures also compare canonical identities. Regression coverage
uses real Windows short-path aliases and verifies that redirected maintenance
paths are rejected before creating backups. These changes were not deployed to
the running Vectorworks installation. The full local rerun completed **821 tests
in 91.918 seconds**, with only the original symlink-privilege test skipped.
The actual short-path regressions, native compiled harnesses, repository hygiene
and current generated-report checks passed. Hosted results remain available
through the commit's GitHub Actions checks.

The earlier native baseline remains **57 default families / 2,303 unique jobs**,
with interruptions preserved in [its audit](LIVE_DEFAULT_SUITE_2027.json).
Confirmed native results cover **401 APIs**, with passing native cases for 399;
2,697 remain unconfirmed. There are still unsupported workflows and unresolved
diagnostic cases. Publishing this baseline does not certify all SDK operations.
