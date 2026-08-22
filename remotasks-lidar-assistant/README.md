# EGO annotation engine (IX Browser attach)

Local helper for the egocentric clipping/captioning tool. **It never launches Chrome.**
You open IX Browser, log in, and open the task. When the Focused Timeline is on screen
(Review, `ego_rectified_canonical`, Sub-goal, play control), the engine attaches and works that tab.

The bot is **not** a folder under `C:\Users\user`. It lives inside the ATLAS git repo:

`C:\Users\user\ATLAS\remotasks-lidar-assistant`

## First-time clone

```powershell
cd $env:USERPROFILE
git clone -b cursor/remotasks-lidar-assistant-7517 https://github.com/Murphy601/ATLAS.git
cd ATLAS\remotasks-lidar-assistant
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

If ATLAS is already cloned from the earlier bots:

```powershell
cd $env:USERPROFILE\ATLAS
git fetch origin
git checkout cursor/remotasks-lidar-assistant-7517
git pull origin cursor/remotasks-lidar-assistant-7517
cd remotasks-lidar-assistant
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

## IX Browser (required before run.ps1)

1. In the IX profile: enable **debugging port** `9222` (Advanced / Other).
2. Start that profile yourself and leave it open.
3. Open the EGO task until you see **Focused Timeline** and the play control.
4. Then run `run.ps1` in a second PowerShell window.

Optional: `$env:CDP_URL="http://127.0.0.1:9222"`

`--dry-run` plays and prints caption fixes without typing. `--lint-text` checks one caption.
