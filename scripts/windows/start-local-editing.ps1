<#
.SYNOPSIS
Starts the local VectCutAPI sidecar required to create editable Jianying drafts.
#>
[CmdletBinding()]
param(
    [string]$InstallRoot,
    [string]$VectCutUrl = "http://127.0.0.1:9001",
    [switch]$Mcp
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

if (-not (Test-CutWorkbenchLoopbackUrl -Url $VectCutUrl)) {
    throw "VectCutUrl must be a localhost/loopback HTTP(S) URL: $VectCutUrl"
}

$sourceRoot = Get-CutWorkbenchRepositoryRoot -ScriptsDirectory $PSScriptRoot
$installRoot = Get-CutWorkbenchInstallRoot -InstallRoot $InstallRoot
$runtimeRoot = Join-Path $installRoot "runtime"
$runtimeConfigPath = Join-Path $runtimeRoot "runtime-config.json"
$vectCutRoot = Join-Path $installRoot "tools\VectCutAPI"
$vectCutPython = Join-Path $vectCutRoot ".venv\Scripts\python.exe"
$workbenchPython = Join-Path $installRoot "workbench-venv\Scripts\python.exe"
$serviceRoot = Join-Path $installRoot "service"
$serviceStatePath = Join-Path $serviceRoot "vectcut-service.json"
$stdoutPath = Join-Path $serviceRoot "vectcut.stdout.log"
$stderrPath = Join-Path $serviceRoot "vectcut.stderr.log"

if (-not (Test-Path -LiteralPath $runtimeConfigPath -PathType Leaf)) {
    throw "Missing runtime config. Run install-local-editing.ps1 first: $runtimeConfigPath"
}
if (-not (Test-Path -LiteralPath $vectCutPython -PathType Leaf) -or -not (Test-Path -LiteralPath (Join-Path $vectCutRoot "capcut_server.py") -PathType Leaf)) {
    throw "Missing local VectCutAPI installation. Run install-local-editing.ps1 first."
}
if (-not (Test-Path -LiteralPath $workbenchPython -PathType Leaf)) {
    throw "Missing Cut Workbench environment. Run install-local-editing.ps1 first."
}

if (Test-CutWorkbenchVectCutHealth -BaseUrl $VectCutUrl) {
    Write-Host "Local VectCutAPI is already healthy at $VectCutUrl"
} else {
    $port = ([Uri]$VectCutUrl).Port
    New-Item -ItemType Directory -Force -Path $serviceRoot | Out-Null
    $serveScript = Join-Path $sourceRoot "scripts\serve_vectcut.py"
    $arguments = "`"$serveScript`" --repo `"$vectCutRoot`" --port $port"
    $process = Start-Process -FilePath $vectCutPython `
        -ArgumentList $arguments `
        -WorkingDirectory $vectCutRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru
    Write-CutWorkbenchJsonFile -Path $serviceStatePath -Value ([ordered]@{
        pid = $process.Id
        started_at_utc = $process.StartTime.ToUniversalTime().ToString("o")
        executable = $vectCutPython
        vectcut_url = $VectCutUrl
    })
    if (-not (Wait-CutWorkbenchVectCutHealth -BaseUrl $VectCutUrl -TimeoutSeconds 30)) {
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
        }
        $errorTail = if (Test-Path -LiteralPath $stderrPath) { (Get-Content -LiteralPath $stderrPath -Tail 30 -ErrorAction SilentlyContinue) -join [Environment]::NewLine } else { "No stderr log was written." }
        throw "Local VectCutAPI did not become healthy. Log tail:`n$errorTail"
    }
    Write-Host "Started local VectCutAPI at $VectCutUrl (PID $($process.Id))."
}

if ($Mcp) {
    Write-Host "Starting Cut Workbench MCP in the foreground. Stop it with Ctrl+C."
    & $workbenchPython -m cut_workbench.cli --root $runtimeRoot --config $runtimeConfigPath mcp
    exit $LASTEXITCODE
}

Write-Host "Local editing service is ready. Configure your Agent with the generated agent-mcp-config.json, then run doctor-local-editing.ps1."
