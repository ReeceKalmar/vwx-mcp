# Native architectural workflows: measured 2027 cases

These scoped tests used Vectorworks 2027 build 882075 and SDK 3200/build
882699 in an inch-based disposable drawing with layer elevation zero.
They are operational workflow evidence, separate from the imported per-API
coverage totals. Creation/reset and dependent geometry reads used separate menu
jobs. Diagnostic copies stayed in the disposable drawing; design deliverables
remain native architectural objects.

## Straight Wall joins

`join_walls` requires two distinct native straight Walls and both `point_a` and
`point_b` as finite `[x,y]` pick points in document units. The points choose the
ends/sides used by `JoinWalls`; passing handles in those POINT arguments was an
implementation error. Mode values are 1=T, 2=L, 3=X and 4=auto. The native tests
described here exercised mode 2 only. Type 68 alone does not prove straightness:
`GetWallPathType` must also return integer zero.

The server preserves raw JSON scalars before validation. FastMCP's coercion can
otherwise turn Boolean/string coordinates into numbers even when a Pydantic
`Strict*` annotation is present. Invalid UUIDs, missing/nonfinite pick points,
coerced mode/cap values and the same Wall twice are rejected before publication.
Host validation also protects generic dispatcher callers. Real FastMCP client
tests cover this boundary; direct Python calls alone would miss it.

Native True means the call was accepted, with `geometry_verified=false`.
False, non-Boolean returns and exceptions preserve dispatch state and both
object identities. Never retry a join automatically or infer rollback.

Five fresh uncapped convex/concave/orientation cases matched independently
computed dimensions and centers. A capped convex case produced a butt partition
instead of the proposed miter; its later complete footprints matched the
intended union without overlap. The original miter expectation remains failed.
A near-collinear case, approximately 0.128 degrees, returned True but failed its
strict geometric oracle and returned NIL from `WallFootPrint` for one Wall.
That case remains unresolved; a small dimension error alone cannot certify its
topology.

A fresh joined pair then tested explicit cap offsets derived independently from
its intended miter. Both `SetWallCapsOffsets` calls returned True; each Wall was
reset before later readback. Wall A's X span remained at its post-join value,
about 0.003576 inches above the predicted span against a 1.2e-6-inch tolerance.
The run stopped at that mismatch. Subsequent read-only diagnostics confirmed
the requested stored offsets, but `WallFootPrint` still returned NIL for Wall A.
The successful diagnostic collection is not a successful repair: the joined-cap
geometry remains failed, with no automatic rejoin, setter replay or deletion.
This does not establish whether the remaining defect lies in native join
geometry, regeneration or its geometry getters. Persistent join behavior still
needs separate tests. None of these observations certifies arbitrary wall
assemblies, component joins, curved Walls or save/reopen persistence.

A separate fresh pair used explicit native end-cap offsets without `JoinWalls`.
Both Walls passed later identity, axes, component, height, 3D-span and center
checks. Their complete `WallFootPrint` boundaries were closed four-corner
polylines without holes. Independent offset-line intersections matched all
vertices within the declared 1.2e-6-inch tolerance; the pair shared one complete
miter edge, with zero measured overlap and union difference below the declared
area tolerance. Both source Walls and the other 18 Walls were preserved.
This establishes physical assembly of editable native Walls for this case.
A false `GetEntityMatrix` result was retained, not interpreted as an identity
matrix; returned polyline XY was checked against parentage and the independent
geometry.

Two fresh perpendicular neighbors subsequently joined the original pair's
opposite ends through the corrected handwritten `join_walls` wrapper, using
explicit pick points, mode 2 and `capped=false`. Each native join ran exactly
once, without corrective cap setters or additional resets. The complete
four-Wall baseline passed before the first join; the first join's complete
footprint checks passed before the second was dispatched.

