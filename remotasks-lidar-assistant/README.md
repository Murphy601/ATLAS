# EGO annotation engine (IX Browser attach)

Local helper for the egocentric clipping/captioning tool. **It never launches Chrome.**
You open IX Browser, log in, and open the task. When the Focused Timeline is on screen
(Review, `ego_rectified_canonical`, Sub-goal, play control), the engine attaches and works that tab.

It encodes the project spec:

- Watch the **entire video first** (clicks Play / 1x, does not skip)
- Subgoals **< 10s**, Clip Export **< 5 min**, idle **> 5s** isolated
- Captions: imperative, named hand, `with` not `using`, `and` not `while`
- Forbidden verbs/adjectives, grammar cheat-sheet prepositions (`pick up … from`)
- **Does not touch** Hand Tracking Error autoflags
- **Does not click Submit**

## IX Browser (required)

1. In the IX profile: enable **debugging port** `9222` (Advanced / Other).
2. Start that profile yourself (this is your Chrome window).
3. Open the EGO task until you see **Focused Timeline** and the play control.
4. Then run the engine:

```powershell
cd remotasks-lidar-assistant
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe main.py
```

Optional: `$env:CDP_URL="http://127.0.0.1:9222"`

The Playwright Chromium install is only the client library talking over CDP. It will **not** open a second browser.

Lint without attaching:

```powershell
python main.py --lint-text "Pick up the pants on the table with the left hand"
python main.py --dry-run
```

`--dry-run` still plays the video and prints caption fixes, but does not type into the page.
