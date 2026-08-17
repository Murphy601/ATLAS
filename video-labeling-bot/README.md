# Video Labeling Bot

Automated video timestamping and action-labeling pipeline for the [Atlas Capture audit portal](https://audit.atlascapture.io/).

```
[Atlas portal video player]
    -> Playwright screenshots (start→end, 5–10 frames)
    -> OpenRouter vision models (Gemini Flash, then fallbacks)
    -> Atlas Standard Text Annotation Rules
    -> fill input[aria-label="Segment N label"]
    -> you review, then "Submit practice clip"
    -> Next task (you click it, or the bot does) -> next clip, repeat
```

## Atlas wiring

- Portal: `https://audit.atlascapture.io/`
- After login: sidebar **Tasks** → **Continue Assessment Practice** (or **Review** on a listed live task)
- Segments already exist with AI drafts. The bot **replaces the text**, it does not delete rows or retimestamp.
- Atlas drafts are **untrusted** and are not sent to the vision model. If every model still says No Action, the bot keeps the draft and rewrites bare `animal` to `stuffed animal` instead of filling No Action.
- Frames are the **painted player** (page screenshot). A raw `<video>` screenshot is often a black GPU frame, which made every model say No Action.
- Label fields: `input[aria-label="Segment 1 label"]`
- Submit: `button:has-text("Submit practice clip")`, fallback Complete / Submit assessment
- After submit the bot **stays in the Chrome session** and starts the next clip when **Next task** / **Next video** appears
- **Leave the Chrome window open** and visible. Ctrl+C should not dump a Playwright traceback.
- Frames come from the in-page player. No `input_video.mp4` required
- Login is manual on the first headed run; cookies persist in `./browser_session`
- Submit mode is review-then-submit (`AUTO_SUBMIT=false`). Press Ctrl+C when you want to stop the queue

## Models

OpenRouter paid vision models, Gemini first:

1. `google/gemini-2.5-flash` (default)
2. `openai/gpt-4o-mini`
3. `anthropic/claude-sonnet-5` (`anthropic/claude-3.5-sonnet` is not on OpenRouter)
4. `qwen/qwen2.5-vl-72b-instruct`

`No Action` in a segment field is ignored (it is leftover from a previous run, not a real Atlas draft). The bot tries the next model whenever one says No Action, then retries once as hand work.

Frames are copied from the decoded `<video>` onto a canvas after a short wait so the JPEG is not a black GPU bitmap.

Optional override in `.env`: `VISION_MODEL=openai/gpt-4o-mini`

Set `OPENROUTER_API_KEY` in `.env`. Do not commit that file. These models are billed on OpenRouter.

## Windows (PowerShell)

The bot is **not** a folder under `C:\Users\user`. It lives inside the ATLAS git repo.

`source venv/bin/activate` is Linux/macOS only. On Windows use `.\venv\Scripts\Activate.ps1`.

```powershell
cd $env:USERPROFILE
git clone -b cursor/video-labeling-bot-ddb9 https://github.com/Murphy601/ATLAS.git
cd ATLAS\video-labeling-bot
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

That script creates `venv`, installs packages, and starts `main.py` in **your installed Google Chrome**.

Playwright's test Chromium is what triggers Cloudflare Turnstile (`Verification failed`). If you already saw that, delete the old session and pull this fix:

```powershell
cd $env:USERPROFILE\ATLAS\video-labeling-bot
Remove-Item -Recurse -Force .\browser_session -ErrorAction SilentlyContinue
git pull
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Log in in the Chrome window that opens. After one successful login, cookies stay in `browser_session`.

Manual equivalent:

```powershell
cd $env:USERPROFILE\ATLAS\video-labeling-bot
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
notepad .env
python main.py
```

If `Activate.ps1` is blocked:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Or skip activation and call the venv Python directly:

```powershell
.\venv\Scripts\python.exe main.py
```

## macOS / Linux

```bash
git clone -b cursor/video-labeling-bot-ddb9 https://github.com/Murphy601/ATLAS.git
cd ATLAS/video-labeling-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
python main.py
```

1. Chromium opens the Atlas login page (headed, persistent profile).
2. Log in and open a labeling task until Segment 1 is visible.
3. The bot screenshots 5–10 frames per segment (start through end) and fills each label input.
4. Inspect the filled labels, then press ENTER to click **Submit practice clip**.
5. Click **Next task** (or wait — the bot clicks it). It labels the next clip instead of exiting. Ctrl+C to stop.

## Tests

```bash
cd video-labeling-bot
python -m pytest -q
```
