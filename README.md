# Vectorworks 2027 MCP bridge

Fork of [vicquick/vwx-mcp](https://github.com/vicquick/vwx-mcp), targeting
**Vectorworks 2027 on Windows, SDK 3200**. The Python API index contains
**3,098 functions**, regenerated from the official SDK build 882699.
Upstream's MIT license and attribution are preserved.

The native palette schedules a Python menu command. All reads and writes run
through that command, **one queued job per invocation**, returning to Vectorworks
between jobs so deferred object resets can complete. Python never runs from the
palette's web callbacks, timer, or notification handler. Error dialogs remain
visible. Invalid API calls or third-party objects can still crash the host;
compilation and offline tests are not proof that every modeling operation works.

## Build

1. Obtain the [official Vectorworks 2027 Windows SDK](https://release.vectorworks.net/latest/Vectorworks/2027-NNA-eng-win-SDK.zip).
2. Install the MSVC v143 **14.42 / Visual Studio 2022 17.12** x64 C++ build tools
   and a Windows SDK. These tools can also be installed alongside Visual Studio
   2026. See the [official 2027 development requirements](https://github.com/Vectorworks/developer-sdk/blob/main/Versions/Vectorworks%202027%20Development.md).
3. Set `VWSDK2027` to the extracted folder **containing `SDKLib`**, then run:

```powershell
python tools/build_2027.py --sdk 'C:\path\to\SDKVW(882699)'
python -m unittest discover -s tests -v
```

The build refuses an SDK other than 3200. Outputs are
`native/Output/2027/Release/VwxBridge.vlb` and `VwxBridge.vwr`.
The SDK itself and generated binaries are not committed to this repository.
The old 2026 project file is retained only as upstream history; use the 2027 target.

## Install

Close Vectorworks 2027, then run `bridge/deploy_2027.ps1`. It copies the native
build and Python files to the **2027 user Plug-ins folder**, verifies hashes,
backs up overwritten files, and archives any old pending jobs to avoid replay.

In Vectorworks, use **Tools → Plug-ins → Plug-in Manager** to create or update a
Python menu command named **VWX Bridge Start**. Its script is the contents of
`vwx-plugin/BridgeStart_MenuCommand.py`. Add it to the workspace with the shortcut
**Ctrl+Shift+B**. Also add the native **VWX Bridge Palette anzeigen** command.
Restart Vectorworks and open the palette. Palette open = bridge enabled;
Pause or closing the palette stops it.

This local native build has no Vectorworks-issued developer credentials.
If Vectorworks blocks it as an unknown developer, the user must review that
prompt. Do not disable plug-in security checks. A credential file for another
developer or Vectorworks year must not be reused for this fork.

Install the server dependencies into a Python environment:

```powershell
python -m pip install -r mcp-server/requirements.txt
```

Point your MCP client at that Python executable, with the absolute path to
`mcp-server/vwx_mcp_server.py` as its argument. Use these environment variables:

```text
MCP_TRANSPORT=stdio
VWX_TRANSPORT=file
VWX_VW_VERSION=2027
VWX_CACHE_TTL=0
VWX_PLUGIN_DIR=<your AppData Roaming>\Nemetschek\Vectorworks\2027\Plug-ins\VWX-MCP
```

The legacy TCP dialog bridge is retained for reference but is **not the supported
2027 route**. Updating SDK files does not repair its modal execution context.
Do not start the old TCP launcher together with the native palette.

## Verify before using project files

Start with a blank disposable document. Check `ping`, `get_document_info`, and
`vs_index_stats` (SDK 3200, year 2027, 3,098 functions). Create a simple rectangle,
then inspect it in a **separate request**. Next test native objects individually,
allowing the menu command to return between creation/reset and inspection.
Do not combine creation and regeneration-dependent reads in `vwx_batch` or one
long `execute_script`. A batch remains a single job.

Claimed jobs are never replayed after a crash. A timeout is not evidence that
the operation did nothing: inspect the document before resubmitting a mutation.
Bridge logs record command start before execution to aid crash diagnosis.

## Tools and reference

The existing tools cover layers, classes, 2D/3D geometry, BIM, site modeling,
plants, resources, worksheets, viewports and export. `vwx` dispatches named
commands; `execute_script` runs Python using Vectorworks' `vs` module.
Use `vs_signature` before authoring API calls. The index is a reference, not an
automatic validator for arbitrary scripts.

- [2027 migration and verification notes](docs/VECTORWORKS_2027.md)
- [Agent API guidance](AGENTS.md) — historical 2026 findings are identified as such
- [Upstream architecture history](docs/ARCHITECTURE.md)
- [Upstream tool coverage](docs/TOOL_COVERAGE.md)

## License

MIT; see [LICENSE](LICENSE). Vectorworks SDK licensing is separate.
