#Requires -Version 5.1
<#
.SYNOPSIS
  Run the offline chat copilot from the ATLAS repo root.

  If offline-chat-copilot is missing, you are on the wrong git branch.
#>

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$copilot = Join-Path $here "offline-chat-copilot\run.ps1"

if (-not (Test-Path $copilot)) {
    Write-Host @"
offline-chat-copilot is not on this branch.

Paste this (no git user.name needed):

  cd $env:USERPROFILE\ATLAS
  git fetch origin
  git checkout -B cursor/offline-chat-copilot-7517 origin/cursor/offline-chat-copilot-7517
  powershell -ExecutionPolicy Bypass -File .\run.ps1

Leave IX Browser open on https://chathomebase.com/chat/claimed first.
"@
    exit 1
}

& $copilot @args
