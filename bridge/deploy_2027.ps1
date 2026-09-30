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
$pairs = @()
foreach ($name in @('commands.py','vwx_pump.py','BridgeStart_MenuCommand.py','vs_index.json','vs_index_meta.json',
                   'sdk_catalog.json','sdk_generated.py','sdk_runtime.py','sdk_sequences.py',
                   'project_guard.py','landscape_takeoff.py')) {
    $pairs += ,@((Join-Path $repo "vwx-plugin\$name"), (Join-Path $pythonDir $name))
}
foreach ($name in @('VwxBridge.vlb','VwxBridge.vwr')) {
    $pairs += ,@((Join-Path $output $name), (Join-Path $plugins $name))
}
# Validate the complete input set before creating a backup, moving a queue or
# replacing an installed file. A partial checkout must leave the install intact.
foreach ($pair in $pairs) {
    if (!(Test-Path -LiteralPath $pair[0] -PathType Leaf)) { throw "Deployment source missing: $($pair[0])" }
}
function Assert-NoReparsePath([string]$Path) {
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Deployment path traverses a reparse point: $cursor"
            }
        }
        $parent = Split-Path -Parent $cursor
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
}
function Get-DeploymentHash([string]$Path) {
    # Use .NET directly: a PowerShell 7 parent can pass a PSModulePath that hides
    # Windows PowerShell's script-based Get-FileHash cmdlet in this child.
    $stream = [IO.File]::OpenRead($Path)
    try {
        $algorithm = [Security.Cryptography.SHA256]::Create()
        try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '') }
        finally { $algorithm.Dispose() }
    }
    finally { $stream.Dispose() }
}
$backupRoot = Join-Path (Split-Path $plugins -Parent) 'MCP-Backups'
foreach ($path in @($plugins, $pythonDir, $backupRoot, (Join-Path $pythonDir 'ipc'))) {
    Assert-NoReparsePath $path
}
foreach ($pair in $pairs) { Assert-NoReparsePath $pair[1] }
if (Test-Path -LiteralPath (Join-Path $pythonDir 'bridge.project.json')) {
    throw 'A project ownership lease exists. Complete or reconcile the owning workflow before deployment; the lease was not changed.'
}
$backup = Join-Path $backupRoot ((Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
if (Get-Process -Name 'Vectorworks2027' -ErrorAction SilentlyContinue) {
    throw 'Vectorworks started during deployment preflight. Close it before trying again.'
}
New-Item -ItemType Directory -Path $pythonDir, $backupRoot -Force | Out-Null
New-Item -ItemType Directory -Path $backup | Out-Null
if (Test-Path -LiteralPath (Join-Path $pythonDir 'ipc')) {
    # Move pending jobs out of the active queue; never replay work from an old session.
    $queuePath = (Resolve-Path -LiteralPath (Join-Path $pythonDir 'ipc')).Path
    # Resolve both sides through the same filesystem provider. APPDATA may use
    # an 8.3 alias (for example RUNNER~1), which GetFullPath does not expand.
    $expected = Join-Path (Resolve-Path -LiteralPath $pythonDir).Path 'ipc'
    if ($queuePath -ne $expected) { throw 'Unexpected queue path.' }
    Move-Item -LiteralPath $queuePath -Destination (Join-Path $backup 'ipc')
}
foreach ($pair in $pairs) {
    if (Test-Path -LiteralPath $pair[1]) {
        Copy-Item -LiteralPath $pair[1] -Destination (Join-Path $backup (Split-Path $pair[1] -Leaf))
    }
    Copy-Item -LiteralPath $pair[0] -Destination $pair[1] -Force
    if ((Get-DeploymentHash $pair[0]) -ne (Get-DeploymentHash $pair[1])) {
        throw "Deployment hash mismatch: $($pair[1])"
    }
}
New-Item -ItemType Directory -Path (Join-Path $pythonDir 'ipc\jobs'), (Join-Path $pythonDir 'ipc\results') -Force | Out-Null
Write-Output "Installed 2027 bridge. Backup: $backup"
Write-Output 'Set the VWX Bridge Start Python menu script to BridgeStart_MenuCommand.py and include that enabled command exactly once in the current workspace menu.'
Write-Output 'The native scheduler invokes that fixed menu name through the SDK; no keyboard shortcut is required.'
Write-Output 'Open the native bridge palette after restarting Vectorworks. Use file transport in your MCP client.'
