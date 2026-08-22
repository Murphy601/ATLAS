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


def probe_devtools(url: str, timeout: float = 0.6) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/json/version", timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        return "webSocketDebuggerUrl" in payload or "Browser" in payload
    except Exception:
        return False


def discover_cdp_http_urls() -> list[str]:
    """Inspect running IX/Chrome processes. Does not open a profile and does not use Local API."""
    found: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        if url not in seen:
            seen.add(url)
            found.append(url)

    try:
        import psutil
    except ImportError:
        psutil = None  # type: ignore[assignment]

    if psutil is not None:
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                info = proc.info
                cmdline_list = info.get("cmdline") or []
                cmd = " ".join(str(part) for part in cmdline_list)
                name = info.get("name") or ""
                if not is_browser_process(name, cmd):
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

    live = [url for url in found if probe_devtools(url)]
    if live:
        logger.info("Found live DevTools on %s", live)
        return live
    logger.info("Process scan candidate URLs: %s", found)
    return found
