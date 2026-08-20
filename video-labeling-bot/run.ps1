#Requires -Version 5.1
<#
.SYNOPSIS
  Set up (if needed) and run the Atlas video-labeling bot on Windows.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\run.ps1
#>

$ErrorActionPreference = "Stop"

function Find-ProjectRoot {
    $here = Get-Location
    if (Test-Path (Join-Path $here "main.py")) {
        return $here
    }
    $nested = Join-Path $here "video-labeling-bot"
    if (Test-Path (Join-Path $nested "main.py")) {
        return (Resolve-Path $nested)
    }
    return $null
}

$root = Find-ProjectRoot
if (-not $root) {
    Write-Host @"
This folder is not the bot project.

In PowerShell, clone the ATLAS repo first (the bot lives inside it):

  cd $env:USERPROFILE
  git clone -b cursor/video-labeling-bot-ddb9 https://github.com/Murphy601/ATLAS.git
  cd ATLAS\video-labeling-bot
  powershell -ExecutionPolicy Bypass -File .\run.ps1

Do not run:  cd video-labeling-bot
from C:\Users\user unless you already cloned the repo there.
"@
    exit 1
}

Set-Location $root
Write-Host "[Setup] Project: $root"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python was not found. Install Python 3.12+ from https://www.python.org/downloads/"
    Write-Host "During setup, enable 'Add python.exe to PATH'."
    exit 1
}

$venvPython = Join-Path $root "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "[Setup] Creating virtual environment..."
    python -m venv venv
}

$venvPython = Join-Path $root "venv\Scripts\python.exe"
Write-Host "[Setup] Installing Python packages..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $root "requirements.txt")

Write-Host "[Setup] Installing Playwright Chromium..."
& $venvPython -m playwright install chromium

$envFile = Join-Path $root ".env"
$example = Join-Path $root ".env.example"
if (-not (Test-Path $envFile)) {
    Copy-Item $example $envFile
    Write-Host "[Setup] Created .env from .env.example. Put your OPENROUTER_API_KEY in that file, then re-run."
    notepad $envFile
    exit 0
}

$envText = Get-Content $envFile -Raw
if ($envText -match "your-actual-api-key-here") {
    Write-Host "[Setup] OPENROUTER_API_KEY is still a placeholder."
    Write-Host "Edit $envFile, paste your OpenRouter key, save, then re-run this script."
    notepad $envFile
    exit 0
}

Write-Host "[Run] Starting Atlas labeling bot (headed Chrome). Log in, then open a practice clip."
& $venvPython (Join-Path $root "main.py") @args
