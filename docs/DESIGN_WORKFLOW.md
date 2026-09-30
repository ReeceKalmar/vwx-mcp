# Landscape architecture workflow

This bridge's primary purpose is to help an agent complete editable landscape
projects. Prioritize reliable site, surface, planting, grading, quantity and
sheet workflows. The generated SDK catalog is a discovery resource; implementing
or natively testing every API is not a prerequisite for useful design work.

Read [the execution contract](VECTORWORKS_2027.md) and the project's own scope
and evidence first. Use the default `landscape` profile; generic `sdk_list`,
`sdk_call` and `sdk_sequence` remain available. The profile reduces tool exposure
but does not change native capabilities or verify any object workflow.

## Work from the current project

1. Inventory surveys, drone DTM/DSM, orthophotos, site photos, existing drawings
   and user markup. Record units, horizontal/vertical datum, north, origin and
   source confidence. A DSM includes buildings and vegetation; use a DTM or
   surveyed elevations for ground. Label inferred dimensions and flat-site
   assumptions. Preserve established layers and organization in existing jobs.
2. Establish one native owner using the [project lease](MULTI_AGENT_WORKFLOW.md)
   and verify the exact saved drawing and fresh bridge readiness. Keep background
   mode enabled. Each owner job rechecks the document before dispatch. Work on prepared geometry and quantities
   offline when the required native operation is unavailable.
3. Model existing conditions first when starting a project. Preserve existing
   user design geometry for later authorized implementation. Do not infer a new
   proposed design from reference photos or replace existing work merely to
   standardize a project.
4. Use native editable objects for the requested features. Create/reset in one
   job, then inspect generated geometry in later jobs. Verify actual object type,
   parent/layer, footprint, holes, elevations and dimensions. An accepted field
   write or a successful reset does not establish regenerated geometry.
5. Keep source objects until their replacements pass the relevant geometric
   and identity checks. Retire only identified, owned sources. Honor user edits
   and scope reductions; geometric fidelity should match the task's declared
   tolerances and source accuracy.
6. Create native sheets, viewports and title blocks; review readable output.
   Verify the native save to the exact project path and establish a genuine
   backup. Distinguish saved work from independent reopen verification.

Use project-specified layers. Typical responsibilities are Hardscape, Landscape
(earthwork/site modifiers), Softscape, Plants, Trees, Structures, Furnishings,
Site Model, Site Data and Design. Layer membership alone is not proof of object
type or of existing/proposed status.

## Object workflows and current boundaries

| Work | Intended result and verification | Current boundary |
|---|---|---|
| Terrain | Native Site Model from elevation-bearing contours; check known XY/Z points and selected existing/proposed TIN | Constructor success is insufficient. The two handwritten elevation routes use SDK order `(dtm, tin_type, x, y)`; that correction is offline-tested, not newly native-certified. |
| Hardscape | Native paving, walks, gravel and patios; check outline/holes, finish levels, thickness and slope | Creation/parameter wrappers need separate native lifecycle verification. Preserve the real slope datum when splitting or replacing a surface. |
| Softscape | Native Landscape Areas with components, correct footprints and terrain relationships | Record elevations may differ from the generated body; check draped edges and interiors after terrain regeneration. |
| Grading | Native Site Modifiers with initialized controls and independently measured grade | Accepted slope fields can leave flat geometry. Do not treat a generic PIO constructor as a complete initialization workflow. |
| Plants and trees | Native Plant or Existing Tree objects, identified species/resource and accurate counts | `create_plant` inserts an existing symbol; it does not itself establish a Plant PIO. Inspect native type and data before claiming planting support. |
| Building context | Native slab, walls and Roof/Roof Faces; doors/windows where supported by source evidence | Model the exterior context needed for landscape coordination. Avoid speculative interiors or openings. Verify wall joins and roof relationships geometrically. |
| Decks, walls and fixtures | Appropriate native assemblies/resources, real heights and placements | PIO field writes may have no geometric effect. Discover the actual resource/universal name and verify the regenerated body. |
| Quantities | Object-linked native records and worksheets for new proposed work | `landscape_set_metadata` and `landscape_takeoff` classify and measure current proposed items, with explicit exclusions and optional sourced rates. Native worksheet publication and sloped/component volumes remain separate workflows. |
| Deliverables | Native sheets, viewports, title blocks, readable exported plans and save/backup | Prior published outputs do not prove that the latest model, sheets or export are current. |

Complex native workflows require explicitly authorized disposable-file tests
before becoming a supported recipe. Successful work in a client drawing is
valuable diagnostic evidence, not automatic credit in the SDK test reports.
Preserve original failures and measured-build limitations.
See [tool recipes](LANDSCAPE_TOOLS.md) for implemented terrain, template,
planting and quantity contracts and their offline/native evidence boundaries.

## Building context without repeated reconstruction

Source-ground the house footprint, slab level, roof form and relevant openings.
Use native building objects from the beginning when that workflow is verified.
A survey-derived mesh can describe source geometry, but should not silently
become the final editable house. Do not author generic display geometry and
then assume it can be converted into semantic walls or roof faces automatically.

Check the assembled exterior footprint, wall base/top profiles, roof planes and
clearances against independent source geometry. Near-collinear corners need
special verification; a wall join returning success does not certify a valid
footprint. Reusable native recipes should encode these checks so each design
agent does not rediscover them on a client drawing.

## Proposed work and acceptance

After the user supplies design intent, preserve the markup and build the
approved proposed work. Record existing/proposed status explicitly with stable
object UUID links. A newly modeled existing driveway is still existing work.
Quantities should track actual proposed area, length, height, volume or count
and update after edits/replacements. Include material and thickness where
needed; leave prices pending until real sourced rates are available.

Judge a workflow by a completed, editable, verified and saved result: correct
native objects, maintained source relationships, usable quantities, readable
sheets and preserved existing work. Track native jobs, avoidable rediscovery,
required UI steps and failures as workflow costs. Do not optimize by combining
creation and dependent inspection in one sequence or replaying uncertain work.
See [roadmap](ROADMAP.md) for implementation priorities and
[testing](TESTING_2027.md) for the verification process.
