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

1. Open any **IX Browser** profile yourself (not Google Chrome, not Gemini).
2. Open the EGO task until you see **Focused Timeline**.
3. Run `run.ps1` in a second PowerShell window. Leave the IX window visible.

The engine ignores Google Chrome / Gemini tabs. If both are open, it drives the IX
process (`...\IXBrowser\...\chrome.exe`), not `Google\Chrome\Application\chrome.exe`.

Most IX profiles do **not** expose DevTools. In that case the engine stops scanning
ports (it will **not** sit on `127.0.0.1:38607` for minutes) and instead:

- brings the **IX** window to the front (not Google Chrome / Gemini)
- clicks the **video** in the page (below the Chromium tab strip), then Space once
- watches at 1x (player clock if visible, otherwise ~90s)
- reads timeline captions via Windows accessibility and types lint fixes

You should see a click like `Clicked video-center at 525,367` (y much larger than 50).
A click at y=49 is the tab bar and will not play the video.

You should see the IX window come forward and the video start. Caption typing into
the page still needs readable timeline text; suggested caption fixes are printed
even when the engine cannot type them.

`--dry-run` plays and prints caption fixes without typing.
