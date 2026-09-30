# Landscape tools for design agents

Use this guide after [the design workflow](DESIGN_WORKFLOW.md). Examples below
are MCP arguments, not Python scripts to execute inside Vectorworks. Read-only
contract discovery works without the host. Native reads and writes need the
installed bridge, a saved drawing and an unpaused palette.

For multiple agents, acquire [project ownership](MULTI_AGENT_WORKFLOW.md) first.
While held, send each native command through `project_execute(token, command,
params)`; direct tools are blocked. Preparation and review can continue in
parallel, but one owner serializes native work across regeneration boundaries.

## Choose the existing workflow

| Task | Entry points | Check before accepting |
|---|---|---|
| Drawing and base plan | `get_document_info`, `get_document_units`, layer/class tools, criteria queries, geometry tools | Exact saved path, document units, survey origin/datum and source confidence |
| Terrain | `get_site_model_info`, `get_terrain_elevation`, `terrain_sample_points`, `update_site_model` | Actual Site Model identity; independent existing/proposed elevations after regeneration |
| Editable landscape objects | `landscape_object_info`, `landscape_duplicate_template` | Correct PIO, layer, path/holes, style, fields, finished elevations and generated body |
| Planting | `get_plants`, `update_plant`, `batch_update_plants` | Actual Plant PIO fields, species/style and count; inspect after reset |
| Classification and takeoff | `landscape_set_metadata`, `landscape_takeoff` | Explicit proposed scope, unique UUIDs, geometry basis, units and sourced prices |
| Building context | Wall/slab/roof tools and exact discovered SDK contracts | Source-grounded exterior footprint, levels, joins and roof relationships |
| Plans and schedules | Worksheet, sheet-layer, viewport, text and dimension tools | Current quantities, readable scale, visibility and export/save readbacks |

Use `list_commands(filter="...")` for handwritten commands and `sdk_list(name="...")`
for exact SDK contracts. Local discovery returns `host_presence_checked:false`;
it never proves that the installed host has the same code or native behavior.
The generic `vwx` wrapper reaches public handwritten commands not individually
registered as MCP tools. Do not guess native selectors or plugin field names.

## Terrain sampling

```text
get_site_model_info(site_model_id="<site-model-uuid>")
terrain_sample_points(site_model_id="<site-model-uuid>",
                      points=[{"x":100,"y":200},{"x":115,"y":210}],
                      tin_types=[0,1])
```

Coordinates and returned elevations use document units. TIN selectors are
`0` existing, `1` proposed and `2` current. A request allows 1–200 finite XY
points and 1–3 distinct selectors. Outside-model points return `ok:false` and
`z:null`. A native failure retains completed samples and identifies the failed
point/TIN; do not treat an incomplete result as a complete survey.

Supplying a UUID avoids ambiguous model lookup. Lookup otherwise uses the
active layer without an interactive picker and validates the returned object
as a Site Model. `update_site_model` requests a reset, then reports pending
regeneration. Sample known locations in a later job; success from ResetObject
is not proof that the TIN finished rebuilding. No cut/fill volume is inferred
from point samples alone.

## Copy and inspect native templates

```text
landscape_object_info(object_id="<approved-template-uuid>")
landscape_duplicate_template(source_id="<approved-template-uuid>",
                             target_layer="Hardscape", dx=12, dy=0,
                             fields={"<discovered-field-name>":"<value>"})
# Separate request after the copy job returns:
landscape_object_info(object_id="<new-uuid>")
```

The template must be an existing native Plant, Hardscape, Landscape Area or
Site Modifier. The destination must already be a design layer. The copy retains
the complete native object and its path; this tool does not replace an outline
or infer construction settings. Offsets use document units. Exact fields are
discovered and validated before mutation. Creation and field readback do not
certify initialization or regenerated geometry.

Inspection also accepts Existing Tree and Site Model objects. It returns actual
fields, style/path identity and available geometry/context diagnostics. Bounds
are projected screen bounds. Use task-specific independent measurements for
slopes, holes, terrain contact and finished elevations; do not interpret a
bounding box as a surface-area or grading check.

Plant updates reject unknown fields and ambiguous aliases before writing.
They verify data writes but do not reset the object. Discover `ResetObject`
with `sdk_list`, call it on the returned Plant UUID, then inspect geometry in
a separate job. Metadata and geometry completion are separate outcomes.
Batch updates preflight targets but have no rollback after writing begins.
An error can include the UUID and completed mutations; preserve that state and
inspect it before deciding a recovery action. Do not repeat a creation after an
uncertain response. `create_plant` inserts an existing symbol; it is not native
Plant creation. The legacy `get_plant_database` returns symbol-name candidates
from the drawing, not an external botanical database.

