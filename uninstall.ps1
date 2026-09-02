#Requires -Version 5.1
<#
.SYNOPSIS
Remove components created by install.ps1 while preserving user state.
#>
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = "High")]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "WeWrite"),
    [switch]$RemoveState
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$manifestPath = Join-Path $InstallRoot "install.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Install manifest not found: $manifestPath"
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$expectedRoot = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd("\")
$recordedRoot = [System.IO.Path]::GetFullPath([string]$manifest.install_root).TrimEnd("\")
if ($expectedRoot -ine $recordedRoot) { throw "Manifest install_root does not match requested target" }

foreach ($linkPath in @($manifest.skill_links)) {
    if (-not (Test-Path -LiteralPath $linkPath)) { continue }
    $item = Get-Item -LiteralPath $linkPath -Force
    $isReparsePoint = ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
    if (-not $isReparsePoint) {
        Write-Warning "Preserved non-link path: $linkPath"
        continue
    }
    if ($PSCmdlet.ShouldProcess($linkPath, "Remove installer-created skill link")) {
        Remove-Item -LiteralPath $linkPath -Force
    }
}

$launcherDir = [string]$manifest.launcher_dir
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath) {
    $kept = @($userPath -split ";" | Where-Object {
        $_ -and $_.TrimEnd("\") -ine $launcherDir.TrimEnd("\")
    })
    if ($PSCmdlet.ShouldProcess("User PATH", "Remove $launcherDir")) {
        [Environment]::SetEnvironmentVariable("Path", ($kept -join ";"), "User")
    }
}

if ($PSCmdlet.ShouldProcess($expectedRoot, "Remove WeWrite CLI installation")) {
    # The exact target was validated against the install manifest above.
    Remove-Item -LiteralPath $expectedRoot -Recurse -Force
}

if ($RemoveState) {
    $stateRoot = [System.IO.Path]::GetFullPath((Join-Path $HOME ".wewrite"))
    if ($PSCmdlet.ShouldProcess($stateRoot, "Permanently remove WeWrite state and credentials")) {
        Remove-Item -LiteralPath $stateRoot -Recurse -Force
    }
} else {
    Write-Host "✓ Preserved user state: $(Join-Path $HOME '.wewrite')"
}
Write-Host "✓ WeWrite Windows components removed"
