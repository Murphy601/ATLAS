#Requires -Version 5.1
<#
.SYNOPSIS
  Set up (if needed) and attach the EGO engine to your already-open IX Browser tab.

.EXAMPLE
  cd $env:USERPROFILE\ATLAS\remotasks-lidar-assistant
  powershell -ExecutionPolicy Bypass -File .\run.ps1
#>

$ErrorActionPreference = "Stop"

function Find-ProjectRoot {
    $candidates = @()
    $here = (Get-Location).Path
    $candidates += $here
    $candidates += (Join-Path $here "remotasks-lidar-assistant")
    $candidates += (Join-Path $here "ATLAS\remotasks-lidar-assistant")
    $candidates += (Join-Path $env:USERPROFILE "ATLAS\remotasks-lidar-assistant")

    foreach ($path in $candidates) {
        if ($path -and (Test-Path (Join-Path $path "main.py")) -and (Test-Path (Join-Path $path "ego_task.py"))) {
            return (Resolve-Path $path).Path
        }
    }
    return $null
}

$root = Find-ProjectRoot
if (-not $root) {
    Write-Host @"
This folder is not the EGO engine.

The bot is NOT C:\Users\user\remotasks-lidar-assistant
It lives inside the ATLAS git repo. Use this:

  cd $env:USERPROFILE
  git clone -b cursor/remotasks-lidar-assistant-7517 https://github.com/Murphy601/ATLAS.git
  cd ATLAS\remotasks-lidar-assistant
  powershell -ExecutionPolicy Bypass -File .\run.ps1

If you already cloned ATLAS for the earlier bots:

  cd $env:USERPROFILE\ATLAS
  git fetch origin
  git checkout cursor/remotasks-lidar-assistant-7517
  git pull origin cursor/remotasks-lidar-assistant-7517
  cd remotasks-lidar-assistant
  powershell -ExecutionPolicy Bypass -File .\run.ps1

Open IX Browser yourself first (debug port 9222) and leave the EGO task on screen.
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
& python -c "import sys; print('[Setup] Python ' + sys.version.split()[0])"

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

Write-Host "[Setup] Installing Python packages (EGO attach; Open3D is not required)..."
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $venvPython -m pip install -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[Setup] Installing Playwright client (used only to attach to IX Browser)..."
& $venvPython -m playwright install chromium
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$envFile = Join-Path $root ".env"
$example = Join-Path $root ".env.example"
if (-not (Test-Path $envFile) -and (Test-Path $example)) {
    Copy-Item $example $envFile
}

Write-Host "[Run] Attach to your open IX Browser task. Do not close that window."
Write-Host "[Run] Enable IX Local API (Settings -> Local API, port 53200), then reopen the profile if needed."
& $venvPython (Join-Path $root "main.py") @args
