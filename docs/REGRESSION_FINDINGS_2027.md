# Vectorworks 2027 regression findings — 2026-09-26

This is a historical checkpoint. For the current 2026-09-27 repair status and
verification, read [NATIVE_REPAIRS_2027.md](NATIVE_REPAIRS_2027.md) and the
[default-suite audit](LIVE_DEFAULT_SUITE_2027.json), which records 57 routine
families and 2,303 unique jobs passing across fresh batches. Statements below
about pending runs describe the checkpoint when they were recorded; original
failures and unresolved diagnostic cases remain preserved.

These checkpoints used Windows app build **882075** and SDK **3200 / 882699**.
They distinguish fixture mistakes from unresolved native behavior. Original
plans, responses, assertions and failures remain preserved; a later successful
run does not rewrite an earlier outcome. See [TESTING_2027.md](TESTING_2027.md)
for execution boundaries and [REGRESSION_RESULTS_2027.json](REGRESSION_RESULTS_2027.json)
for the generated run report. Job counts below are not distinct API counts.
The earlier C/D/E checkpoint offered **1,876 planned jobs in 55 families**,
including explicit diagnostics. The registry has since expanded; generate a
fresh plan with `tools/sdk_regression_suite.py` for its current summary.
Planned semantic jobs and characterization observations are counted separately,
and neither planned total establishes a native pass.

## Saved batch checkpoints

| Batch | Planned jobs | Executed | Passed | Failed | Unexecuted within stopped families |
|---|---:|---:|---:|---:|---:|
| `regression-expanded-live-20260926-c` | 838 | 427 | 415 | 12 | 411 |
| `regression-corrected-live-20260926-d` | 542 | 497 | 495 | 2 | 45 |
| `regression-final-live-20260926-e` | 80 | 75 | 74 | 1 | 5 |

All three batch manifests ended `completed_with_failures`. C passed all jobs in
six of its 18 families; D passed nine of 11; E passed one of two.
Each failed family stopped at its first
assertion mismatch. Continuing another independent family did not execute the
remaining jobs in the failed family. The exact local records are under
`.audit/<batch>/batch-plan.json`, `batch-result.json`, and each family directory's
`plan.json`, `journal.jsonl` and `result.json`.

## Fixture corrections with preserved evidence

