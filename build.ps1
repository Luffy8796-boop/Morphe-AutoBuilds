[CmdletBinding()]
param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$App,

    [Parameter(Mandatory=$true, Position=1)]
    [string]$Source,

    [string]$Arch = "arm64-v8a",
    [string]$ApkArch = "universal",
    [string]$KeepLocales = "en",
    [switch]$SkipLocaleSlimming
)

$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Error "Virtual environment not found at .venv. Please run: python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
}

$env:APP_NAME = $App
$env:SOURCE = $Source
$env:ARCH = $Arch
$env:APK_ARCH = $ApkArch
$env:KEEP_LOCALES = $KeepLocales
if ($SkipLocaleSlimming) {
    $env:SKIP_LOCALE_SLIMMING = "true"
}

Write-Host "🔨 Starting build for $App ($Source) targeting $Arch..." -ForegroundColor Cyan
& $venvPython -m src
