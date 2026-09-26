# Install only the 2027 build into the current user's Vectorworks plug-ins.
# Run with Vectorworks closed. Existing files are backed up before overwrite.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
if (Get-Process -Name 'Vectorworks2027' -ErrorAction SilentlyContinue) {
    throw 'Close Vectorworks 2027 before deploying the bridge.'
}
$repo = Split-Path -Parent $PSScriptRoot
$output = Join-Path $repo 'native\Output\2027\Release'
$plugins = Join-Path $env:APPDATA 'Nemetschek\Vectorworks\2027\Plug-ins'
$pythonDir = Join-Path $plugins 'VWX-MCP'
$metadata = Get-Content -LiteralPath (Join-Path $repo 'vwx-plugin\vs_index_meta.json') -Raw | ConvertFrom-Json
if ($metadata.sdk_version -ne 3200) { throw 'SDK provenance must be 3200.' }
foreach ($file in @('VwxBridge.vlb', 'VwxBridge.vwr')) {
    if (!(Test-Path -LiteralPath (Join-Path $output $file))) { throw "Build output missing: $file" }
}
$backup = Join-Path (Split-Path $plugins -Parent) ('MCP-Backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $backup, $pythonDir -Force | Out-Null
if (Test-Path -LiteralPath (Join-Path $pythonDir 'ipc')) {
    # Move pending jobs out of the active queue; never replay work from an old session.
    $queuePath = (Resolve-Path -LiteralPath (Join-Path $pythonDir 'ipc')).Path
    $expected = [IO.Path]::GetFullPath((Join-Path $plugins 'VWX-MCP\ipc'))
    if ($queuePath -ne $expected) { throw 'Unexpected queue path.' }
    Move-Item -LiteralPath $queuePath -Destination (Join-Path $backup 'ipc')
}
$pairs = @()
foreach ($name in @('commands.py','vwx_pump.py','BridgeStart_MenuCommand.py','vs_index.json','vs_index_meta.json')) {
    $pairs += ,@((Join-Path $repo "vwx-plugin\$name"), (Join-Path $pythonDir $name))
}
foreach ($name in @('VwxBridge.vlb','VwxBridge.vwr')) {
    $pairs += ,@((Join-Path $output $name), (Join-Path $plugins $name))
}
foreach ($pair in $pairs) {
    if (Test-Path -LiteralPath $pair[1]) {
        Copy-Item -LiteralPath $pair[1] -Destination (Join-Path $backup (Split-Path $pair[1] -Leaf))
    }
    Copy-Item -LiteralPath $pair[0] -Destination $pair[1] -Force
    if ((Get-FileHash -LiteralPath $pair[0]).Hash -ne (Get-FileHash -LiteralPath $pair[1]).Hash) {
        throw "Deployment hash mismatch: $($pair[1])"
    }
}
New-Item -ItemType Directory -Path (Join-Path $pythonDir 'ipc\jobs'), (Join-Path $pythonDir 'ipc\results') -Force | Out-Null
Write-Output "Installed 2027 bridge. Backup: $backup"
Write-Output 'Set the VWX Bridge Start Python menu script to BridgeStart_MenuCommand.py and assign Ctrl+Shift+B.'
Write-Output 'Open the native bridge palette after restarting Vectorworks. Use file transport in your MCP client.'
