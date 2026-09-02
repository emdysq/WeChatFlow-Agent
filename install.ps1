#Requires -Version 5.1
<#
.SYNOPSIS
Install WeChatFlow Agent CLI and Agent Skills on Windows.

.DESCRIPTION
Creates a dedicated virtual environment under LocalAppData, adds its launcher
directory to the user PATH, and links every wewrite* skill into selected Agent
Skills directories. The operation is idempotent and never overwrites an
unrelated skill directory.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$RepoRoot = $PSScriptRoot,
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "WeWrite"),
    [string]$Python = "",
    [string[]]$SkillTarget = @(),
    [switch]$SkipCli,
    [switch]$SkipSkills,
    [switch]$SkipMigration,
    [switch]$NoPathUpdate
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $repo "pyproject.toml") -PathType Leaf)) {
    throw "RepoRoot does not contain pyproject.toml: $repo"
}

function Resolve-PythonCommand {
    param([string]$Requested)
    if ($Requested) {
        $candidate = Get-Command $Requested -ErrorAction SilentlyContinue
        if (-not $candidate) { throw "Python command not found: $Requested" }
        $probe = & $candidate.Source -c "import sys; print(sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $probe) { throw "Python command is not runnable: $Requested" }
        return $candidate.Source
    }
    $repoPython = Join-Path $repo ".venv\Scripts\python.exe"
    foreach ($name in @($repoPython, "py", "python", "python3")) {
        $candidate = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $candidate) { continue }
        $probe = & $candidate.Source -c "import sys; print(sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $probe) { return $candidate.Source }
    }
    throw "No runnable Python found (Microsoft Store aliases do not count). Install Python 3.11+ or pass -Python <path>."
}

function Assert-PythonVersion {
    param([string]$Command)
    $version = & $Command -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0 -or -not $version) { throw "Unable to run Python: $Command" }
    $parts = $version.Trim().Split(".")
    if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 11)) {
        throw "Python 3.11+ is required; found $version"
    }
}

function Add-UserPathEntry {
    param([string]$Entry)
    $current = [Environment]::GetEnvironmentVariable("Path", "User")
    $items = @($current -split ";" | Where-Object { $_ })
    if ($items | Where-Object { $_.TrimEnd("\") -ieq $Entry.TrimEnd("\") }) { return $false }
    $updated = (@($items) + $Entry) -join ";"
    [Environment]::SetEnvironmentVariable("Path", $updated, "User")
    return $true
}

function Get-DefaultSkillTargets {
    $targets = @((Join-Path $HOME ".agents\skills"))
    foreach ($parent in @(".codex", ".claude", ".openclaw")) {
        $parentPath = Join-Path $HOME $parent
        if (Test-Path -LiteralPath $parentPath -PathType Container) {
            $targets += Join-Path $parentPath "skills"
        }
    }
    return $targets | Select-Object -Unique
}

function Get-LinkTargetPath {
    param([System.IO.FileSystemInfo]$Item)
    if (-not $Item.PSObject.Properties.Name.Contains("Target") -or -not $Item.Target) { return $null }
    $rawTarget = @($Item.Target)[0]
    if ([System.IO.Path]::IsPathRooted($rawTarget)) { return [System.IO.Path]::GetFullPath($rawTarget) }
    return [System.IO.Path]::GetFullPath((Join-Path $Item.Parent.FullName $rawTarget))
}

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
$manifestPath = Join-Path $InstallRoot "install.json"
$launcherDir = Join-Path $InstallRoot "bin"
$venvDir = Join-Path $InstallRoot "venv"
$linkedSkills = @()

if (-not $SkipCli) {
    $pythonCommand = Resolve-PythonCommand -Requested $Python
    Assert-PythonVersion -Command $pythonCommand
    if (-not (Test-Path -LiteralPath (Join-Path $venvDir "Scripts\python.exe") -PathType Leaf)) {
        Write-Host "→ Creating Windows virtual environment: $venvDir"
        & $pythonCommand -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { throw "Failed to create virtual environment" }
    }
    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    Write-Host "→ Installing WeChatFlow Agent from $repo"
    & $venvPython -m pip install --disable-pip-version-check --quiet -e $repo
    if ($LASTEXITCODE -ne 0) { throw "Failed to install WeWrite" }
    New-Item -ItemType Directory -Force -Path $launcherDir | Out-Null
    foreach ($commandName in @("wechatflow", "wewrite")) {
        $launcher = Join-Path $launcherDir "$commandName.cmd"
        $launcherText = "@echo off" + [Environment]::NewLine +
            [char]34 + (Join-Path $venvDir "Scripts\$commandName.exe") + [char]34 + " %*" +
            [Environment]::NewLine
        [System.IO.File]::WriteAllText($launcher, $launcherText, [System.Text.Encoding]::ASCII)
    }
    if (-not $NoPathUpdate) {
        if (Add-UserPathEntry -Entry $launcherDir) {
            Write-Host "✓ Added to user PATH: $launcherDir"
        }
        if (-not (($env:Path -split ";") | Where-Object { $_.TrimEnd("\") -ieq $launcherDir.TrimEnd("\") })) {
            $env:Path = "$launcherDir;$env:Path"
        }
    }
    Write-Host "✓ CLI ready: $(Join-Path $launcherDir 'wechatflow.cmd')"
}

if (-not $SkipSkills) {
    $targets = if ($SkillTarget.Count) { $SkillTarget } else { @(Get-DefaultSkillTargets) }
    $skillSources = Get-ChildItem -LiteralPath (Join-Path $repo "skills") -Directory |
        Where-Object { $_.Name -like "wewrite*" -and (Test-Path -LiteralPath (Join-Path $_.FullName "SKILL.md")) }
    foreach ($targetRoot in $targets) {
        New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
        foreach ($source in $skillSources) {
            $destination = Join-Path $targetRoot $source.Name
            if (Test-Path -LiteralPath $destination) {
                $existing = Get-Item -LiteralPath $destination -Force
                $existingTarget = Get-LinkTargetPath -Item $existing
                if ($existingTarget -and $existingTarget.TrimEnd("\") -ieq $source.FullName.TrimEnd("\")) {
                    $linkedSkills += $destination
                    continue
                }
                Write-Warning "Skipped existing unrelated skill: $destination"
                continue
            }
            New-Item -ItemType Junction -Path $destination -Target $source.FullName | Out-Null
            $linkedSkills += $destination
        }
        Write-Host "✓ Skills checked: $targetRoot"
    }
}

if (-not $SkipMigration -and -not $SkipCli) {
    $legacyFiles = @("style.yaml", "history.yaml", "config.yaml") |
        Where-Object { Test-Path -LiteralPath (Join-Path $repo $_) -PathType Leaf }
    if ($legacyFiles.Count) {
        & (Join-Path $venvDir "Scripts\wewrite.exe") migrate --from $repo
        if ($LASTEXITCODE -ne 0) { throw "Legacy state migration failed" }
    }
}

$manifest = [ordered]@{
    schema_version = 1
    installed_at = (Get-Date).ToUniversalTime().ToString("o")
    repo_root = $repo
    install_root = [System.IO.Path]::GetFullPath($InstallRoot)
    cli_installed = -not [bool]$SkipCli
    launcher_dir = $launcherDir
    venv_dir = $venvDir
    skill_links = @($linkedSkills | Select-Object -Unique)
    state_preserved_on_uninstall = $true
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
Write-Host ""
Write-Host "✓ WeChatFlow Agent Windows installation complete"
Write-Host "  Manifest: $manifestPath"
Write-Host "  State:    $(Join-Path $HOME '.wewrite') (not modified by uninstall)"
