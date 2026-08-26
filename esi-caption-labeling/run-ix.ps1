#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$env:ESI_BROWSER = "ix"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $here "run.ps1") @args
