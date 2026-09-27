# Build and set up Vectorworks 2027 MCP

This guide installs the Windows bridge from source. The repository includes
generated SDK bindings and offline tests; it does not include the vendor SDK,
Vectorworks, credentials, compiled plug-ins or test drawings.

## Prerequisites

| Component | Requirement |
|---|---|
| Native host | Windows x64 with Vectorworks 2027 installed |
| Server/test Python | Python 3.12, tested independently of Vectorworks' embedded Python |
| Native SDK | Official Vectorworks 2027 Windows SDK, `SDK_VERSION=3200`; the checked-in bindings use build 882699 |
| C++ compiler | MSVC v143 **14.42.34433**, the Visual Studio 2022 **17.12** toolset |
| Build support | MSBuild, `v170` C++ targets and a Windows 10/11 SDK |
| Client | An MCP client supporting local stdio, or streamable HTTP on localhost |

The compiler requirement follows the
[official 2027 development requirements](https://github.com/Vectorworks/developer-sdk/blob/main/Versions/Vectorworks%202027%20Development.md).
The build script finds the pinned C++ tools through `vswhere`; they may be
installed alongside a newer Visual Studio IDE. Installing only the newest
compiler is insufficient. Select the v143 14.42 components in Visual Studio
Installer, including the x64/x86 tools and a Windows SDK.

Obtain the [official Windows SDK archive](https://release.vectorworks.net/latest/Vectorworks/2027-NNA-eng-win-SDK.zip)
and extract it outside the repository. The `latest` URL may change. Check the
download against [vs_index_meta.json](../vwx-plugin/vs_index_meta.json) when
reproducing the recorded build; do not silently regenerate the catalog from a
different SDK build. Point `VWSDK2027` at the folder **containing `SDKLib`**, such
as `C:\SDKs\SDKVW(882699)`, not at the archive's outermost folder.

For offline Python development, Vectorworks and the vendor SDK are unnecessary.
Linux CI covers offline Python behavior; it is not a supported native host.
Compiled Windows harnesses skip if the required compiler is unavailable, so
inspect the test summary before claiming that those harnesses ran.

## Clone and prepare Python

Run these commands in PowerShell:

```powershell
git clone https://github.com/ReeceKalmar/vwx-mcp.git
Set-Location vwx-mcp
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r mcp-server/requirements.txt
```

Commands below use the environment's executable directly; activation and
PowerShell activation-policy changes are unnecessary. The server uses standalone
FastMCP **4.0.3**. Do not substitute the `mcp.server.fastmcp` package.

## Build the native plug-in

```powershell
$env:VWSDK2027 = 'C:\SDKs\SDKVW(882699)'
& .\.venv\Scripts\python.exe tools/build_2027.py
```

Alternatively pass `--sdk 'C:\SDKs\SDKVW(882699)'`. The script validates SDK
3200, the import library, property sheet and resource-packaging tools, then
builds `native/VwxBridge2027.vcxproj` for Release/x64. It normalizes the child
environment for Windows/MSBuild and does not deploy anything.

Successful output files are:

```text
native/Output/2027/Release/VwxBridge.vlb
native/Output/2027/Release/VwxBridge.vwr
```

The `.vwr` file is the packaged English palette and string resources; install it
alongside the `.vlb`. A build against another SDK year is refused. The project
keeps native `wchar_t` and C++20 for the SDK headers. Build output is ignored by
Git. Rebuilding can change binary/package hashes; old native test evidence still
belongs to its recorded artifacts, not automatically to the new outputs.

## First installation

Save work and **fully close Vectorworks 2027**. From the repository root run:

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File bridge/deploy_2027.ps1
```

`bridge/deploy_native_bridge.bat` forwards to that command. `RemoteSigned`
applies only to the child process; organizational policy still takes precedence.
If a downloaded script is blocked, review its contents and your organization’s
policy instead of disabling machine-wide protections.

Deployment checks all eleven source files and the target paths before changing
the installation. It backs up existing files, quarantines old IPC work to avoid
replay, copies the files and verifies their SHA-256 values. Destinations are:

```text
%APPDATA%\Nemetschek\Vectorworks\2027\Plug-ins\VwxBridge.vlb
%APPDATA%\Nemetschek\Vectorworks\2027\Plug-ins\VwxBridge.vwr
%APPDATA%\Nemetschek\Vectorworks\2027\Plug-ins\VWX-MCP\<nine Python/data files>
```

Backups are under the user version folder's `MCP-Backups`. This installer uses
the user plug-in folder, not Program Files. It refuses a running host and
unexpected reparse paths. If deployment fails, inspect the error and backup;
do not restart into a partially installed version or restore old pending jobs.

Launch Vectorworks and complete its normal startup. A locally built plug-in may
need your approval in **Unknown Developer Plug-ins**. The credential example
is not an issued credential; see [developer credentials](PLUGIN_CREDENTIALS.md).

### Configure the workspace once

1. In **Tools → Plug-ins → Plug-in Manager**, create a custom **Python menu
   command** named exactly **VWX Bridge Start**.
2. Set its script to the complete contents of
   [BridgeStart_MenuCommand.py](../vwx-plugin/BridgeStart_MenuCommand.py).
3. Use the Workspace Editor to add **VWX Bridge Start** exactly once to an
   enabled menu in the workspace you will use. A shortcut is optional; the
   scheduler invokes the name through the SDK.
4. Add **Show VWX Bridge Palette** to that workspace, then invoke it to open
   the native palette. The separate **VWX Bridge Status (native)** command is
   a status probe, not the Python runner.
5. Leave Vectorworks unminimized and the palette open and unpaused. Its status
   should become **Active**. Closing or pausing it stops new jobs.

Repeat the menu setup for another workspace. Update the custom command's script
when `BridgeStart_MenuCommand.py` changes; copying its source file alone does
not edit the saved Vectorworks custom menu command.

## MCP client configuration

Prefer stdio for a local client. This is a generic MCP configuration example;
replace the absolute paths and put it in your client's MCP server settings:

```json
{
  "mcpServers": {
    "vectorworks-2027": {
      "command": "C:\\src\\vwx-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\src\\vwx-mcp\\mcp-server\\vwx_mcp_server.py"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "VWX_TRANSPORT": "file",
        "VWX_VW_VERSION": "2027",
        "VWX_BACKGROUND_MODE": "1",
        "VWX_CACHE_TTL": "0",
        "VWX_SDK_TOOLS": "1"
      }
    }
  }
}
```

The server discovers the complete installation in the default user plug-in
folder. For a custom installation, set `VWX_PLUGIN_DIR` to its absolute Python
folder in **both** the MCP server and the Vectorworks process environment before
launching them. A bad explicit path fails rather than silently selecting another
installation. The native binary/resources remain in a host plug-in search path.

Set `VWX_SDK_TOOLS=0` for a compact tool list. `sdk_call`, `sdk_list` and
`sdk_sequence` remain available. The `VWX_TOOLSET` presets are `full`, `sdk`,
`gis`, `modeling`, `baumkataster`, and `minimal`.

For HTTP clients, `bridge/vwx-mcp.bat` bootstraps the repository `.venv`, installs
the pinned requirements and serves `http://127.0.0.1:8082/mcp`. Keep the terminal
running, and configure the client for streamable HTTP. This HTTP connection is
between client and server; the server still uses the local Vectorworks file
queue. No legacy TCP bridge or external watchdog is required.

## Verify the installation

Use a blank, saved disposable drawing. Through MCP:

1. Call `ping` and `get_document_info`; confirm the intended document.
2. Call `vs_index_stats`; expect year 2027, SDK 3200 and 3,098 indexed functions.
3. Inspect `sdk_list(name="Abs")`, then call
   `sdk_call(name="Abs", arguments={"v": -3})`; expect result `3`.
4. Create a small rectangle with a handwritten tool. Inspect its returned UUID
   and dimensions in a **later request**, allowing the menu runner to return.

Use [background diagnostics](BACKGROUND_WORK.md) if the heartbeat is absent or
a job is not picked up. Do not manufacture completion stamps or blindly retry
a mutation with an uncertain outcome. The [testing guide](TESTING_2027.md)
explains the guarded live suite; do not execute it on a real project drawing.

## Development checks and SDK regeneration

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe tools/pruefe_konsistenz.py .
& .\.venv\Scripts\python.exe tools/sdk_test_matrix.py --check
& .\.venv\Scripts\python.exe tools/api_coverage.py --check
& .\.venv\Scripts\python.exe tools/check_repository.py
& .\.venv\Scripts\python.exe tools/build_sdk_wrappers.py "$env:VWSDK2027\SDKLib\Include\vs.py" --check
```

To check the original SDK index without changing the repository, generate a
temporary copy and compare its hash:

```powershell
New-Item -ItemType Directory -Path .audit -Force | Out-Null
& .\.venv\Scripts\python.exe tools/build_vs_index.py "$env:VWSDK2027\SDKLib\Include\vs.py" .audit/vs_index.check.json
if ((Get-FileHash .audit/vs_index.check.json).Hash -ne (Get-FileHash vwx-plugin/vs_index.json).Hash) {
    throw 'SDK index differs; review the SDK build and generator before updating.'
}
```

`build_vs_index.py` has no `--check` option. `build_sdk_wrappers.py --check`
validates both generated catalog and wrappers against pinned provenance.
An intentional SDK update requires reviewed archive/stub/index metadata and
generator changes; removing hash/version guards is not a migration procedure.
After relevant implementation/evidence changes, regenerate current reports with
`tools/sdk_test_matrix.py` and `tools/api_coverage.py`, then rerun their checks.
See [tooling context](../tools/AGENTS.md) for file ownership and evidence rules.

## Updating an existing installation

Build and test first. For a host with the native maintenance helper already
installed, use the [controlled maintenance workflow](MAINTENANCE_2027.md) with
the one exact saved drawing. It saves, requests normal quit, waits for actual
exit, backs up/deploys, reopens and verifies the installation. It cannot handle
the very first installation and will stop rather than force-close uncertain
work or dismiss startup/security dialogs.

## Common setup failures

| Symptom | Check |
|---|---|
| Compiler not found | Install the pinned 14.42.34433 tools and v170 targets; a newer IDE alone is insufficient |
| SDK/resource tool missing | `VWSDK2027` must contain the complete `SDKLib` tree, including `ToolsWin/BuildVWR` |
| Palette menu absent | Confirm both native files are in the 2027 user plug-in folder, startup approval and active workspace |
| Active palette but unclaimed jobs | Check the exact Python menu name, enabled workspace entry, menu script and current scheduler diagnostics |
| Wrong/no Python installation | Check `VWX_PLUGIN_DIR` in both processes and the required installed files |
| Too many advertised tools | Set `VWX_SDK_TOOLS=0`, then restart the MCP server |
| Background interaction error | The requested operation requires attended mode; do not bypass the policy for unattended work |
| Vision startup warning | Read the installation-specific [Vision investigation](VISION_STARTUP_2027.md); copying application files into Vision is not a setup step |
