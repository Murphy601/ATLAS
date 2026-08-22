# EGO annotation engine (IX Browser attach)

Local helper for the egocentric clipping/captioning tool. **It never launches Chrome
and does not use IX Local API.** Open any IX profile yourself, open the task, then run
the engine. It finds that window from the running process and works the tab on screen.

The bot is **not** a folder under `C:\Users\user`. It lives inside the ATLAS git repo:

`C:\Users\user\ATLAS\remotasks-lidar-assistant`

## Run

```powershell
cd $env:USERPROFILE\ATLAS
git pull origin cursor/remotasks-lidar-assistant-7517
cd remotasks-lidar-assistant
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

1. Open any IX profile yourself.
2. Open the EGO task until you see **Focused Timeline**.
3. Run `run.ps1` in a second PowerShell window. Leave IX open.

`--dry-run` plays and prints caption fixes without typing.
