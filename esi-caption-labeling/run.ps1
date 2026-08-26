#Requires -Version 5.1
<#
.SYNOPSIS
  Attach the ESI caption bot to an already-open IX or MoreLogin Chromium profile.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\run-ix.ps1
  powershell -ExecutionPolicy Bypass -File .\run-morelogin.ps1
#>

$ErrorActionPreference = "Stop"

function Find-ProjectRoot {
    $candidates = @()
    $here = (Get-Location).Path
    $candidates += $here
    $candidates += (Join-Path $here "esi-caption-labeling")
    $candidates += (Join-Path $here "ATLAS\esi-caption-labeling")
    $candidates += (Join-Path $env:USERPROFILE "ATLAS\esi-caption-labeling")
    if ($PSScriptRoot) {
        $candidates += $PSScriptRoot
        $candidates += (Join-Path $PSScriptRoot "esi-caption-labeling")
    }
    foreach ($path in $candidates) {
        if ($path -and (Test-Path (Join-Path $path "main.py")) -and (Test-Path (Join-Path $path "esi_caption"))) {
            return (Resolve-Path $path).Path
        }
    }
    return $null
}

$root = Find-ProjectRoot
if (-not $root) {
    Write-Host @"
This folder is not the ESI caption bot.

Use the ATLAS git repo:

  cd $env:USERPROFILE\ATLAS
  git fetch origin
  git checkout -B cursor/esi-caption-labeling-7517 origin/cursor/esi-caption-labeling-7517
  powershell -ExecutionPolicy Bypass -File .\run-ix.ps1
  # or
  powershell -ExecutionPolicy Bypass -File .\run-morelogin.ps1

Open the IX or MoreLogin profile yourself first. Leave
https://www.multimango.com/tasks/vs-1781285808-260612-esi-caption-labeling
on screen. Debug port 9222 is optional.
"@
    exit 1
}

Set-Location $root
Write-Host "[Setup] Project: $root"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python was not found. Install Python 3.12 from https://www.python.org/downloads/"
    Write-Host "During setup, enable 'Add python.exe to PATH'."
    exit 1
}

$venvPython = $null
foreach ($name in @("venv", ".venv")) {
    $candidate = Join-Path $root "$name\Scripts\python.exe"
    if (Test-Path $candidate) {
        $venvPython = $candidate
        break
    }
}

if (-not $venvPython) {
    Write-Host "[Setup] Creating virtual environment..."
    python -m venv venv
    $venvPython = Join-Path $root "venv\Scripts\python.exe"
}

Write-Host "[Setup] Installing Python packages (IX/MoreLogin attach + desktop fallback)..."
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $venvPython -m pip install -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[Setup] Installing Playwright client (used only to attach if DevTools is on)..."
& $venvPython -m playwright install chromium
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$browser = $env:ESI_BROWSER
if (-not $browser) { $browser = "ix" }
$pass = @("--browser", $browser)
if ($args) { $pass += $args }

Write-Host "[Run] Attach to your already-open $browser window. Do not close that window."
Write-Host "[Run] Target: https://www.multimango.com/tasks/vs-1781285808-260612-esi-caption-labeling"
& $venvPython (Join-Path $root "main.py") @pass
exit $LASTEXITCODE
