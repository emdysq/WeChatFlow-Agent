#Requires -Version 5.1
<#
.SYNOPSIS
Run a deterministic, offline WeWrite demo on Windows.

.DESCRIPTION
Converts the bundled Markdown article, validates the generated HTML, and runs
the writing-quality scorer. It never reads WeChat credentials or performs a
publish operation.
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$OutputDir = "",
    [string]$Theme = "professional-clean",
    [switch]$NoOpen
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not $OutputDir) { $OutputDir = Join-Path $repo ".artifacts\windows-demo" }
$output = [System.IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path $output | Out-Null

$candidates = @(
    (Join-Path $repo ".venv\Scripts\wewrite.exe"),
    (Join-Path $env:LOCALAPPDATA "WeWrite\venv\Scripts\wewrite.exe")
)
$command = Get-Command "wewrite" -ErrorAction SilentlyContinue
if ($command) { $cli = $command.Source }
else { $cli = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1 }
if (-not $cli) { throw "WeWrite CLI not found. Run install.ps1 first." }

$article = Join-Path $repo "docs\demo-article.md"
$preview = Join-Path $output "preview.html"
$validationPath = Join-Path $output "validation.json"
$scorePath = Join-Path $output "score.json"
$reportPath = Join-Path $output "demo-report.json"
$previousHome = $env:WEWRITE_HOME
$env:WEWRITE_HOME = Join-Path $output "state"

try {
    Write-Host "→ Rendering bundled article"
    & $cli preview $article --theme $Theme --output $preview --no-open
    if ($LASTEXITCODE -ne 0) { throw "Preview command failed with exit code $LASTEXITCODE" }

    Write-Host "→ Validating WeChat HTML compatibility"
    $validation = & $cli validate $preview --json
    if ($LASTEXITCODE -ne 0) { throw "HTML validation failed with exit code $LASTEXITCODE" }
    [System.IO.File]::WriteAllText(
        $validationPath,
        ($validation -join [Environment]::NewLine) + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )

    Write-Host "→ Scoring writing quality"
    $score = & $cli score $article --json
    if ($LASTEXITCODE -ne 0) { throw "Quality scoring failed with exit code $LASTEXITCODE" }
    [System.IO.File]::WriteAllText(
        $scorePath,
        ($score -join [Environment]::NewLine) + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )

    $report = [ordered]@{
        schema_version = 1
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        network_requests = 0
        credentials_read = $false
        source = $article
        theme = $Theme
        preview = $preview
        validation = $validationPath
        score = $scorePath
    }
    [System.IO.File]::WriteAllText(
        $reportPath,
        ($report | ConvertTo-Json -Depth 3) + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
} finally {
    $env:WEWRITE_HOME = $previousHome
}

Write-Host "✓ Offline demo complete: $reportPath"
if (-not $NoOpen) { Start-Process $preview }
