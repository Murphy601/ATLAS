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
- **pauses only after watching the first clips** (~24s from the start). It does not stop after 2 segments.
- **Play is confirmed by Pause on screen.** Playback stays at 1x: **Slow around transitions is turned off** so the video does not stall at clip cuts. The watch loop does not re-click Play (that pauses the clip). If Pause vanishes at the end of the video, Play is **not** clicked again.
- seeks Full Timeline using the bar (not the left-edge label) and the first Focused Timeline card so playback starts at 0s
- if Quality Assistant says missing hands / 10 words / format on an Idle clip, it **replaces Idle** with a 10+ word hand caption. It does **not** K-split that action into smaller Idle pieces
- splits Idle **over 5s** only when the clip is truly Idle (no action). Caption stays `Idle`. Never HTE
- switches the top **Sub-goal** dropdown to **ClipExport**, types **one** third-person kitchen sentence with **no hand/handling wording**, and clicks **Ignore** on the end-match warning. It does **not** K-split Clip Export. `Ignore all` is never clicked
- rewrites sub-goals that join actions with a **period** (`...left hand. Hold...` → `...left hand and hold...`)
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
- splits Idle **>5s** with **K** after Pause, at 45% of the Idle *card* (then 90% if the red remains)
- fills **Clip Export** by typing into the existing pending / Focus annotation field (no extra K when a clip already exists)
- never counts a guessed sidebar coordinate as a successful write

Look for `Review pass`, `Clicked UIA empty clip` / `Typed missing caption: Idle` / `Clicked UIA Review Use`. Grammar should count down (`Grammar 2 clips` → `1` → gone).
`--dry-run` plays and prints caption fixes without typing.
