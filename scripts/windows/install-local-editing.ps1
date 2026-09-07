<#
.SYNOPSIS
Installs the local, no-cloud Cut Workbench + VectCutAPI editing kit for Jianying Pro.

.DESCRIPTION
This script is Windows-first. It creates isolated Python environments, configures
one local VectCutAPI service on loopback, and writes a ready-to-copy MCP config.
It never edits an existing Jianying draft and does not call a cloud VectCut service.
#>
[CmdletBinding()]
param(
    [string]$InstallRoot,
    [string]$JianyingDraftFolder,
    [string]$PythonExecutable,
    [switch]$InstallPrerequisites,
    [switch]$SkipVisualQa,
    [switch]$ForceConfig,
    [switch]$StartService,
    [switch]$NonInteractive,
    [string]$VectCutRepository = "https://github.com/sun-guannan/VectCutAPI.git",
    [string]$VectCutRef = "d14e70749c9331424ab816a402bb45417c50cf68"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

function Ensure-CutWorkbenchCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$WingetId
    )

    if (Get-Command $Name -ErrorAction SilentlyContinue) {
        return
    }
    if (-not $InstallPrerequisites) {
        throw "Missing '$Name'. Rerun with -InstallPrerequisites, install it manually, then rerun this script."
    }
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($null -eq $winget) {
        throw "Missing '$Name' and winget is unavailable. Install $Name manually, reopen PowerShell, and rerun."
    }
    Write-Host "Installing $Name with winget ($WingetId)..."
    & $winget.Source install --exact --id $WingetId --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget failed while installing $Name (exit code $LASTEXITCODE)."
    }
    Update-CutWorkbenchProcessPath
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was installed but is not available in this shell yet. Open a new PowerShell window and rerun this script."
    }
}

