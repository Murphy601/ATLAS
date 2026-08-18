# Atlas Hybrid Annotator

**Non-LLM / hybrid pipeline** for Atlas Capture labels: classical computer vision (MediaPipe hands), cross-segment state memory, and deterministic regex linting.

This bot is **fully separate** from [`video-labeling-bot/`](../video-labeling-bot/README.md) (the Playwright + OpenRouter vision pipeline). They do not share code, venv, or browser sessions.

## Strategy

| Layer | What it does |
|---|---|
| **MediaPipe Hands** | Wrist velocity → `with left hand` / `with right hand` / `with both hands` |
| **Frame-0 contact** | Wrist visible at segment start → prefer `hold` over `pick up` |
| **State memory** | JSON-like dict across segments: if Segment 1 held `wrench`, Segment 2 rewrites `pick up wrench` → `hold wrench` |
| **Regex linter** | Lexicon lock, `-ing` → imperative, strip `and`/`then`, duration clause cap (<3.5s = 1 clause) |

No API keys. Runs on CPU.

## Setup (Windows)

```powershell
cd $env:USERPROFILE\ATLAS\atlas-hybrid-bot
python -m venv venv
.\venv\Scripts\pip.exe install -r requirements.txt
copy .env.example .env
```

## Quick demo (no video, no MediaPipe motion)

```powershell
.\venv\Scripts\python.exe main.py --demo
```

## Process a local video + segment JSON

`segments.json`:

```json
[
  {"start": 0.0, "end": 2.5, "draft": "picking up blue package and clothes", "object": "glass cleaner pouch"},
  {"start": 2.5, "end": 6.0, "draft": "pick up blue package then wipe table", "object": "glass cleaner pouch"}
]
```

```powershell
.\venv\Scripts\python.exe main.py --video clip.mp4 --segments segments.json
```

## In-memory frames (browser integration pattern)

Export base64 JPEGs from your capture step, then:

```powershell
.\venv\Scripts\python.exe main.py --frames-json frames.json --segments segments.json
```

`frames.json`: `{"frames": ["<base64>", "..."]}`

## Python API

```python
from hybrid_annotator import AtlasHybridPipeline
from frame_utils import frames_from_base64_list

pipeline = AtlasHybridPipeline()
frames = frames_from_base64_list(segment_jpegs_base64)
label = pipeline.process_frame_batch(
    frames,
    start_sec=0.0,
    end_sec=2.8,
    draft_label="picking up blue package and clothes",
    target_object="glass cleaner pouch",
)
pipeline.close()
```

## vs LLM bot

| | `atlas-hybrid-bot` | `video-labeling-bot` |
|---|---|---|
| Vision | MediaPipe (local) | OpenRouter VLMs |
| Cost | Free | API usage |
| Best for | Hand/state/taxonomy rules | Complex scene understanding |
| Browser | Manual / export frames | Full Playwright automation |

You can run **hybrid first** on drafts, then send hard segments to the LLM bot — keep them in separate folders and venvs.

## Tests

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

## Env

| Variable | Default | Purpose |
|---|---|---|
| `EGO_SWAP_HANDS` | `true` | Swap MediaPipe L/R for ego camera |
| `HAND_MOTION_THRESHOLD` | `0.015` | Wrist velocity threshold |
