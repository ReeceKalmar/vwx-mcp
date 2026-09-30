# Landscape architecture priorities

Use [current status](VECTORWORKS_2027.md) and [measured coverage](TOOL_COVERAGE.md)
for implemented and verified behavior. An adapter, callable host name, offline
test and native semantic fixture are different results.

The target is the [landscape design workflow](DESIGN_WORKFLOW.md), including
existing-site reconstruction, implementation of user design intent, new-work
quantities and native sheets. Exhaustive SDK implementation or live coverage is
not a release requirement. Retain generated adapters and evidence without making
the 2,697 unconfirmed API names the default work queue.

1. **Reliable terrain and finished surfaces.** Verify native Site Model,
   Hardscape, Landscape Area and Site Modifier creation/edit/inspection on
   disposable drawings. Cover initialization, profile holes, slope reference
   origins, finished elevations, grade overlaps and regenerated geometry.
   Correct terrain queries and units before building higher-level grading tools.
2. **Reusable native building context.** Package proven slab, exterior wall,
   Roof/Roof Face, retaining-wall and deck workflows. Verify joins, wall peaks,
   footprint preservation and terrain relationships. Include doors/windows only
   when source evidence and the requested context require them. Avoid repeated
   mesh-to-native reconstruction and per-project PIO field discovery.
3. **Real planting workflows.** Make native Plant/Existing Tree insertion,
   resource/style discovery, species data, spacing and count readback reliable.
   Keep existing symbol insertion clearly identified until true Plant PIO
   creation has its own verified workflow.
4. **Proposed quantities and sheets.** Explicit classification, UUID-linked
   measured takeoffs, assembly/reference exclusions and sourced-rate costing
   are implemented with offline tests. Verify them natively, extend supported
   slope/component measurements, and publish verified worksheet snapshots.
   Add native title-block/sheet
   recipes with independent viewport/export checks and verified saves. Resolve
   worksheet and text discrepancies when they block these deliverables.
5. **Reduce agent overhead.** The compact landscape profile, native template
   duplication/inspection, bulk terrain sampling and cooperative project leases
   are implemented. Next consolidate proven multi-step workflows with typed inputs and useful
   diagnostics. Discover existing handwritten tools before adding wrappers.
   Preserve separate jobs for dependent readbacks and disclose incomplete work.

For each recipe, test meaningful source geometry, create, independently inspect
after regeneration, edit, inspect again, measure relevant quantities and verify
save/persistence within the authorized test scope. Include no-effect setters and
preservation of nearby objects. A passing setter or broad API count is not the
acceptance criterion. Client project incidents can guide fixtures but are not
silently imported as test passes.

Maintain transport/no-replay safety and existing regression coverage throughout.
Unsupported contexts and broader build compatibility remain demand-driven work:
there are 173 APIs without a supported workflow, and native pointers, transient
handles, tool events and modal dialogs are not ordinary JSON menu calls. Keep
unknown-build behavior intact for repairs measured on Windows app build 882075.
Retain [original native findings](NATIVE_REPAIRS_2027.md) and stopped runs.

The Windows SDK menu broker, controlled maintenance restarts and English palette
are implemented. A macOS native bridge and per-agent document sessions are not
supported. Use [project ownership](MULTI_AGENT_WORKFLOW.md) to serialize native
work while other agents prepare and review the same project in parallel.

Older upstream instructions remain available in
[upstream Git](https://github.com/vicquick/vwx-mcp) and this repository's history;
they do not establish current 2027 behavior.
