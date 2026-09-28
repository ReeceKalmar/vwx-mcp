# Remaining Vectorworks 2027 work

Use [current status](VECTORWORKS_2027.md) and [measured coverage](TOOL_COVERAGE.md)
for implemented and verified behavior. An adapter, callable host name, offline
test and native semantic fixture are different results.

Prioritize complete useful workflows and predictable recovery. Verification of
all remaining API names is not a prerequisite for a scoped design workflow.
Use the [design operating guide](DESIGN_WORKFLOW.md) for work that can continue
under the present implementation; the items below are still development or
verification work.

1. Verify a representative native house and landscape workflow through objects,
   edits, independent geometry checks, sheet layers/viewports, published outputs
   and save/reopen persistence. Build on the measured
   [Wall, Roof Face and Slab cases](NATIVE_ARCHITECTURE_2027.md). Native Hardscape,
   Landscape Area, Plant and site-model workflows, complex/styled assemblies
   and persistence still need their own evidence. Keep requested native object
   types; meshes or generic solids do not complete that requirement.
2. Prove bounded pause/resume handling for unavailable environments, rejected
   requests and known undispatched work. Preserve uncertain-operation holds,
   ownership and no-replay rules. Reuse documented recovery steps rather than
   requiring a new private incident framework for each routine design action.
   Document policy alone does not implement automatic recovery.
3. Establish guarded blank-document creation, initial save and owned-document
   closing before claiming an unattended multi-project lifecycle. Existing-file
   transitions are verified separately; controlled restart still requires one
   saved drawing. Unexpected-crash recovery is not yet a verified workflow.
4. Resolve worksheet classification/zero-cell/border assumptions, text-style
   propagation and NURBS distance units with isolated probes. Retain the
   [original findings](NATIVE_REPAIRS_2027.md) and stopped runs.
5. Add context-specific adapters only with the required host lifecycle. There
   are 173 APIs without a supported workflow; native pointers, transient handles,
   tool events and modal dialogs are not ordinary JSON menu calls.
6. Extend compatibility verification beyond Windows app build 882075. Keep
   unknown-build behavior intact for repairs guarded to the measured build.
7. Add independent native fixtures for the 2,697 APIs without confirmed results,
   prioritizing calls used by these workflows. Use documented prerequisites and
   meaningful inputs; preserve compatibility and native evidence separately.

Return to Vectorworks between creation/reset and dependent inspection. A
successful setter is not proof of regeneration or the requested geometry.

The Windows SDK menu broker, controlled maintenance restarts, guarded existing-file
transitions and English palette are implemented. A macOS native bridge and per-agent document sessions are not
supported. Coordinate ownership of the shared active document.

Older upstream instructions remain available in
[upstream Git](https://github.com/vicquick/vwx-mcp) and this repository's history;
they do not establish current 2027 behavior.
