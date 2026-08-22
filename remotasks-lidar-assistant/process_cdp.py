"""Find the debug port of an already-open IX/Chrome window. No Local API required."""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from pathlib import Path

logger = logging.getLogger("ego.process_cdp")

BROWSER_NAMES = {
    "chrome.exe",
    "chromium.exe",
    "msedge.exe",
    "ixbrowser.exe",
    "ixbrowser",
    "chrome",
    "chromium",
}

IX_PATH_MARKERS = ("ixbrowser", "ix-browser", "/ix browser/", "\\ix browser\\")
STOCK_CHROME_MARKERS = (
    "/google/chrome/",
    "/google/chrome beta/",
    "/microsoft/edge/",
    "/brave software/",
)

PORT_RE = re.compile(r"--remote-debugging-port(?:=|\s+)(\d+)", re.I)
USER_DIR_RE = re.compile(r'--user-data-dir(?:=|\s+)(?:"([^"]+)"|(\S+))', re.I)


def parse_debug_port(command_line: str) -> int | None:
    match = PORT_RE.search(command_line or "")
    if not match:
        return None
    port = int(match.group(1))
    return port if port > 0 else None


def parse_user_data_dir(command_line: str) -> str | None:
    match = USER_DIR_RE.search(command_line or "")
    if not match:
        return None
    return match.group(1) or match.group(2)


def read_devtools_active_port(user_data_dir: str | Path) -> int | None:
    path = Path(user_data_dir) / "DevToolsActivePort"
    if not path.is_file():
        return None
    try:
        first = path.read_text(encoding="utf-8", errors="replace").splitlines()[0].strip()
        port = int(first)
        return port if port > 0 else None
    except (OSError, ValueError):
        return None


def command_line_cdp_urls(command_line: str) -> list[str]:
    urls: list[str] = []
    port = parse_debug_port(command_line)
    if port:
        urls.append(f"http://127.0.0.1:{port}")
    user_dir = parse_user_data_dir(command_line)
    if user_dir:
        file_port = read_devtools_active_port(user_dir)
        if file_port:
            urls.append(f"http://127.0.0.1:{file_port}")
    return urls


def is_browser_process(name: str | None, command_line: str | None) -> bool:
    lowered = (name or "").lower()
    if lowered in BROWSER_NAMES or lowered.endswith("chrome.exe"):
        return True
    cmd = (command_line or "").lower()
    return "ixbrowser" in cmd or "chrome.exe" in cmd or "chromium" in cmd


def _norm_path(value: str | None) -> str:
    return (value or "").lower().replace("\\", "/")


def is_ix_install(
    name: str | None = None,
    command_line: str | None = None,
    exe_path: str | None = None,
) -> bool:
    """True for IX Browser (including chrome.exe launched from the IX install folder)."""
    blob = " ".join(part for part in (name, command_line, exe_path) if part)
    lowered = _norm_path(blob)
    return any(marker.replace("\\", "/") in lowered for marker in IX_PATH_MARKERS)


def is_stock_chrome_path(exe_path: str | None) -> bool:
    lowered = _norm_path(exe_path)
    return any(marker in lowered for marker in STOCK_CHROME_MARKERS)


def probe_devtools(url: str, timeout: float = 0.6) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/json/version", timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        return "webSocketDebuggerUrl" in payload or "Browser" in payload
    except Exception:
        return False


def _candidate_http_urls() -> list[str]:
    """Listen ports and --remote-debugging-port values from IX/Chrome processes."""
    found: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        if url not in seen:
            seen.add(url)
            found.append(url)

    try:
        import psutil
    except ImportError:
        return found

    for proc in psutil.process_iter(["pid", "name", "cmdline", "exe"]):
        try:
            info = proc.info
            cmdline_list = info.get("cmdline") or []
            cmd = " ".join(str(part) for part in cmdline_list)
            name = info.get("name") or ""
            exe = info.get("exe") or ""
            if not is_ix_install(name, cmd, exe):
                continue
            for url in command_line_cdp_urls(cmd):
                add(url)
            try:
                for conn in proc.net_connections(kind="inet"):
                    if getattr(conn, "status", "") != "LISTEN":
                        continue
                    laddr = getattr(conn, "laddr", None)
                    port = getattr(laddr, "port", None) if laddr is not None else None
                    if port:
                        add(f"http://127.0.0.1:{port}")
            except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError):
                continue
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return found


def discover_cdp_http_urls() -> list[str]:
    """Return only endpoints that currently answer /json/version (live DevTools)."""
    found = _candidate_http_urls()
    live = [url for url in found if probe_devtools(url)]
    if live:
        logger.info("Found live DevTools on %s", live)
        return live
    if not found:
        logger.info("No IX Browser debug port (Google Chrome listen ports are ignored)")
    else:
        logger.info("No live DevTools endpoint (ignored non-DevTools ports: %s)", found)
    return []
