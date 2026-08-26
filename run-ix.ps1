#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$env:ESI_BROWSER = "ix"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$inner = Join-Path $here "esi-caption-labeling\run-ix.ps1"
if (-not (Test-Path $inner)) {
    Write-Host "esi-caption-labeling is not on this branch. Checkout cursor/esi-caption-labeling-7517."
    exit 1
}
& $inner @args
