# Vectorworks 2027 migration

## SDK and build

- Official Windows SDK, build 882699, `SDK_VERSION=3200`.
- Native x64 Release build uses MSVC v143 14.42.34433 and C++20.
- Public headers require native `wchar_t` to distinguish overloads from
  `unsigned short`; the project explicitly overrides the stale SDK property-sheet
  default. The compiled library links successfully against `VWSDK.lib`.
- Compile-time SDK assertion prevents an accidental 2026 binary under the 2027
  filename. Separate output directories prevent stale binaries being deployed.
- `tools/build_2027.py` discovers VS2022-compatible targets, including when the
  compiler is installed alongside VS2026. It normalizes duplicate Windows
  environment variable casing only for the child build process.
- `vwx-plugin/vs_index_meta.json` records source and index hashes. The regenerated
  index has 3,098 functions: 28 additions, one removal (`Prot_GetLicenseType`),
  and no argument-list changes among shared functions compared with upstream's
  3,071-function index. `Prot_GetAppMode` is present in the 2027 API.

## Execution changes

The server defaults to 2027 and rejects a different explicit host year. A missing
explicit plug-in directory produces an error instead of falling back to another
installation. The native binary derives its host folder from `SDK_VERSION`.
The menu script checks the running application version before importing the pump.

The 2027 native palette has no Python script-engine call or read-only notification
executor. Both reads and writes go through Vectorworks' Python menu-command
runner. The pump executes one job and returns, including when new work arrives
mid-execution. Reentry is refused, and jobs are consumed before native dispatch so
a crash cannot cause automatic mutation replay. Error dialogs are preserved.

These changes address plausible execution-context and deferred-regeneration
risks observed during native-object work. The precise cause of the earlier
application crashes has not been isolated. A newer SDK alone is not a proven fix.

## Verification boundary

Verified offline on Windows:

- Native 2027 Release compilation, linking and VWR resource packaging.
- Nine regression tests covering queue ordering, one job per invocation,
  jobs arriving during dispatch, reentry, crash/no-replay behavior, disabled
  notification reads, version selection and API-index provenance.
- Static API-name scan: 858 calls across commands and menu launcher, no unknown
  function names. Existing arity warnings require live verification; tuple
  argument conventions can make these warnings ambiguous.
- Upstream consistency checker reports nine existing findings on both upstream
  and this fork. This migration introduces no additional findings. Those existing
  wrapper/parameter mismatches are not certified as working by this build.

Live host checks and modeling operations must be recorded separately. Until then,
native Hardscape, Landscape Area, wall, roof and site-model workflows are **not
certified**. Test in a disposable file before editing a project. Do not use Python
threading or timer callbacks to invoke the Vectorworks API.

## Rebuilding the API reference

`python tools/build_vs_index.py <SDKLib/Include/vs.py> vwx-plugin/vs_index.json`
regenerates the index. After changing SDK builds, update the companion metadata
with the new SDK version/build, function count and SHA-256 hashes; the regression
test refuses stale index metadata. Do not commit the SDK archive, libraries,
headers, developer credential files or project drawings.
