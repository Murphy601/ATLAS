# Atlas Hybrid Bot

**Full browser automation + non-LLM labeling** for Atlas Capture: Playwright opens Atlas, watches segment clips, captures frames, and fills labels using **MediaPipe hand tracking**, **cross-segment state memory**, and the **same deterministic post-processing** as the LLM bot — **without any OpenRouter / vision API calls**.

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
5. Run **MediaPipe** wrist velocity → hand tag
6. Apply **regex linter**, draft noun lock, verb-state, duration caps (from `label_generator.py`)
7. Fill each segment label and wait for you to review/submit

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

## Architecture

```
main.py
  └─ VideoBrowserBot (browser_automation.py)  ← Playwright, capture, fill, submit
  └─ generate_label_hybrid (label_pipeline.py)
       ├─ AtlasHybridPipeline (hybrid_annotator.py)  ← MediaPipe + state memory
       └─ finalize_pipeline_label (label_generator.py)  ← draft surgery, lint, caps
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

## vs LLM bot

| | `atlas-hybrid-bot` | `video-labeling-bot` |
|---|---|---|
| Browser automation | Yes | Yes |
| MediaPipe hands | Yes | No |
| Vision LLM | **No** | Yes (OpenRouter) |
| API key | Not required | Required |
| Object names | From Atlas AI draft | Draft + vision override |

Object identification comes from the **pre-filled Atlas draft** on each row; MediaPipe only picks the active hand and pick-up vs hold corrections.
