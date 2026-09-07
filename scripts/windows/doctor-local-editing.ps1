<#
.SYNOPSIS
Checks whether this Windows machine can create and visually QA local Jianying drafts.

.PARAMETER MediaPath
Optional read-only media probe. It reports the actual video/audio stream types
using ffprobe; it does not run ASR and does not create a draft.
#>
[CmdletBinding()]
param(
    [string]$InstallRoot,
    [string]$MediaPath,
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$checks = [System.Collections.Generic.List[object]]::new()
function Add-CutWorkbenchCheck {
    param(
        [string]$Name,
        [bool]$Passed,
        [string]$Detail,
        [bool]$Critical = $true,
        [string]$Fix = ""
    )
    $checks.Add([PSCustomObject]@{
        check = $Name
        passed = $Passed
        critical = $Critical
        detail = $Detail
        fix = $Fix
    })
}

$installRoot = Get-CutWorkbenchInstallRoot -InstallRoot $InstallRoot
$runtimeRoot = Join-Path $installRoot "runtime"
$runtimeConfigPath = Join-Path $runtimeRoot "runtime-config.json"
$workbenchPython = Join-Path $installRoot "workbench-venv\Scripts\python.exe"
$vectCutRoot = Join-Path $installRoot "tools\VectCutAPI"
$vectCutProfilePath = Join-Path $vectCutRoot "config.json"
$testedVectCutRef = "d14e70749c9331424ab816a402bb45417c50cf68"
$defaultUrl = "http://127.0.0.1:9001"
$runtimeConfig = $null

if (Test-Path -LiteralPath $runtimeConfigPath -PathType Leaf) {
    try {
        $runtimeConfig = Read-CutWorkbenchJsonFile -Path $runtimeConfigPath
        Add-CutWorkbenchCheck -Name "runtime-config" -Passed $true -Detail $runtimeConfigPath
    } catch {
        Add-CutWorkbenchCheck -Name "runtime-config" -Passed $false -Detail $_.Exception.Message -Fix "Rerun install-local-editing.ps1 -ForceConfig."
    }
} else {
    Add-CutWorkbenchCheck -Name "runtime-config" -Passed $false -Detail "Missing $runtimeConfigPath" -Fix "Run install-local-editing.ps1."
}

$vectCutUrl = if ($null -ne $runtimeConfig -and $null -ne $runtimeConfig.vectcut -and $runtimeConfig.vectcut.base_url) { [string]$runtimeConfig.vectcut.base_url } else { $defaultUrl }
$draftFolder = if ($null -ne $runtimeConfig -and $null -ne $runtimeConfig.vectcut -and $runtimeConfig.vectcut.draft_folder) { [string]$runtimeConfig.vectcut.draft_folder } else { $null }
Add-CutWorkbenchCheck -Name "vectcut-loopback-url" -Passed (Test-CutWorkbenchLoopbackUrl -Url $vectCutUrl) -Detail $vectCutUrl -Fix "Use a localhost URL such as http://127.0.0.1:9001."

if (Test-Path -LiteralPath $workbenchPython -PathType Leaf) {
    try {
        & $workbenchPython -c "import cut_workbench; print('ok')" | Out-Null
        Add-CutWorkbenchCheck -Name "cut-workbench-python" -Passed ($LASTEXITCODE -eq 0) -Detail $workbenchPython -Fix "Rerun install-local-editing.ps1."
    } catch {
        Add-CutWorkbenchCheck -Name "cut-workbench-python" -Passed $false -Detail $_.Exception.Message -Fix "Rerun install-local-editing.ps1."
    }
} else {
    Add-CutWorkbenchCheck -Name "cut-workbench-python" -Passed $false -Detail "Missing $workbenchPython" -Fix "Run install-local-editing.ps1."
}

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
$ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
$ffmpegDetail = if ($ffmpeg) { $ffmpeg.Source } else { "ffmpeg not on PATH" }
$ffprobeDetail = if ($ffprobe) { $ffprobe.Source } else { "ffprobe not on PATH" }
Add-CutWorkbenchCheck -Name "ffmpeg-renderer" -Passed ($null -ne $ffmpeg) -Detail $ffmpegDetail -Fix "Install FFmpeg, then reopen PowerShell."
Add-CutWorkbenchCheck -Name "ffprobe-media-probe" -Passed ($null -ne $ffprobe) -Detail $ffprobeDetail -Fix "Install FFmpeg, then reopen PowerShell."

if (Test-Path -LiteralPath $vectCutProfilePath -PathType Leaf) {
    try {
        $profile = Read-CutWorkbenchJsonFile -Path $vectCutProfilePath
        $profileOk = $profile.draft_profile -eq "jianying_pro_10" -and [int]$profile.port -eq 9001 -and $profile.is_capcut_env -eq $false
        Add-CutWorkbenchCheck -Name "vectcut-profile" -Passed $profileOk -Detail ("{0}; profile={1}; port={2}" -f $vectCutProfilePath, $profile.draft_profile, $profile.port) -Fix "Rerun install-local-editing.ps1 -ForceConfig."
    } catch {
        Add-CutWorkbenchCheck -Name "vectcut-profile" -Passed $false -Detail $_.Exception.Message -Fix "Rerun install-local-editing.ps1 -ForceConfig."
    }
} else {
    Add-CutWorkbenchCheck -Name "vectcut-profile" -Passed $false -Detail "Missing $vectCutProfilePath" -Fix "Run install-local-editing.ps1."
}

$git = Get-Command git -ErrorAction SilentlyContinue
if ($null -ne $git -and (Test-Path -LiteralPath (Join-Path $vectCutRoot ".git") -PathType Container)) {
    $actualVectCutRef = (& $git.Source -C $vectCutRoot rev-parse HEAD 2>$null).Trim()
    Add-CutWorkbenchCheck -Name "vectcut-tested-revision" -Passed ($actualVectCutRef -eq $testedVectCutRef) -Detail $actualVectCutRef -Critical $false -Fix "Use the installer on a fresh VectCutAPI directory, or manually checkout $testedVectCutRef."
} else {
    Add-CutWorkbenchCheck -Name "vectcut-tested-revision" -Passed $false -Detail "Git revision is unavailable" -Critical $false -Fix "Install Git or use a fresh installer-managed VectCutAPI directory."
}

if ($draftFolder) {
    $draftFolderExists = Test-Path -LiteralPath $draftFolder -PathType Container
    $draftFolderWritable = $draftFolderExists -and (Test-CutWorkbenchDirectoryWritable -Path $draftFolder)
    Add-CutWorkbenchCheck -Name "jianying-draft-folder" -Passed $draftFolderWritable -Detail $draftFolder -Fix "Open Jianying once and rerun install with -JianyingDraftFolder <actual folder>."
} else {
    Add-CutWorkbenchCheck -Name "jianying-draft-folder" -Passed $false -Detail "No configured draft folder" -Fix "Rerun install-local-editing.ps1 with -JianyingDraftFolder <actual folder>."
}

$jianyingExe = Get-CutWorkbenchJianyingExecutable
$jianyingDetail = if ($jianyingExe) { $jianyingExe } else { "Not found in conventional locations; a custom installation may still work." }
Add-CutWorkbenchCheck -Name "jianying-executable" -Passed ($null -ne $jianyingExe) -Detail $jianyingDetail -Critical $false -Fix "Open Jianying Pro and confirm it can see the configured draft folder."

Add-CutWorkbenchCheck -Name "local-vectcut-service" -Passed (Test-CutWorkbenchVectCutHealth -BaseUrl $vectCutUrl) -Detail $vectCutUrl -Fix "Run start-local-editing.ps1, then rerun doctor."

if (Test-Path -LiteralPath $workbenchPython -PathType Leaf) {
    try {
        & $workbenchPython -c "import cv2, PIL; print('ok')" | Out-Null
        Add-CutWorkbenchCheck -Name "visual-qa-packages" -Passed ($LASTEXITCODE -eq 0) -Detail "opencv-python + Pillow" -Critical $false -Fix "Rerun install-local-editing.ps1 without -SkipVisualQa."
    } catch {
        Add-CutWorkbenchCheck -Name "visual-qa-packages" -Passed $false -Detail "opencv-python/Pillow unavailable" -Critical $false -Fix "Rerun install-local-editing.ps1 without -SkipVisualQa."
    }
}

if (-not [string]::IsNullOrWhiteSpace($MediaPath)) {
    if (-not (Test-Path -LiteralPath $MediaPath -PathType Leaf)) {
        Add-CutWorkbenchCheck -Name "media-stream-probe" -Passed $false -Detail "Media file does not exist: $MediaPath" -Fix "Pass an existing local video or audio file."
    } elseif ($null -eq $ffprobe) {
        Add-CutWorkbenchCheck -Name "media-stream-probe" -Passed $false -Detail "ffprobe is unavailable" -Fix "Install FFmpeg."
    } else {
        try {
            $probeJson = & $ffprobe.Source -v error -show_entries stream=codec_type -of json $MediaPath
            if ($LASTEXITCODE -ne 0) { throw "ffprobe exit code $LASTEXITCODE" }
            $probe = $probeJson | ConvertFrom-Json
            $types = @($probe.streams | ForEach-Object { $_.codec_type }) -join ", "
            Add-CutWorkbenchCheck -Name "media-stream-probe" -Passed $true -Detail ("Detected streams: " + $types)
        } catch {
            Add-CutWorkbenchCheck -Name "media-stream-probe" -Passed $false -Detail $_.Exception.Message -Fix "Verify that the source file is readable by FFmpeg."
        }
    }
}

$criticalFailures = @($checks | Where-Object { $_.critical -and -not $_.passed })
if ($Json) {
    [PSCustomObject]@{
        passed = ($criticalFailures.Count -eq 0)
        vectcut_url = $vectCutUrl
        checks = $checks
    } | ConvertTo-Json -Depth 6
} else {
    $checks | Format-Table check, passed, critical, detail, fix -Wrap
    if ($criticalFailures.Count -eq 0) {
        Write-Host "Doctor passed: this machine can create local editable Jianying drafts and run FFmpeg media checks."
    } else {
        Write-Error ("Doctor found {0} critical issue(s). Apply the listed fix and rerun." -f $criticalFailures.Count)
    }
}

if ($criticalFailures.Count -gt 0) {
    exit 1
}
