# Vision startup finding on the tested 2027 installation

On 2026-09-27, restoring one vendor-configured compatibility registry entry
was followed by a successful Vectorworks startup. Process 41536 reached the
expected drawing and typed native document inventory; the old maintenance
lease was released. The user explicitly confirmed, "No warning appeared."
A subsequent read-only window inventory found no Vision dialog, and the bridge
reported fresh idle telemetry. These observations concern Windows app build
882075 and the installed files inspected here, not every 2027 installation.

## Evidence and the targeted repair

The read-only binary/configuration inspection found:

- The outer `Plug-Ins/SpotlightVision.vlb` contains the expected 2027
  `CommonPath` registry reference.
- The installed `Vision/sVisionPlugin_2017_64.dll` and `Vision/VisionPhysics.dll`
  contain references to `Software\Vectorworks\Vectorworks 2026\CommonPath`.
- The installed 2027 Install Manager's `cli-settings.json` explicitly declares
  a compatibility registration, `commonPathWorkaroundU0`, mapping that legacy
  key's default `REG_SZ` value to `${commonDir}`.
- That 64-bit `HKLM` compatibility key was absent. The ordinary 2027 key and
  the required shared library data were already present.

After UAC approval, the repair restored only the absent vendor-declared entry,
with value `C:\Program Files\Common Files\Vectorworks 2027`. The previous absent
state was recorded for reversibility. No application files, plug-ins or license
data were moved or modified by this repair. Static string references alone do
not trace the failing execution branch; the subsequent successful startup and
user confirmation provide the separate observed outcome.

Local audit records retain the exact inspected hashes, registry state and results:

- `.audit/vision-commonpath-static-diagnosis-20260927.json`
- `.audit/vision-path-repair-20260927-a/before.json` and `result.json`
- `.audit/vision-startup-verification-20260927-a/result.json` and
  `read-only-window-diagnosis.json`

The startup result initially recorded dialog absence as unverified; the later
window inventory and user confirmation supplement it without rewriting that
earlier result.

## Troubleshooting boundary

For a different installation, inspect its actual versions, vendor installer
settings, registration and shared data first. This record is not a general
registry recipe. Do not copy whole application trees into `Vision`, patch
binaries, or overwrite an existing compatibility value based on these findings.

The user had separately copied application contents into `Vision` before this
repair. Those copies are still present. A read-only inventory is recorded in
`.audit/vision-copy-audit-20260927.json`; any cleanup remains subject to review
and revalidation. Successful startup does not certify those copies as necessary.

The separate `.audit/maintenance-native-20260927-a` run subsequently verified
one controlled native save/quit/deploy/reopen cycle from process 41536 to 50096.
Its [checked maintenance audit](MAINTENANCE_2027.json) records that result;
startup recovery alone did not establish it. See
[controlled maintenance](MAINTENANCE_2027.md) and [native repair evidence](NATIVE_REPAIRS_2027.md).
