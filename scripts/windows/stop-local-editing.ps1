<#
.SYNOPSIS
Stops only the VectCutAPI process previously launched by start-local-editing.ps1.
#>
[CmdletBinding()]
param([string]$InstallRoot)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$installRoot = Get-CutWorkbenchInstallRoot -InstallRoot $InstallRoot
$serviceStatePath = Join-Path $installRoot "service\vectcut-service.json"
if (-not (Test-Path -LiteralPath $serviceStatePath -PathType Leaf)) {
    Write-Host "No managed VectCutAPI service state exists; nothing was stopped."
    exit 0
}

try {
    $state = Read-CutWorkbenchJsonFile -Path $serviceStatePath
} catch {
    throw "Invalid managed VectCutAPI service state: $serviceStatePath"
}
if ($null -eq $state.pid -or [string]$state.pid -notmatch "^\d+$" -or [string]::IsNullOrWhiteSpace([string]$state.started_at_utc)) {
    throw "Incomplete managed VectCutAPI service state: $serviceStatePath"
}
$process = Get-Process -Id ([int]$state.pid) -ErrorAction SilentlyContinue
if ($null -eq $process) {
    Remove-Item -LiteralPath $serviceStatePath -Force
    Write-Host "Managed VectCutAPI is not running; removed stale service state."
    exit 0
}
$recordedStart = ([DateTime]$state.started_at_utc).ToUniversalTime()
$actualStart = $process.StartTime.ToUniversalTime()
if ([Math]::Abs(($actualStart - $recordedStart).TotalSeconds) -gt 1) {
    throw "Refusing to stop PID $($process.Id): it does not match the process originally launched by start-local-editing.ps1."
}
Stop-Process -Id $process.Id -Force
Remove-Item -LiteralPath $serviceStatePath -Force
Write-Host "Stopped managed VectCutAPI process $($process.Id)."