## Explicit proposed quantities

Classification describes project scope, not when the geometry was drawn.
A newly modeled existing driveway stays `existing`. Classification never
automatically marks a new object as proposed work.

```text
landscape_set_metadata(object_id="<paving-uuid>", metadata={
  "status":"new_proposed", "role":"item", "category":"paving",
  "material":"concrete", "measurement":"plan_area", "unit":"ft2",
  "classification_source":"Approved planting and paving plan, revision B",
  "description":"New patio"
})
# Separate measurement request:
landscape_takeoff(object_ids=["<paving-uuid>"])
```

This writes the ordinary text record `VWX_Landscape` and verifies each value.
It preserves unrelated records and uses each object's current native UUID.
Copying a record therefore does not copy its object's identity. Required
metadata fields are shown above except that description and classification
source are optional. Existing schema conflicts fail rather than redefining
another format's fields.

| Metadata | Accepted values or meaning |
|---|---|
| `status` | `existing`, `new_proposed`, `remove`, `unknown` |
| `role` | `item`, `assembly`, `assembly_part`, `reference`, `markup` |
| `category`, `material` | Explicit nonempty project labels; exact price-match keys |
| `measurement` | `plan_area`, `perimeter`, `linear_length`, `count`, `plant_count` |
| `unit` | `each`; length `mm/cm/m/in/ft/yd`; area with `2` suffix, `acre` or `ha` |
| `count_field` | Required only for `plant_count`; exact discovered native Plant field |
| `assembly_id` | Optional parent assembly UUID; excludes the linked member from totals |
| `classification_source`, `description` | Optional project evidence and human-readable description |

Takeoff accepts 1–500 explicit UUIDs and reads metadata and geometry afresh.
Only `new_proposed` items/assemblies are included. Existing, removed, unknown,
unclassified, reference, markup and component objects are excluded with reasons.
Every occurrence of a duplicated UUID is excluded, so aliases cannot double
count. Native containers and assembly ancestry are checked as well as metadata.
Inspect exclusions and partial status before using totals.

Plan area/perimeter support rectangle, oval, polygon, rounded rectangle and
polyline geometry. Hardscape and Landscape Area measurements use their actual
validated path, not projected bounds. Every measured object and intermediate
group must have a successful, finite SDK `GetEntityMatrix` result establishing
a horizontal plane; native surface PIOs require both their owner and path planes
to pass. Failed, unavailable, tilted or ambiguous transforms exclude the quantity
with a reason. This deliberately excludes native/container cases whose planar
transforms have not been established; a native fixture is still required to
verify each supported workflow. An area needs a closed polygon/polyline.
Linear length supports straight line/wall endpoints. Object `count` is one per
object; native `plant_count` reads a verified whole-number count field.
Document coordinate units are converted explicitly into the requested units.
Sloped finish area, component thickness/volume, earthwork cut/fill and irrigated
coverage are not inferred from plan geometry.

Prices are optional. To cost the example, add a real sourced rate:

```text
landscape_takeoff(object_ids=["<paving-uuid>"], prices=[{
  "category":"paving", "material":"concrete", "quantity_kind":"area",
  "unit":"ft2", "unit_price":<actual-quoted-rate>,
  "currency":"USD", "source":"<supplier quote and date>"
}])
```

The placeholder rate must be replaced with a JSON number. Rates match exact
category/material/dimension/unit keys. Missing rates remain unpriced; no market
prices or unit conversions are invented. Currencies are totaled separately.
The result contains UUID-linked line items, a grouped schedule, exclusions,
quantity totals and cost totals. It is a read-only snapshot, not a worksheet,
save operation or continuously updating database. Rerun after edits; use the
worksheet tools to publish an accepted current snapshot and record its basis.

## Evidence boundary

These additions have offline tests for validation, ownership races, partial
state, unit conversion, exclusion and pricing. Native lifecycle acceptance must
still be performed on an explicitly authorized disposable drawing with this
installation. Existing SDK evidence is preserved separately in
[coverage](TOOL_COVERAGE.md); it does not become a native pass for these composed
workflows. Installation/build/test results must be reported separately from
deployment and live verification.
