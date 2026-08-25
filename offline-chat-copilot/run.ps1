#Requires -Version 5.1
<#
.SYNOPSIS
  Attach the offline chat copilot to your already-open IX Browser profile.

.EXAMPLE
  Open IX Browser yourself, open https://chathomebase.com/chat/claimed, then:

  cd $env:USERPROFILE\ATLAS
  git fetch origin
  git checkout -B cursor/offline-chat-copilot-7517 origin/cursor/offline-chat-copilot-7517
  cd offline-chat-copilot
  powershell -ExecutionPolicy Bypass -File .\run.ps1
#>

$ErrorActionPreference = "Stop"

function Find-ProjectRoot {
    $candidates = @()
    $here = (Get-Location).Path
    $candidates += $here
    $candidates += (Join-Path $here "offline-chat-copilot")
    $candidates += (Join-Path $here "ATLAS\offline-chat-copilot")
    $candidates += (Join-Path $env:USERPROFILE "ATLAS\offline-chat-copilot")

    foreach ($path in $candidates) {
        if ($path -and (Test-Path (Join-Path $path "offline_copilot")) -and (Test-Path (Join-Path $path "rule_engine.py"))) {
            return (Resolve-Path $path).Path
        }
    }
    return $null
}

$root = Find-ProjectRoot
if (-not $root) {
    Write-Host @"
This folder is not the offline chat copilot.

Use the ATLAS git repo:

  cd $env:USERPROFILE\ATLAS
  git fetch origin
  git checkout cursor/offline-chat-copilot-7517
  git pull origin cursor/offline-chat-copilot-7517
  cd offline-chat-copilot
  powershell -ExecutionPolicy Bypass -File .\run.ps1

Open IX Browser yourself first (debug port 9222) and leave
https://chathomebase.com/chat/claimed on screen.
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

Write-Host "[Setup] Installing Python packages (IX attach)..."
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $venvPython -m pip install -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[Setup] Installing Playwright client (used only to attach to IX Browser)..."
& $venvPython -m playwright install chromium
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[Run] Attach to your already-open IX window. Do not close that window."
Write-Host "[Run] Target: https://chathomebase.com/chat/claimed"
& $venvPython -m offline_copilot attach @args
