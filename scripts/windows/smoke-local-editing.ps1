<#
.SYNOPSIS
Creates one real, short Jianying smoke draft from a local source video.

.DESCRIPTION
This is deliberately opt-in because it creates a new draft. It validates source
immutability, two source trims, local VectCutAPI execution, and saved draft files.
After it passes, open Jianying Pro and confirm that the new smoke draft appears.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Source,
    [string]$InstallRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$sourceRoot = Get-CutWorkbenchRepositoryRoot -ScriptsDirectory $PSScriptRoot
$installRoot = Get-CutWorkbenchInstallRoot -InstallRoot $InstallRoot
$runtimeRoot = Join-Path $installRoot "runtime"
$runtimeConfigPath = Join-Path $runtimeRoot "runtime-config.json"
$workbenchPython = Join-Path $installRoot "workbench-venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
    throw "Source video does not exist: $Source"
}
if (-not (Test-Path -LiteralPath $runtimeConfigPath -PathType Leaf) -or -not (Test-Path -LiteralPath $workbenchPython -PathType Leaf)) {
    throw "Missing installation files. Run install-local-editing.ps1 first."
}
$config = Read-CutWorkbenchJsonFile -Path $runtimeConfigPath
$url = [string]$config.vectcut.base_url
$draftFolder = [string]$config.vectcut.draft_folder
if (-not (Test-CutWorkbenchVectCutHealth -BaseUrl $url)) {
    throw "Local VectCutAPI is not healthy at $url. Run start-local-editing.ps1 first."
}
if (-not (Test-Path -LiteralPath $draftFolder -PathType Container) -or -not (Test-CutWorkbenchDirectoryWritable -Path $draftFolder)) {
    throw "Configured Jianying draft folder is not writable: $draftFolder"
}

$smokeRoot = Join-Path $installRoot "smoke-runtime"
& $workbenchPython (Join-Path $sourceRoot "scripts\smoke_vectcut.py") `
    --source $Source `
    --root $smokeRoot `
    --url $url `
    --draft-folder $draftFolder
if ($LASTEXITCODE -ne 0) {
    throw "Local real-media smoke test failed with exit code $LASTEXITCODE."
}
Write-Host "Smoke draft created. Open Jianying Pro and confirm the new Local VectCut smoke draft is visible and playable."
