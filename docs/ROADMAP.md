# Remaining Vectorworks 2027 work

Use [current status](VECTORWORKS_2027.md) and [measured coverage](TOOL_COVERAGE.md)
for implemented and verified behavior. An adapter, callable host name, offline
test and native semantic fixture are different results.

1. Add independent native fixtures for the 2,697 APIs without confirmed results.
   Prefer useful workflows and documented prerequisites over arbitrary inputs.
   Preserve compatibility and native evidence as separate categories.
2. Resolve worksheet classification/zero-cell/border assumptions, text-style
   propagation and NURBS distance units with isolated probes. Retain the
   [original findings](NATIVE_REPAIRS_2027.md) and stopped runs.
3. Verify native Hardscape, Landscape Area, wall, roof, site-model and other
   complex PIO workflows individually. Return to Vectorworks between creation,
   reset and dependent inspection; a successful setter is not regeneration.
4. Add context-specific adapters only with the required host lifecycle. There
   are 173 APIs without a supported workflow; native pointers, transient handles,
   tool events and modal dialogs are not ordinary JSON menu calls.
5. Extend compatibility verification beyond Windows app build 882075. Keep
   unknown-build behavior intact for repairs guarded to the measured build.
6. Establish guarded blank-document creation, initial save and owned-document
   closing before claiming an unattended multi-project lifecycle. Existing-file
   transitions are verified separately; controlled restart still requires one
   saved drawing. Unexpected-crash recovery is not yet a verified workflow.

The Windows SDK menu broker, controlled maintenance restarts, guarded existing-file
transitions and English palette are implemented. A macOS native bridge and per-agent document sessions are not
supported. Coordinate ownership of the shared active document.

Older upstream instructions remain available in
[upstream Git](https://github.com/vicquick/vwx-mcp) and this repository's history;
they do not establish current 2027 behavior.
