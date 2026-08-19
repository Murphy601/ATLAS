# Atlas Hybrid Bot

**Full browser automation + official ATLAS guide labeling** for Atlas Capture: preserves bimanual actions (hold + work), enforces syntax rules from the annotation guide, and never calls vision LLMs.

Sibling project: [`video-labeling-bot/`](../video-labeling-bot/README.md) (same browser flow, but uses vision LLMs).

## What runs when you start it

```powershell
cd $env:USERPROFILE\ATLAS\atlas-hybrid-bot
git pull
python -m venv venv
.\venv\Scripts\pip.exe install -r requirements.txt
.\venv\Scripts\playwright.exe install chromium
copy .env.example .env
.\venv\Scripts\python.exe main.py
```

This will:

1. Open Chrome (persistent `./browser_session` — log in once)
2. Navigate to **Practice assessment** (or graded, via `--mode`)
3. Play each segment clip at 1× speed and capture frames
4. Read the **Atlas AI draft** from each row input
5. **Guide linter**: up to 3 actions, off-hand hold, place+location, tool syntax, no articles/digits
6. Fill each segment label and wait for you to review/submit

No API key needed.

## CLI flags (same as LLM bot)

| Flag | Purpose |
|---|---|
| `--mode practice` | Training Practice assessment (default) |
| `--mode assessment` | Graded 70% test |
| `--mode auto` | Practice first, then graded |
| `--auto-submit` | Submit without review pause |
| `--headless` | Headless capture (needs prior login cookies) |
| `--video clip.mp4` | Local file fallback instead of live player |
| `--skip-browser` | Print labels from `--video` only |
| `--demo` | Regex/state demo in terminal (no browser) |

## Official guide rules (implemented)

| Rule | What the bot does |
|---|---|
| Bimanual / off-hand hold | Keeps up to **3** clauses from the draft — e.g. `hold bowl with left hand, scrub bowl with sponge in right hand` |
| `place` needs location | Keeps location when the draft includes it; does not invent locations |
| Tool syntax | Preserves `with [tool] in [hand]`; fixes broken `with [tool] with [hand]` |
| Draft verbs | Keeps `smooth` and other imperatives; does not rewrite to `smoothen` |
| Off-hand stabilize | Adds `hold [object] in left hand` when draft names one working hand on cloth/dish work |
| Plural nouns | Keeps `papers` when draft or prior segment uses plural |
| Hand attribution | Splits false `both hands` bimanual clauses; motion corrects single-hand dominance |
| No articles / digits | Strips `the`, `a`, `an`; spells out numbers |
| Banned verbs | `adjust`→`shift`, `grab`→`pick up` |
| Plural tools | `scissors`, `tongs`, `pliers` always plural |
| Hand-state carryover | `pick up`→`hold` only if prior segment ended holding same object; never `hold`→`pick up` |
| Draft trust | No noun swaps, fake off-hand holds, or location injection |

## Architecture

```
main.py
  └─ VideoBrowserBot (browser_automation.py)
  └─ generate_label_hybrid (label_pipeline.py)
       └─ draft_preserving_cleaner → safe syntax only (no sanitize_label surgery)
```

## Env

| Variable | Default | Purpose |
|---|---|---|
| `EGO_SWAP_HANDS` | `true` | Swap L/R for ego camera |
| `HAND_MOTION_THRESHOLD` | `0.015` | Wrist motion sensitivity |
| `ATLAS_LABEL_MODE` | `practice` | Which Atlas flow to open |
| `AUTO_SUBMIT` | `false` | Skip review pause |
| `PORTAL_URL` | audit.atlascapture.io | Portal URL |

## Tests

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

## Troubleshooting

### `module 'mediapipe' has no attribute 'solutions'`

You have MediaPipe **1.0+** (normal on Python 3.14). The bot auto-downloads the hand model on first run and uses the **Tasks API**. On first segment you may see:

```
[Hybrid]: Downloading MediaPipe hand model (~7.5 MB)...
```

If hand tracking still fails, the bot falls back to **regex + draft hand tags** (e.g. `in both hands` from the Atlas draft).

### Tab keeps refreshing before the editor opens

Wait for login to finish. The bot retries `/tasks` at most every 8 seconds. Once segment rows appear, it stops navigating and plays each clip.

### Python version

- **Python 3.14**: uses `mediapipe>=1.0` (Tasks API)
- **Python 3.10–3.12**: either version works

## vs LLM bot

| | `atlas-hybrid-bot` | `video-labeling-bot` |
|---|---|---|
| Browser automation | Yes | Yes |
| MediaPipe hands | Yes | No |
| Vision LLM | **No** | Yes (OpenRouter) |
| API key | Not required | Required |
| Object names | From Atlas AI draft | Draft + vision override |

Object identification comes from the **pre-filled Atlas draft**; MediaPipe is only a hand-tag fallback when the draft omits hands.
