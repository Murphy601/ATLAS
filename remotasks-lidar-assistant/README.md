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

1. Click **Open** on the IX profile so **SensorFusionLab** Chromium is visible
   (not the profile list / Edit Notes dashboard).
2. Open the EGO task until you see **Focused Timeline**.
3. Run `run.ps1` in a second PowerShell window. Leave the Chromium task window visible.

The engine ignores Google Chrome / Gemini tabs. If both are open, it drives the IX
process (`...\IXBrowser\...\chrome.exe`), not `Google\Chrome\Application\chrome.exe`.

Most IX profiles do **not** expose DevTools. In that case the engine stops scanning
ports (it will **not** sit on `127.0.0.1:38607` for minutes) and instead:

- brings the **IX** window to the front (not Google Chrome / Gemini)
- clicks the **video** in the page (below the Chromium tab strip), then Space once
- watches at 1x (player clock if visible, otherwise ~90s). **Play is always clicked** when that button is on screen, even if Watched already shows 100%
- clicks **Use** on Review Grammar cards for red clips (Ignore/Submit are never clicked)
- splits Idle **over 5s** by placing the playhead in that subgoal and pressing **K** (`click or press K to create`). Caption stays `Idle`. Never HTE
- switches the top **Sub-goal** dropdown to **Clip Export** and types 1–2 environment sentences so Clip Export is filled in parallel with sub-goals
- clicks **click to add text** on empty timeline clips and types a caption (Idle when the action is unknown)

You should see a click like `Clicked video-center at 525,367` (y much larger than 50).
A click at y=49 is the tab bar and will not play the video.

You should see the IX window come forward. After play, the engine must fill empty
timeline cards (`click to add text` → `Idle`) and click Review **Use**. A log that
only shows `Watching video... 90/90s` then `Filled 0 missing/red caption(s)` and
`OCR words: 0` did **not** write captions — Chromium PrintWindow captures are blank,
so the engine now:

- reads the Chromium accessibility tree (same path that already found **Play**)
- captures the real on-screen pixels (desktop BitBlt / screenshot), not PrintWindow
- clicks **Use** on each remaining Grammar clip (opens the Grammar row when Use hides)
- splits Idle **>5s** with **K** (PDF clipping rule; Quality Assistant "no idle more than 5s")
- fills **Clip Export** on its own timeline (1–2 sentences, environment + task, never HTE)
- never counts a guessed sidebar coordinate as a successful write

Look for `Review pass`, `Clicked UIA empty clip` / `Typed missing caption: Idle` / `Clicked UIA Review Use`. Grammar should count down (`Grammar 2 clips` → `1` → gone).
`--dry-run` plays and prints caption fixes without typing.
