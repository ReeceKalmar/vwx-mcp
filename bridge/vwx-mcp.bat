@echo off
REM Vectorworks 2027 MCP server: HTTP :8082 to the native palette/file queue.
REM Start Vectorworks 2027 and open its native VWX Bridge palette first.
setlocal

set VWX_VW_VERSION=2027
set VWX_TRANSPORT=file
set VWX_CACHE_TTL=0
REM Background mode rejects known interactive calls and arbitrary scripts.
set VWX_BACKGROUND_MODE=1
set MCP_TRANSPORT=streamable-http
set FASTMCP_HOST=127.0.0.1
set FASTMCP_PORT=8082
REM Landscape is compact by default; preserve an explicit caller override.
REM Other presets: full | sdk | gis | modeling | baumkataster | minimal
if not defined VWX_TOOLSET set VWX_TOOLSET=landscape
REM VWX_SDK_TOOLS=1 opts into named SDK registration; 0 omits it for any preset.
REM If unset, the server registers named SDK tools only for full/sdk startup.
REM sdk_call/list/sequence remain available in every preset.

for %%I in ("%~dp0..") do set "VWX_REPO=%%~fI"
set "VWX_SERVER=%VWX_REPO%\mcp-server"
set "VWX_VENV=%VWX_REPO%\.venv"

REM --- one-time venv bootstrap (auto, idempotent) ---
if not exist "%VWX_VENV%\Scripts\python.exe" (
    echo [vwx-mcp] First run: creating Python 3.12 venv + installing fastmcp ...
    py -3.12 -m venv "%VWX_VENV%"
    if errorlevel 1 exit /b 1
)
REM Reconcile the pin on each launch so an existing venv does not stay stale.
"%VWX_VENV%\Scripts\python.exe" -m pip install -r "%VWX_SERVER%\requirements.txt"
if errorlevel 1 exit /b 1

"%VWX_VENV%\Scripts\python.exe" "%VWX_SERVER%\vwx_mcp_server.py"
pause
