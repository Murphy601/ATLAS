# Video Labeling Bot

Automated video timestamping and action-labeling pipeline for the [Atlas Capture audit portal](https://audit.atlascapture.io/).

```
[Atlas portal video player]
    -> Playwright screenshots (1 fps)
    -> GPT-4o labels
    -> sanitize rules
    -> fill input[aria-label="Segment N label"]
    -> you review, then Submit/Next
```

## Atlas wiring

- Portal: `https://audit.atlascapture.io/`
- Label fields: `input[aria-label="Segment 1 label"]` (also `data-segment-start-seconds`)
- Timestamps live on each pre-rendered row, not in separate start/end boxes
- Frames come from the in-page `<video>` element. No `input_video.mp4` required
- Login is manual on the first headed run; cookies persist in `./browser_session`
- Submit mode is review-then-submit (`AUTO_SUBMIT=false`)

## Setup

```bash
cd video-labeling-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Put your OpenAI key in `.env`. Keep `PORTAL_URL=https://audit.atlascapture.io/`.

## Run

```bash
python main.py
```

1. Chromium opens the Atlas login page (headed, persistent profile).
2. Log in and open a labeling task until Segment 1 is visible.
3. The bot plays/pauses the in-page video, screenshots 1s frames per 3s segment, and fills each label input.
4. Inspect the filled labels, then press ENTER to click Submit/Next.

Useful flags:

```bash
python main.py --url https://audit.atlascapture.io/
python main.py --video path/to/optional.mp4   # local fallback only
```

Do not use `--auto-submit` until you have verified labels; Atlas audit score depends on accuracy.

## Still needed

Paste the **Submit** or **Next** button HTML from the task page (`Ctrl+Shift+C`) if the generic `Submit`/`Next` selector does not hit the real control.

## Tests

```bash
cd video-labeling-bot
python -m pytest -q
```
