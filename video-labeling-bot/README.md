# Video Labeling Bot

Automated video timestamping and action-labeling pipeline for the [Atlas Capture audit portal](https://audit.atlascapture.io/).

```
[Atlas portal video player]
    -> Playwright screenshots (1 fps)
    -> OpenRouter free VLMs (with fallbacks)
    -> Atlas Standard Text Annotation Rules
    -> fill input[aria-label="Segment N label"]
    -> you review, then "Submit practice clip"
```

## Atlas wiring

- Portal: `https://audit.atlascapture.io/`
- Label fields: `input[aria-label="Segment 1 label"]` (also `data-segment-start-seconds`)
- Submit: `button:has-text("Submit practice clip")`, fallback `button[data-slot="button"]:has-text("Submit")`
- Frames come from the in-page `<video>` element. No `input_video.mp4` required
- Login is manual on the first headed run; cookies persist in `./browser_session`
- Submit mode is review-then-submit (`AUTO_SUBMIT=false`)

## Models

OpenRouter free vision models, tried in order:

1. `qwen/qwen-2-vl-7b-instruct:free`
2. `google/gemini-2.5-flash:free`
3. `google/gemini-2.0-flash-exp:free`
4. `meta-llama/llama-3.2-11b-vision-instruct:free`
5. `mistralai/pixtral-12b:free`
6. `qwen/qwen-2.5-vl-72b-instruct:free`
7. `openrouter/auto`

Set `OPENROUTER_API_KEY` in `.env`. Do not commit that file.

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
3. The bot screenshots 1s frames per 3s segment and fills each label input.
4. Inspect the filled labels, then press ENTER to click **Submit practice clip**.

## Tests

```bash
cd video-labeling-bot
python -m pytest -q
```
