# ESI caption labeling

Hierarchical egocentric video caption bot for [MultiMango ESI caption labeling](https://www.multimango.com/tasks/vs-1781285808-260612-esi-caption-labeling).

Same attach model as the Remotasks EGO engine: **you** open the IX or MoreLogin profile and the task. The bot never launches Chrome and does not use a Local API. Debug port 9222 is optional — if DevTools is off it drives the window from the desktop.

## Two commands

IX Browser (SensorFusionLab Chromium, not the `ixBrowser | v2.9.20` manager):

```powershell
cd $env:USERPROFILE\ATLAS
git fetch origin
git checkout -B cursor/esi-caption-labeling-7517 origin/cursor/esi-caption-labeling-7517
powershell -ExecutionPolicy Bypass -File .\run-ix.ps1
```

MoreLogin (the open profile Chromium, not the MoreLogin manager):

```powershell
cd $env:USERPROFILE\ATLAS
git fetch origin
git checkout -B cursor/esi-caption-labeling-7517 origin/cursor/esi-caption-labeling-7517
powershell -ExecutionPolicy Bypass -File .\run-morelogin.ps1
```

Fill fields but do not click Submit:

```powershell
powershell -ExecutionPolicy Bypass -File .\run-ix.ps1 --no-submit
powershell -ExecutionPolicy Bypass -File .\run-morelogin.ps1 --no-submit
```

## What it does

1. Attaches to the already-open profile you named (IX **or** MoreLogin).
2. Leaves Google Chrome, Gmail, and the profile-manager windows alone.
3. Watches the clip at **1x** (required before submit).
4. Labels **L3 → L2 → L1**:
   - L3 atomic actions (hand, Action, Object + tool, Target or skip, Idle if both hands still >2s)
   - L2 object-centric segments (Result Success/Fail + retries)
   - L1 Environment + episode caption
5. Clicks **Generate with AI**, then corrects the caption (lowercase, no period, always “hand”, never “gripper”).
6. Clicks **Submit Captions** only when the red issues box is gone.
7. Never clicks Skip, Flag bad video, or Flag for removal.

Captions stay unique. Pick and place are two L3s. Reaching is part of pick; retracting is part of place. Idle spans have no fields.

## Operator setup

1. Click **Open** on the IX profile **or** the MoreLogin profile so Chromium is visible.
2. Open https://www.multimango.com/tasks/vs-1781285808-260612-esi-caption-labeling (login yourself).
3. Run **one** of the two commands above in a second PowerShell window.
4. Leave that Chromium window on the labeling page.

The bot ignores the tiny 158×26 title stub and Handshake AI. It maximizes the large Chromium window, pauses the video, then clicks each empty **A1 / action (empty)** card on the right and fills it. It does not press `3` on a playing timeline.

Python 3.12 on PATH. First run creates `venv` and installs packages.