Both original near-miter cap arrays survived unchanged. After each join, all
four Walls retained the expected identity, axes, component, height, cap flags,
independent 3D spans and centers. Their complete closed, hole-free four-corner
footprints matched the independent polygons, including the shared edges and
four-Wall union. The final maximum vertex error was 1.861e-11 inches against
the fixed 1.2e-6-inch tolerance. Pairwise overlap was 1.175e-12 square inches and
union difference 2.350e-9 square inches, both below the fixed 0.000144-square-inch
tolerance. All 22 Wall identities and bounds were checked across each join,
preserving the recorded identities and Top/Plan bounds of the 18 controls.

This verifies survival of the physical near seam after those two perpendicular
opposite-end joins; it does not create a persistent native join at that seam.
The evidence combines complete returned-XY footprints with native 3D spans,
centers and heights, not a full triangulated-volume proof. Whole production
rings, arbitrary neighbor angles or styles, feet-based drawings, high elevations,
later edits and save/reopen persistence remain separate verification scopes.

## Roof Face

The measured native Roof Face is type 71 with public selector 172 equal to 1.
A balanced `BeginRoof`/polygon/`EndGroup` construction used a 10-by-8-inch
rectangle, rise/run 1/4, vertical miter, one 0.5-inch component, bottom component
datum and axis height 12. Component setters and later getters agreed.

Its defining polygon was accessible through `FIn3D`, not `FInGroup`. Validate
each candidate's actual parent/type before reading vertices. Four closed
vertices and the polygon's successful identity matrix confirmed the footprint.

For this Roof Face, raw `Get3DInfo` returned `[28,20,14.5153882032]` instead of
the expected Y/X/Z spans `[8,10,2.5153882032]`. The getter discrepancy is retained;
the bridge does not silently replace its result. `Get3DCntr` and the verified
Top/Plan screen bounds agreed with the intended placement. Do not generalize a
Wall's dimensional getter behavior to every native object family.

Independent verification preserved the native Roof Face, duplicated it and
converted only the diagnostic duplicate with `ConvertTo3DPolys`. Bounded reads
of six actual polygon faces yielded eight vertices and twelve shared edges.
An independent halfspace/plane, area, watertight-edge, volume and centroid oracle
confirmed the expected body: normal thickness 0.5 inches, vertical thickness
0.5153882032 inches and volume 41.2310562562 cubic inches. A NURBS copy also had
the correct extents, but two underlying surface control nets extended beyond
their trims; raw NURBS control points must not be treated as a closed boundary.

Changing the original axis height from 12 to 15, resetting and reading later
moved its center up exactly 3 inches. A fresh kept-original NURBS diagnostic
copy confirmed unchanged dimensions and the new center. This edit test checked
dimensions/placement; the full polygon topology test belongs to the first body.

`GetRoofFaceCoords` returned grouped outputs, with XY values equal to the
literal coordinates divided by 25.4 in this inch drawing. The original SDK XML
contains a historical scaling example, but this single measurement does not
authorize a general unit correction. Preserve raw outputs and cross-check
actual geometry. Other units, slopes, miters, holes, styles, multiple components
and saved-file persistence remain separate cases.

### Reusable roof-body oracle

[`validate_roof_body`](../tools/sdk_architecture_oracles.py) checks an explicit
rectangular XY footprint bounded by two parallel sloped planes and four vertical
sides. Supply independently captured boundary polygons as dictionaries with
exactly `face_id` (a unique local label) and `points` (ordered XYZ triples):

```python
from tools.sdk_architecture_oracles import validate_roof_body

report = validate_roof_body(
    polygons, x_bounds=(10, 20), y_bounds=(20, 28), base_z=12,
    slope_xy=(0, 0.25), normal_thickness=0.5, abs_tol=1e-7,
)
```

`base_z` is the lower plane at the minimum X/Y corner; thickness is perpendicular
to the sloped plane. Coordinates, thickness and tolerance use the same length
unit. The oracle checks independent halfspaces, face areas, opposite paired
edges, expected corners/extents, volume and centroid. Invalid or inconsistent
input raises `RoofGeometryError`. Either winding and convex subdivisions with
matching shared-edge segmentation are accepted. Watertightness is within the
specified vertex-welding tolerance, not an exact-arithmetic topology certificate.

