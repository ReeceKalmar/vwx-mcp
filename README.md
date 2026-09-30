# Vectorworks 2027 MCP bridge

Use Vectorworks for landscape architecture through typed MCP tools for site
geometry, planting, building context, drawing data, quantities and sheets.
This Windows fork of
[vicquick/vwx-mcp](https://github.com/vicquick/vwx-mcp) targets **Vectorworks 2027,
SDK 3200**, with generated Python bindings from SDK build **882699**.

The bridge runs commands through Vectorworks' Python menu-command runner, one
queued job per invocation. Ordinary typed design work can run behind another
application without moving the mouse or taking keyboard focus. Leave
Vectorworks open and **unminimized**, with its bridge palette open and unpaused.
Known interactive operations and arbitrary scripts are blocked by default.

## Start here

- **Install or build:** [complete setup and build instructions](docs/BUILD_SETUP.md).
- **Develop with an AI agent:** [AGENTS.md](AGENTS.md), then the relevant subsystem guide.
- **Model a landscape project:** [design workflow](docs/DESIGN_WORKFLOW.md).
- **Use landscape tools:** [terrain, templates, planting and takeoff recipes](docs/LANDSCAPE_TOOLS.md).
- **Coordinate agents:** [project ownership and handoffs](docs/MULTI_AGENT_WORKFLOW.md).
- **Find a topic:** [documentation index](docs/INDEX.md).
- **Understand execution:** [architecture](docs/ARCHITECTURE.md) and
  [background operation](docs/BACKGROUND_WORK.md).
- **Assess support:** [current 2027 context](docs/VECTORWORKS_2027.md),
  [coverage](docs/TOOL_COVERAGE.md) and [remaining work](docs/ROADMAP.md).

## Quick setup

You need Windows, Vectorworks 2027, Python 3.12, the official 2027 Windows SDK,
and the matching MSVC v143 14.42 C++ build tools. The full guide covers the
Windows SDK, compiler discovery, deployment and first-run security prompt.

```powershell
git clone https://github.com/ReeceKalmar/vwx-mcp.git
Set-Location vwx-mcp
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r mcp-server/requirements.txt
& .\.venv\Scripts\python.exe tools/build_2027.py --sdk 'C:\SDKs\SDKVW(882699)'
```

Close Vectorworks, then run `bridge/deploy_2027.ps1`. In Vectorworks, create the
Python menu command **VWX Bridge Start** from
`vwx-plugin/BridgeStart_MenuCommand.py`, add it exactly once to the active
workspace, and add **Show VWX Bridge Palette**. Open that palette. These menu
steps are required; compiling and copying the files alone is insufficient.

Configure your MCP client to run `.venv\Scripts\python.exe` with the absolute
path to `mcp-server/vwx_mcp_server.py`, using stdio. The
[setup guide](docs/BUILD_SETUP.md#mcp-client-configuration) provides a complete
JSON example. `bridge/vwx-mcp.bat` is the optional localhost HTTP launcher.

Start with a disposable drawing and call `ping`, `get_document_info`, and
`vs_index_stats`. Verify a created object in a separate request before using
the bridge on project drawings. Run
`python tools/check_landscape_installation.py` with your configured Python to
check deployed companions; use `--source-only` for an offline checkout check.

## API access

The default `landscape` profile exposes the relevant handwritten workflows and
omits individual generated SDK registrations. Prefer a handwritten tool when it
covers the intended operation. The full inventory still contains **294
handwritten tools** and **3,098 generated SDK tools**; complete API coverage is
not the landscape development target. For SDK calls, inspect the contract first:

```python
sdk_list(name="Abs")
sdk_call(name="Abs", arguments={"v": -3})
```

`sdk_call`, `sdk_list`, and `sdk_sequence` remain available in the compact
profile. Set `VWX_TOOLSET=full` to opt into the full inventory;
`VWX_SDK_TOOLS=0` explicitly omits named SDK registrations even with that profile.
Object handles travel as UUIDs.
See [SDK adapter contracts](docs/SDK_ADAPTERS_2027.md) for JSON types, callbacks,
construction scopes and disclosed compatibility replacements.

The default exposes **257 tools**, including bulk existing/proposed terrain
sampling, native template inspection/duplication, validated Plant edits and
classified proposed-work takeoffs with optional sourced prices. A native copy
or field write still needs separate geometry verification.

Multiple agents can prepare and review the same project in parallel. Reserve
native ownership with `project_session` and use `project_execute` for every
owner read/write. Each job checks the exact saved drawing before dispatch;
other clients are blocked until release. The application still has one active
drawing, and sequences have no rollback or regeneration break. An uncertain
result must not trigger automatic mutation replay.

## Verification and limitations

The landscape update ran **948 offline tests: 947 passed and one Windows
symlink test skipped**, including the compiled native harnesses. Contract,
generated-report and repository checks passed. These new workflows have not
yet been deployed or verified in a live drawing. The recorded earlier native
baseline passed all **57 default
live fixture families / 2,303 unique jobs** across resumed batches. The
[default-suite audit](docs/LIVE_DEFAULT_SUITE_2027.json) retains interruptions
and repeated attempts. Cleanup validation is recorded in
[publication notes](docs/PUBLICATION_2027.md).

Confirmed native results cover **401 of 3,098 API names**, with passing native
cases for 399. **2,697 lack confirmed native results**. Generated bindings,
adapter tests and compatibility replacements do not establish original native
semantics. Known diagnostic failures, unsupported contexts and uncertain
attempts remain documented in [coverage](docs/TOOL_COVERAGE.md) and
[native investigations](docs/NATIVE_REPAIRS_2027.md).

Run the offline suite without connecting to Vectorworks:

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe tools/sdk_test_matrix.py --check
& .\.venv\Scripts\python.exe tools/api_coverage.py --check
```

See [testing](docs/TESTING_2027.md) before executing any live fixture. Native
testing needs an explicitly selected disposable drawing. The
[maintenance controller](docs/MAINTENANCE_2027.md) supports guarded
save/quit/deploy/reopen cycles once the native helper is installed.

## License and attribution

[MIT](LICENSE). Original project: [vicquick/vwx-mcp](https://github.com/vicquick/vwx-mcp).
This fork retains upstream attribution. Vectorworks and its SDK are separate
products; SDK archives, credentials, drawings and compiled plug-ins are not
distributed in this source repository. The supported native host is Windows;
Linux CI runs offline Python checks, and no macOS native runner is implemented.