| Finding | Classification and correction |
|---|---|
| Six C families expected names of 64–68 ASCII characters; `GetName` returned the first 63 | Fixture identity exceeded the observed host limit. New names use a shared deterministic helper capped at 60 ASCII characters, with a hash of the complete identity. Expected lookups use the same name. This is fixture isolation, not an SDK string-limit claim for every API. |
| An earlier symbol fixture expected `GetSymRot=270`; native returned `-90` | Equivalent angles. SDK reference specifies degrees without a canonical interval. The angular oracle now compares periodic equivalents while rejecting different directions. C's fresh symbol family passed all 44 jobs. |
| The first handwritten Boolean probe compared centroid `4.999999999999999` exactly with `5` | Numeric comparison was too strict. A fresh probe used `math.isclose` with relative and absolute tolerances `1e-9`; add, intersect and subtract passed independent readbacks. Both probes remain in [BOOLEAN_WORKFLOW_2027.json](BOOLEAN_WORKFLOW_2027.json), outside SDK API-case counts. |
| D expected `HWidth=20` for `RectangleN` with direction `[0,1]`, width 30 and height 20; native returned 30 | The fixture assumed projected width. SDK `HWidth`/`HHeight` document object dimensions; `GetBBox` explicitly documents screen-plane projection. E used analytic X/Y spans from `GetBBox`, without assuming an origin corner. Its axis-aligned, quarter-turn and oblique-rectangle checks passed before the separate oblique-oval discrepancy described below. The D failure remains recorded. |
| `Centroid` expected rectangle center `[15,10]` in drawing units; native returned `[381,254]` | The official [Centroid reference](https://github.com/Vectorworks/developer-scripting/blob/main/Function%20Reference/Functions/Centroid.md) specifies millimetres. The old fixture used the wrong output-unit contract. Routine `modeling_centroid_units` creates signed, asymmetric geometry from explicit millimetre strings through `ValidNumStr` and checks physical millimetre centroids. Independent inch/mm/cm/metre models check unit independence. All 31 jobs passed in `.audit/rootcause-batch-20260926-e/005-21eca0b358ff`; no runtime rescaling was added. |
| Historical final E expected tight contour bounds for an oblique oval | SDK `GetBBox` describes screen-plane projection, while `SetBBox` identifies ovals and rounded rectangles as box-defined primitives. F's independent oriented-construction, rotation and reset probes consistently returned the projected construction box. The current routine oracle uses that box's analytic spans. A fresh G semantic run is still required; F's characterization observations do not themselves pass the corrected family. |

## Unresolved contracts retained as diagnostics

| API or behavior | Recorded discrepancy | Current treatment |
|---|---|---|
| `CreateLight` / `GetLightInfo` | SDK XML documents 75% default brightness; C's directional light returned 100% | `resource_light_defaults` retains 75%. Routine light tests explicitly set their baselines; their success does not resolve the default discrepancy. |
| `GetNurbsObjectDistanceFromPoint` | Expected perpendicular distance 5; native returned `-127` | F's explicit-millimetre inputs produced distance magnitudes 5 and `sqrt(50)`, with interior signs reversed by curve direction. Endpoint-extension signs were not consistent under reversal. The reference does not specify signed or millimetre output; the old `[true,5]` oracle remains preserved and no runtime absolute-value or unit normalization was added. |
| `GetTextLeading` | Expected the documented noncustom-spacing sentinel `-1`; native returned `0` | A bounded compatibility repair independently checks `GetTextSpace` before returning `-1` for confirmed noncustom spacing. Three requests in the incomplete root-cause D run verified modes 2, 3 and 4 with the original zero disclosed; the later root-cause E family completed successfully. These getter outcomes remain compatibility evidence, not direct native getter passes. |
| Partial `SetTextStyleRefN` | Removing the style from positions 2–3 also left position 0 with reference 0 | `annotation_text_styles` retains the outside-range preservation expectation. F's new style-scope probe stopped earlier at independent resource-font setup: selector 1370 retained Arial after requesting Courier New. It therefore adds no new evidence about the partial-style operation. |
| Worksheet border clearing | After the earlier clear/inside-border sequence, cell `(2,2)` retained top and left borders | `annotation_ws_border_clearing` preserves the original reproduction. Routine edge-topology cases use independent worksheets; their success does not certify the clearing sequence. |
| Unicode `GetTextLength` | D read back `café 東京 café` correctly, but length was 18 against the planned character count 12 | `annotation_unicode_length` retains the original character-count expectation. Later characterization observed UTF-8 byte lengths for six text values. Formatting-offset probes remain separate; neither those observations nor the passing E replacement family prove an indexing correction. |
| `SetArc` / `GetArc` | Angles remained `[0,90]` after requesting start 90 and sweep 180 | F completed all 51 characterization jobs; all seven variants retained `[0,90]`, including integer/float inputs, both arc constructors, separate resets, and start-only/sweep-only changes. SDK XML and C++ wrappers specify degrees. A new geometry-discriminator probe is prepared to distinguish a setter no-op from a stale angle getter; it has no native result yet. |

Diagnostic families require explicit selection or the batch runner's
`--include-diagnostics`; they were not silently changed to match native results.
Characterization families require an explicit `--family`, independently of the
diagnostic flag. Their broader return-contract assertions record observations,
not semantic API passes, and the evidence importer refuses to promote them.
The corrected `modeling_centroid_units` family is now routine.

## Later repair and transport checkpoint

The preserved `.audit/rootcause-batch-20260926-d/001-5fb77f456bda` run planned
16 text-leading jobs. Fourteen completed with passing assertions, including
the three disclosed compatibility getter results above. The fifteenth
`GetTextSpace` request returned `VW_JOB_UNCLAIMED`; the sixteenth has no
recorded attempt. The original runner labeled the transport response
`SDK_DESIGN_ASSERTION`. The corrected offline report interprets its machine
code as one blocked, undispatched job: no native `GetTextSpace` failure and no
semantic failure attributed to its preceding `SetTextSpace` call.
The original result and journal are unchanged; nothing was automatically
replayed. The corrected classification does not make the family complete.

[NATIVE_REPAIRS_2027.md](NATIVE_REPAIRS_2027.md) records subsequent bounded
adapter corrections for text leading, opacity flags, material-name status and
native null handles, with their separate deployment and verification states.
Those changes preserve original responses and compatibility disclosures.
Passing compatibility cases do not become direct native API passes.

## Corrected batch D outcomes

D passed text layout (39 jobs), worksheet borders (80), textures (65), explicitly
initialized lights (89), bounds (45), duplicates (27), planar conversions (28),
routine NURBS sampling (34), and solid booleans (45). These verify the concrete
cases run, not every input or the excluded diagnostic behavior.

Two families remained incomplete:

- Text replacement read back the expected `café 東京 café`, but `GetTextLength`
  returned **18** against the planned character count **12**. The content edit
  passed; the length/counting contract remains unresolved. Fifteen later D jobs
  did not run, and the recorded expectation was not changed. E subsequently ran
  fresh replacement fixtures with this discrepancy isolated as a diagnostic.
- Oriented primitives stopped at the `HWidth` projection assumption described
  above. Thirty later D jobs did not run. E subsequently exercised the new
  `GetBBox` oracle and reached a different mismatch.

## Historical final batch E outcome and later bounds correction

E's text-replacement family passed **38 jobs**. The oriented-primitives family
completed **36 passing jobs**, then failed its 37th at
`oriented_oval_projected_bounds_2`; five later jobs did not run. It is not a
fully passing native family.

The oval used width 30, height 20 and unit direction `[0.6,0.8]`. Its preceding
area check passed `150π`, approximately `471.238898038469`. `GetBBox` returned
approximately `[[434,36],[468,0]]`, giving **34 × 36** spans. The independent tight
ellipse spans are:

```text
X = sqrt((30 × 0.6)^2 + (20 × 0.8)^2) = 24.083189157585
Y = sqrt((30 × 0.8)^2 + (20 × 0.6)^2) = 26.832815729997
```

The observed **34 × 36** exactly matches the rotated enclosing rectangle's
spans, `30×0.6 + 20×0.8` and `30×0.8 + 20×0.6`. At that checkpoint the single
result did not distinguish a cached bound from the primitive's construction
box. F supplied that independent comparison, described below. The old plan's
analytic ellipse spans and failed result remain unchanged; no tolerance was
widened to accept the larger box.

## Root-cause batch F: completed observations and remaining failures

`.audit/rootcause-batch-20260926-f` reached all 14 selected families and ended
`completed_with_failures`, with no transport failure or pending family. This
means every family reached an outcome; it does not mean every planned job ran.
Each failing family stopped at its first mismatch, and characterization
outcomes remain observations without native semantic coverage credit.

- `data_materials` passed all 30 jobs, including the unassigned null-handle
  case. `data_worksheet_operators` passed 70 and `data_worksheet_edge_edits`
  passed 66. These are concrete family results, not distinct API counts.
- The gradient probe confirmed `GetGradientDataN`'s six returned values for
  independent control and target segments, including opacities 71 and 37.
  After `SetGradientOpacity(..., 0)` returned successfully, the separate getter
  still returned **37**. That family recorded 25 successful jobs and one
  mismatch, then stopped; the shape correction did not repair the opacity
  setter's observed effect.
- The style-scope probe confirmed that `GetFontID`/`GetFontName` resolved both
  Arial and Courier New. On the fresh second style resource, integer selector
  **1370** read back Arial's ID **30** after setting Courier New's ID **97**.
  The independent name readback failed on record 15. The later partial-range
  style operations did not run, so this is a setup failure, not confirmation
  or rejection of their behavior.
- The worksheet database family stopped on record 34:
  `IsValidWSSubrowCell` returned `true` for the tested row-4 subrow-1 case against
  the fixture's `false` expectation. Operator and edge-edit successes do not
  settle this classifier contract.

The three geometry characterization families completed their requested
observations:

| Family | Observations | Finding |
|---|---:|---|
| `geometry_arc_characterization` | 51 | All seven post-set angle readbacks remained `[0,90]`; neither constructor choice, scalar representation nor separate reset resolved the discrepancy. |
| `modeling_nurbs_distance_characterization` | 43 | Physical-millimetre interior offsets returned left `-5`, right `+5`; reversing the curve reversed those signs. Endpoint-distance magnitudes were Euclidean segment distances, but collinear-extension signs were inconsistent. |
| `modeling_curve_bounds_characterization` | 30 | Both `OvalN`/`RRectangleN` and separately rotated `Oval`/`RRect` returned **34 × 36** spans before and after `ResetBBox`: eight matching bounds observations. |

The bounds correction follows the SDK distinction between an object's defining
box and its tight contour. `VectorScript Reference.xml` documents `GetBBox`'s
screen-plane projection and lists Oval and Rounded Rectangle among the objects
whose geometry is defined by a bounding box in `SetBBox`. For width `w`, height
`h` and unit direction `(dx,dy)`, the projected construction-box spans are
`w*abs(dx)+h*abs(dy)` and `w*abs(dy)+h*abs(dx)`. The corrected routine fixture
uses these formulas for all three primitives. Independent offline tests rotate
the four box corners, reject ignored direction, and distinguish tight contour
bounds from construction-box bounds. **Fresh native verification of this
corrected routine family remains pending for G.**

The new `geometry_arc_geometry_characterization` plan contains 40 observations
using a fresh quarter-arc control, a directly constructed target semicircle,
and a separate `SetArc` candidate. It preserves each original during
`ConvertToNURBS`, requires a later type-111 readback before sampling at length
fractions 0, 0.5 and 1, and records `HPerimN` as a supplementary measurement.
Analytic intended and unchanged points accompany the raw observations. Its
offline models distinguish an ineffective setter from a stale angle getter;
the new plan remains unexecuted and cannot earn semantic coverage credit.

The SDK-contract review used the local SDK's `vs.py`, `VectorScript Reference.xml`
and documented native type/constants headers. The C/D/E observations remain
preserved alongside subsequent fixture and bounded adapter corrections; an
expected result was not changed solely to make a host run pass. There is no
automatic replay, rollback, per-agent document isolation, or claim that the
remaining SDK surface has been verified.
