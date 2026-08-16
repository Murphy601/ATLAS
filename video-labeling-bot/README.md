# Video Labeling Bot

Automated video timestamping and action-labeling pipeline for web-based annotation platforms.

```
[Web/App Interface] ---> 1. Frame Extraction (CV2/FFmpeg)
                     ---> 2. VLM Inference (GPT-4o / Qwen2-VL)
                     ---> 3. Post-Processing Filter (Regex & Rules)
                     ---> 4. Web UI Automation (Playwright)
```

## Phase 1 — Project structure

```
video-labeling-bot/
  .env                 # API credentials (gitignored; copy from .env.example)
  config.py            # Annotation rules, forbidden words, system prompt
  frame_extractor.py   # Keyframe extraction from local video
  label_generator.py   # VLM inference + sanitization
  browser_automation.py
  main.py              # End-to-end orchestrator
```

## Setup

```bash
cd video-labeling-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Add your OpenAI API key to `.env`:

```env
OPENAI_API_KEY="your-actual-api-key-here"
```

Place a test MP4 named `input_video.mp4` in this folder.

## Run

```bash
python main.py
```

Useful flags:

```bash
python main.py --video input_video.mp4 --url https://your-portal.example --headless
python main.py --skip-browser --video input_video.mp4
python main.py --auto-submit
```

`AUTO_SUBMIT` defaults to false so you can review filled fields before submit.

## Annotation rules

Labels are hand-object contact only, imperative voice, no subject nouns, no digits, no trailing period. Idle or no-contact frames become `No Action` and are not written to the UI.

## Tests

```bash
cd video-labeling-bot
python -m pytest -q
```