function Invoke-CutWorkbenchExternal {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

$sourceRoot = Get-CutWorkbenchRepositoryRoot -ScriptsDirectory $PSScriptRoot
$installRoot = Get-CutWorkbenchInstallRoot -InstallRoot $InstallRoot
$runtimeRoot = Join-Path $installRoot "runtime"
$toolsRoot = Join-Path $installRoot "tools"
$vectCutRoot = Join-Path $toolsRoot "VectCutAPI"
$workbenchVenv = Join-Path $installRoot "workbench-venv"
$vectCutVenv = Join-Path $vectCutRoot ".venv"
$workbenchPython = Join-Path $workbenchVenv "Scripts\python.exe"
$vectCutPython = Join-Path $vectCutVenv "Scripts\python.exe"
$runtimeConfigPath = Join-Path $runtimeRoot "runtime-config.json"
$mcpConfigPath = Join-Path $installRoot "agent-mcp-config.json"

Ensure-CutWorkbenchCommand -Name "git" -WingetId "Git.Git"
Ensure-CutWorkbenchCommand -Name "python" -WingetId "Python.Python.3.11"
Ensure-CutWorkbenchCommand -Name "ffmpeg" -WingetId "Gyan.FFmpeg"
Ensure-CutWorkbenchCommand -Name "ffprobe" -WingetId "Gyan.FFmpeg"

$python = Get-CutWorkbenchPython -PreferredPython $PythonExecutable
$pythonVersion = Assert-CutWorkbenchPythonVersion -PythonExecutable $python
$git = (Get-Command git -ErrorAction Stop).Source
$ffprobe = (Get-Command ffprobe -ErrorAction Stop).Source

$draftFolder = Get-ExistingJianyingDraftFolder -RequestedFolder $JianyingDraftFolder
if ($null -eq $draftFolder) {
    if ($NonInteractive) {
        throw "Jianying's draft folder was not found. Open Jianying Pro once, then rerun with -JianyingDraftFolder <folder>."
    }
    Write-Host "Jianying's default draft folder was not found. Open Jianying Pro once, or paste its draft folder now."
    $enteredFolder = Read-Host "Jianying draft folder"
    $draftFolder = Get-ExistingJianyingDraftFolder -RequestedFolder $enteredFolder
}
if (-not (Test-CutWorkbenchDirectoryWritable -Path $draftFolder)) {
    throw "Jianying's draft folder is not writable: $draftFolder"
}

New-Item -ItemType Directory -Force -Path $installRoot, $runtimeRoot, $toolsRoot | Out-Null

if (-not (Test-Path -LiteralPath $workbenchPython -PathType Leaf)) {
    Write-Host "Creating isolated Cut Workbench Python environment..."
    Invoke-CutWorkbenchExternal -Description "Create Cut Workbench virtual environment" -Action { & $python -m venv $workbenchVenv }
}
Invoke-CutWorkbenchExternal -Description "Upgrade Cut Workbench pip" -Action { & $workbenchPython -m pip install --disable-pip-version-check --upgrade pip setuptools wheel }
Invoke-CutWorkbenchExternal -Description "Install Cut Workbench" -Action { & $workbenchPython -m pip install --disable-pip-version-check -e $sourceRoot }
if (-not $SkipVisualQa) {
    Invoke-CutWorkbenchExternal -Description "Install optional visual QA packages" -Action { & $workbenchPython -m pip install --disable-pip-version-check opencv-python Pillow }
}

if (-not (Test-Path -LiteralPath $vectCutRoot)) {
    Write-Host "Cloning tested local VectCutAPI revision..."
    Invoke-CutWorkbenchExternal -Description "Clone VectCutAPI" -Action { & $git clone --no-checkout $VectCutRepository $vectCutRoot }
    Invoke-CutWorkbenchExternal -Description "Fetch tested VectCutAPI revision" -Action { & $git -C $vectCutRoot fetch --depth 1 origin $VectCutRef }
    Invoke-CutWorkbenchExternal -Description "Checkout tested VectCutAPI revision" -Action { & $git -C $vectCutRoot checkout --detach $VectCutRef }
} elseif (-not (Test-Path -LiteralPath (Join-Path $vectCutRoot "capcut_server.py") -PathType Leaf)) {
    throw "Existing VectCutAPI directory is not valid: $vectCutRoot"
} else {
    $existingRef = (& $git -C $vectCutRoot rev-parse HEAD 2>$null).Trim()
    if ($existingRef -ne $VectCutRef) {
        Write-Warning "Keeping existing VectCutAPI revision $existingRef. The tested revision is $VectCutRef; doctor will report the difference."
    }
}

if (-not (Test-Path -LiteralPath $vectCutPython -PathType Leaf)) {
    Write-Host "Creating isolated VectCutAPI Python environment..."
    Invoke-CutWorkbenchExternal -Description "Create VectCutAPI virtual environment" -Action { & $python -m venv $vectCutVenv }
}
Invoke-CutWorkbenchExternal -Description "Upgrade VectCutAPI pip" -Action { & $vectCutPython -m pip install --disable-pip-version-check --upgrade pip }
Invoke-CutWorkbenchExternal -Description "Install VectCutAPI requirements" -Action { & $vectCutPython -m pip install --disable-pip-version-check -r (Join-Path $vectCutRoot "requirements.txt") }

$vectCutProfilePath = Join-Path $vectCutRoot "config.json"
$vectCutProfile = [ordered]@{
    draft_profile = "jianying_pro_10"
    is_capcut_env = $false
    port = 9001
    is_upload_draft = $false
    draft_domain = "http://127.0.0.1:9001"
}
if ($ForceConfig -or -not (Test-Path -LiteralPath $vectCutProfilePath -PathType Leaf)) {
    Write-CutWorkbenchJsonFile -Path $vectCutProfilePath -Value $vectCutProfile
} else {
    Write-Warning "Keeping existing VectCutAPI config: $vectCutProfilePath. Use -ForceConfig to write the tested Jianying profile."
}

$runtimeConfig = [ordered]@{
    vectcut = [ordered]@{
        base_url = "http://127.0.0.1:9001"
        timeout = 120
        draft_folder = $draftFolder
    }
    providers = @(
        [ordered]@{
            kind = "ffprobe"
            executable = $ffprobe
        }
    )
}
$effectiveDraftFolder = $draftFolder
if ($ForceConfig -or -not (Test-Path -LiteralPath $runtimeConfigPath -PathType Leaf)) {
    Write-CutWorkbenchJsonFile -Path $runtimeConfigPath -Value $runtimeConfig
} else {
    try {
        $existingRuntimeConfig = Read-CutWorkbenchJsonFile -Path $runtimeConfigPath
        if ($null -ne $existingRuntimeConfig.vectcut -and $existingRuntimeConfig.vectcut.draft_folder) {
            $effectiveDraftFolder = [string]$existingRuntimeConfig.vectcut.draft_folder
        }
    } catch {
        Write-Warning "Existing runtime config cannot be parsed; doctor will report it: $runtimeConfigPath"
    }
    Write-Warning "Keeping existing runtime config: $runtimeConfigPath. Use -ForceConfig to overwrite it."
    if ($effectiveDraftFolder -ne $draftFolder) {
        Write-Warning "The retained runtime config targets a different draft folder: $effectiveDraftFolder"
    }
}

$agentConfig = [ordered]@{
    mcpServers = [ordered]@{
        "cut-workbench" = [ordered]@{
            command = $workbenchPython
            args = @("-m", "cut_workbench.cli", "--root", $runtimeRoot, "--config", $runtimeConfigPath, "mcp")
            cwd = $sourceRoot
        }
    }
}
Write-CutWorkbenchJsonFile -Path $mcpConfigPath -Value $agentConfig

$receiptPath = Join-Path $installRoot "installation.json"
$receipt = [ordered]@{
    installed_at_utc = [DateTime]::UtcNow.ToString("o")
    source_root = $sourceRoot
    install_root = $installRoot
    runtime_root = $runtimeRoot
    jianying_draft_folder = $effectiveDraftFolder
    python_version = $pythonVersion.ToString()
    workbench_python = $workbenchPython
    vectcut_python = $vectCutPython
    vectcut_repository = $VectCutRepository
    vectcut_ref = $VectCutRef
    runtime_config = $runtimeConfigPath
    agent_mcp_config = $mcpConfigPath
    visual_qa_installed = (-not $SkipVisualQa)
}
Write-CutWorkbenchJsonFile -Path $receiptPath -Value $receipt

Write-Host "Installation complete."
Write-Host "Runtime config: $runtimeConfigPath"
Write-Host "Agent MCP snippet: $mcpConfigPath"
Write-Host "Next: run scripts\\windows\\start-local-editing.ps1, then scripts\\windows\\doctor-local-editing.ps1."

if ($StartService) {
    & (Join-Path $PSScriptRoot "start-local-editing.ps1") -InstallRoot $installRoot
}
