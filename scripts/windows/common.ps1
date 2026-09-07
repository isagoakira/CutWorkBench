# Shared helpers for the Windows-first local Cut Workbench setup.
# This file deliberately performs no installation or service mutation on import.

function Get-CutWorkbenchRepositoryRoot {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$ScriptsDirectory)

    return (Resolve-Path -LiteralPath (Join-Path $ScriptsDirectory "..\..")).Path
}

function Get-CutWorkbenchInstallRoot {
    [CmdletBinding()]
    param([string]$InstallRoot)

    if (-not [string]::IsNullOrWhiteSpace($InstallRoot)) {
        return [System.IO.Path]::GetFullPath($InstallRoot)
    }
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "LOCALAPPDATA is unavailable. Pass -InstallRoot explicitly."
    }
    return (Join-Path $env:LOCALAPPDATA "CutWorkbench")
}

function Update-CutWorkbenchProcessPath {
    [CmdletBinding()]
    param()

    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @($machinePath, $userPath, $env:Path) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    $env:Path = ($parts -join ";")
}

function Get-CutWorkbenchPython {
    [CmdletBinding()]
    param([string]$PreferredPython)

    if (-not [string]::IsNullOrWhiteSpace($PreferredPython)) {
        if (-not (Test-Path -LiteralPath $PreferredPython -PathType Leaf)) {
            throw "-PythonExecutable does not exist: $PreferredPython"
        }
        return (Resolve-Path -LiteralPath $PreferredPython).Path
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Python 3.11+ was not found on PATH. Rerun with -InstallPrerequisites or pass -PythonExecutable."
    }
    return $command.Source
}

function Assert-CutWorkbenchPythonVersion {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$PythonExecutable)

    $raw = (& $PythonExecutable -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($raw)) {
        throw "Unable to run Python at $PythonExecutable"
    }
    try {
        $version = [version]$raw
    } catch {
        throw "Unable to parse Python version '$raw' from $PythonExecutable"
    }
    if ($version -lt [version]"3.11") {
        throw "Cut Workbench requires Python 3.11 or later; found $raw at $PythonExecutable"
    }
    return $version
}

function Get-ExistingJianyingDraftFolder {
    [CmdletBinding()]
    param([string]$RequestedFolder)

    if (-not [string]::IsNullOrWhiteSpace($RequestedFolder)) {
        if (-not (Test-Path -LiteralPath $RequestedFolder -PathType Container)) {
            throw "The supplied Jianying draft folder does not exist: $RequestedFolder"
        }
        return (Resolve-Path -LiteralPath $RequestedFolder).Path
    }

    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        return $null
    }
    $candidate = Join-Path $env:LOCALAPPDATA "JianyingPro\User Data\Projects\com.lveditor.draft"
    if (Test-Path -LiteralPath $candidate -PathType Container) {
        return (Resolve-Path -LiteralPath $candidate).Path
    }
    return $null
}

function Get-CutWorkbenchJianyingExecutable {
    [CmdletBinding()]
    param()

    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    $candidates = @()
    if ($env:LOCALAPPDATA) {
        $candidates += (Join-Path $env:LOCALAPPDATA "JianyingPro\JianyingPro.exe")
        $candidates += (Join-Path $env:LOCALAPPDATA "JianyingPro\Apps\JianyingPro.exe")
    }
    if ($env:ProgramFiles) {
        $candidates += (Join-Path $env:ProgramFiles "JianyingPro\JianyingPro.exe")
    }
    if ($programFilesX86) {
        $candidates += (Join-Path $programFilesX86 "JianyingPro\JianyingPro.exe")
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Test-CutWorkbenchLoopbackUrl {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        $uri = [Uri]$Url
    } catch {
        return $false
    }
    return $uri.Scheme -in @("http", "https") -and $uri.Host -in @("localhost", "127.0.0.1", "::1")
}

function Test-CutWorkbenchVectCutHealth {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$BaseUrl)

    try {
        $response = Invoke-RestMethod -Method Get -Uri (([string]$BaseUrl).TrimEnd("/") + "/get_mask_types") -TimeoutSec 5 -ErrorAction Stop
        return $null -ne $response -and $response.success -eq $true -and $response.output -is [array]
    } catch {
        return $false
    }
}

function Wait-CutWorkbenchVectCutHealth {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [int]$TimeoutSeconds = 30
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-CutWorkbenchVectCutHealth -BaseUrl $BaseUrl) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Write-CutWorkbenchJsonFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Read-CutWorkbenchJsonFile {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Path)

    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Test-CutWorkbenchDirectoryWritable {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Path)

    try {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
        $probe = Join-Path $Path (".cut-workbench-write-" + [Guid]::NewGuid().ToString("N") + ".tmp")
        [System.IO.File]::WriteAllText($probe, "ok")
        Remove-Item -LiteralPath $probe -Force
        return $true
    } catch {
        return $false
    }
}