This is an offline mathematical check: callers must separately establish native
identity, capture completeness/provenance, units and regeneration. Raw untrimmed
NURBS control nets are not boundary polygons. Holes, dormers, curved faces,
arbitrary footprints and general architectural roofs are outside this contract.
The [21 focused tests](../tests/test_architecture_oracles.py) cover malformed,
omitted/duplicate and oversized faces; Boolean/nonfinite inputs; orientation,
translation, independent volume/centroid expectations and failure under
`python -O`. They add no native API coverage credit.

## Architectural Slab

`CreateSlab` produced **type 86**, with a hidden parametric record of type 48
named exactly **`Slab`**. Do not confuse it with the older type-71/kind-2 floor
primitive. The initially proposed legacy-node assertion failed and is retained.
The modern Slab independently accepted and exposed its native style, component,
datum, manual edge-offset and height properties.

The measured case used a 10-by-8-inch profile, one 0.5-inch component, bottom
datum, zero manual edge offset and height 4. Later model spans were `[8,10,0.5]`
and center `(35,24,4.25)`. Raising height to 7 and resetting preserved the UUID,
width and spans, with center Z 7.25. A first exact floating-point width assertion
stopped at `0.5000000000000001`; subsequent read-only checks used a declared
1e-8-inch numerical tolerance without replaying any setters.

`GetCustomObjectPath` returned a type-21 polyline under an internal type-11
container whose parent was the Slab. The path had four corner vertices, was
closed and had no holes. Do not require every custom-object path's direct
parent to be the PIO; verify the bounded actual ownership chain instead.

Component resource setters recognize only this narrowly measured modern Slab
identity in addition to existing architectural owner types. A generic PIO or an
ordinary attached record named Slab is insufficient. This guard has offline
tests. Styles, multiple components, holes, nonzero layer elevations and
persistence remain unverified by this first case.

The modern Slab subsequently accepted one newly created simple Material through
the guarded handwritten component setter. A later native material-index/name
readback matched; component width, elevation, 3D dimensions, center and original
path remained unchanged. This verifies resource assignment for that one Slab,
not the material's rendered appearance, texture assignment or saved persistence.

## Historical offline validation checkpoints

The recorded full discovery run reported 981 test cases: **979 passed, one skipped,
and one was blocked from execution**. Windows Code Integrity event 3077 rejected
the freshly compiled status-file harness executable before its process started.
That environmental block was unresolved at this checkpoint; the run is not an
all-tests-pass result, and no policy bypass was used. The changed Python behavior also passed
57 focused tests. Native C++ was unchanged in that
checkpoint.

The subsequently added roof oracle separately passed all **21 focused tests**,
with no skips, including an independent review and rerun. It also accepted the
previously captured six native roof boundary polygons, independently reproducing
their volume, centroid, extents and closed edge incidence. This offline
reassessment makes no new native calls or combined full-suite rerun claim.

The [testing guide](TESTING_2027.md#earlier-checkpoints-and-native-evidence)
records the subsequent hosted results and their harness skips. It also owns the
[latest local checkpoint](TESTING_2027.md#current-offline-checkpoint). Later passes
do not erase the original Code Integrity block or add native geometry evidence.

## Provenance and delivery

Named resource imports use the existing same-job build/list/import workflow.
One native list reported 39 items, but its identifier returned an empty name
in the following menu job. A fresh same-job control returned the expected name
through both name getters. This is a lifecycle observation, not a general API
correction. Import diagnostics now bound callbacks, depth and visited UUIDs;
bounded nesting counts do not prove complete traversal or regenerated geometry.

Local `workflow-001-*` plans, journals and independent oracle reports retain
the original successes, failed hypotheses and read-only diagnoses. Their
pre-repair runtime used `commands.py` SHA-256
`45401f3f4933ec2067afaefced4a8995e96dc13c69d218b8c19b443f790225cb`
and the native library/archive pinned in [the current contract](VECTORWORKS_2027.md).
Later source fixes do not change those original evidence identities.

The early wall jobs had measured background delivery. Later jobs also ran when
Vectorworks was already foreground, with that delivery category recorded
separately. No mouse, keyboard, screenshots or focus changes were used. Native
geometry verification is not additional proof of background execution.
