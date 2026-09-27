# Vectorworks 2027 MCP bridge

Control Vectorworks through typed MCP tools for geometry, drawing data,
resources, worksheets and SDK operations. This Windows fork of
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
the bridge on project drawings.

## API access

The default inventory contains **287 handwritten tools** and **3,098 generated
SDK tools**. Prefer a handwritten tool when it covers the intended operation.
For SDK calls, inspect the contract first:

```python
sdk_list(name="Abs")
sdk_call(name="Abs", arguments={"v": -3})
```

Set `VWX_SDK_TOOLS=0` to omit the 3,098 individual registrations while retaining
`sdk_call`, `sdk_list`, and `sdk_sequence`. Object handles travel as UUIDs.
See [SDK adapter contracts](docs/SDK_ADAPTERS_2027.md) for JSON types, callbacks,
construction scopes and disclosed compatibility replacements.

Multiple clients share one active Vectorworks drawing. They do **not** get
isolated document sessions; coordinate document ownership and serialize work
on different files. A sequence has no rollback or regeneration break between
its calls. An uncertain result must not trigger automatic mutation replay.

## Verification and limitations

The publication check ran **818 offline tests** successfully, with one Windows
symlink test skipped. The recorded native baseline passed all **57 default
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
