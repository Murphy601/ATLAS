# Remotasks LiDAR Assistant

Local annotation helper for WebGL / LiDAR Lite tasks. It never injects JavaScript into the task page. Instead it:

1. Opens Remotasks in a **persistent Playwright Chrome profile** so you can log in once.
2. Intercepts `.pcd` / `.bin` / point-cloud network payloads and saves them under `debug_captures/`.
3. Runs **Open3D** ground removal + DBSCAN clustering and prints oriented cuboids `(x, y, z, dx, dy, dz, theta)`.
4. Serves a **localhost-only** Flask + Three.js overlay of those boxes.

```text
remotasks-lidar-assistant/
├── config.py
├── main.py
├── browser_engine.py
├── pcd_parser.py
├── overlay.py
├── debug_captures/
└── requirements.txt
```

## Setup

```bash
cd remotasks-lidar-assistant
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

On Windows PowerShell:

```powershell
cd remotasks-lidar-assistant
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

## Run

```bash
python main.py
```

1. Complete login / 2FA in the Playwright window.
2. Open a LiDAR Lite task.
3. Watch cuboid JSON in the terminal and at `http://127.0.0.1:8765`.

Analyze a captured file without the browser:

```bash
python main.py --analyze-only debug_captures/latest_frame.pcd --no-overlay
```

## Tests

```bash
python -m pytest -q
```
