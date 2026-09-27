# Python host bridge context

Read [root guidance](../AGENTS.md) and [the 2027 contract](../docs/VECTORWORKS_2027.md).
These files load inside Vectorworks' Python menu-command context.

| File | Responsibility |
|---|---|
| `BridgeStart_MenuCommand.py` | Host/install checks and one outer pump invocation |
| `vwx_pump.py` | Reentry guard, atomic claim/consume, one job, result and completion stamps |
| `commands.py` | Handwritten workflow verbs and UUID/native object helpers |
| `sdk_runtime.py` | Argument/handle/context/result validation and disclosed compatibility repairs |
| `sdk_sequences.py` | Up to 200 balanced same-job calls, references and scope cleanup |
| `sdk_catalog.json`, `sdk_generated.py` | Generated SDK bindings; regenerate, never hand-edit |
| `vs_index.json`, `vs_index_meta.json` | SDK reference and provenance; regenerate together |

Every `vs.*` call must stay on the authorized menu runner. Never add Python
threads, notification/timer execution, reentrant pumping or automatic retries.
Consume a claimed job before dispatch; only the outer invocation may stamp
completion. Creation/reset and regeneration-dependent inspection need separate
requests. Sequences have no rollback or regeneration break.

Resolve UUIDs and validate object types; type-zero lookup handles are invalid.
Collect iterator results before mutation, bound traversal and verify nested
parentage. Use replacement handles returned by conversion/import/booleans.
Preserve exact tuple/in-out SDK conventions and use catalog names, not guessed
selectors. Expected values must come from documented contracts or independent
measurements, not from the implementation being tested.

Preserve compatibility metadata, original values, exact-build guards and
pre/post-write dispatch state. A compatibility success never becomes a native
pass. Do not call the broken gradient-opacity binding before its replacement,
retry native `UprString`, or weaken the private arc/maintenance ABI checks.
Maintenance save/quit rechecks the sole expected saved drawing and owner lease;
no discard, force-kill or dialog dismissal fallback is permitted.

## Native design command contracts

Terrain queries pass `(model, tin_type, x, y)` to `DTM6_GetZatXY`, with finite
coordinates, TIN 0/1/2 and verified model identity/readiness. Implicit discovery
accepts only one model on the requested layer and never opens the SDK model
picker; pass an exact `site_model_id` when several models exist. Failed queries
do not expose undefined elevation outputs. Recheck an unready model in a later
job without replaying its preceding mutation.

`get_walls` returns top/bottom endpoint levels, `start_height`, `end_height` and
numeric `thickness`; `height` is null for unequal endpoint heights. Per-field
errors remain explicit. Selector 173 is not a wall-height contract.
Its `bounds` field comes from `GetBBox`, which projects onto the screen plane;
it is not a model-space geometry oracle. A reconciled native Wall returned all
zero screen bounds while its endpoints, 3D spans and center matched the request.
For a straight Wall, check `GetWallPathType`, `GetSegPt1/2`, `Get3DInfo` and
`Get3DCntr` in later jobs against independent expected geometry. In that measured
case, `Get3DInfo` returned Y/X/Z spans (`height`, `width`, `depth`); `depth` was
the vertical span. Keep layer elevation, view and intended placement explicit.
Do not recreate or reset an object merely because its screen bounds are zero.

`create_wall` owns only its newly created type-68 UUID. It leaves document wall
defaults alone, removes an inherited style only from that new instance, and
preserves inherited components/materials while scaling their widths
proportionally to the requested thickness. It requires at least one component,
strict native success flags and matching component-width parameter readbacks.
Height uses `SetWallOverallHeights` with bottom/top bound to layer Z at offsets
0/height. It avoids the failed `SetWallHeights` binding and does not delete or
insert components. Failures retain the partial object's UUID and failing phase;
never retry the creation automatically. Success means accepted parameters, with
`geometry_verified=false`; call `get_walls` in a later job for parameter
readbacks and use the independent geometry checks above. The unstyled
single-component constructor passed a separate native dimensional readback in
an inch-based disposable drawing; styled and multiple-component branches have
offline tests only. [Wall repair evidence](../docs/WALL_CREATION_2027.json) pins
that deployment and preserves the non-Boolean `SetWallHeights` diagnostic and
false `DeleteAllComponents` result. Their raw failures must not be relabeled
as native success; save/reopen persistence remains unverified.

Component material/texture setters require documented architectural object or
style types, a valid component index and a typed named resource. They resolve
LONGINT references with `Name2Index`, honor native false and read back the stored
parameter before reset. `parameter_verified` does not verify regenerated
geometry; perform that inspection in a later job. Errors report whether a
mutation was dispatched and never retry it. Hardscape/Landscape Area PIOs need
a separately verified component-owner workflow; these setters reject generic
PIO handles, except the measured modern Slab identity: type86 with its hidden
`GetParametricRecord` of type48 named exactly `Slab`. An ordinary attached Slab
record is insufficient. One simple-material assignment on that Slab exception
passed native resource/name readback and separate unchanged dimensions, center,
height and path checks. Texture assignment and other assemblies remain separate
cases. See [architectural workflows](../docs/NATIVE_ARCHITECTURE_2027.md)
for the bounded native Slab evidence.

`join_walls` requires explicit finite `point_a`/`point_b` picks and two distinct
type68 objects with `GetWallPathType=0`. Native acceptance is not geometry
verification; inspect later and retain dispatched failures without retry.

Resource nesting inspection uses a shared callback budget, canonical UUID
cycle checks and verified immediate parentage before traversal. `nesting_count`
is a bounded diagnostic, not proof of complete inspection. `resource_info`
reports `contents_complete` for its immediate list and only infers a plug-in
style from a complete one-PIO list. A nesting check's `clean` flag cannot certify
complete geometry. Create/read/import resource lists in the same menu job;
cross-job list identifiers have returned empty names in the measured host.

## Checks from repository root

```text
python -m unittest discover -s tests -p "test_menu_runner.py" -v
python -m unittest discover -s tests -p "test_command_contracts_2027.py" -v
python -m unittest discover -s tests -p "test_native_design_command_contracts.py" -v
python -m unittest discover -s tests -p "test_plain_wall_creation.py" -v
python -m unittest discover -s tests -p "test_sdk_runtime.py" -v
python -m unittest discover -s tests -p "test_sdk_sequences.py" -v
python -m unittest discover -s tests -p "test_sdk_*repair*.py" -v
python tools/pruefe_vs_aufrufe.py vwx-plugin/vs_index.json vwx-plugin/commands.py vwx-plugin/BridgeStart_MenuCommand.py
```

Check a script's `--help` before supplying alternate roots/SDK paths. Follow
[BUILD_SETUP.md](../docs/BUILD_SETUP.md) for deployment and
[TESTING_2027.md](../docs/TESTING_2027.md) for independent typed native fixtures.
Changing generated-contract inputs requires wrapper/index and report freshness
checks; never rewrite empirical evidence merely to match new source.
