"""Find DevTools on an already-open IX Browser profile. Never launches Chrome."""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from pathlib import Path

logger = logging.getLogger("copilot.ix_cdp")

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

CLAIMED_URL = "https://chathomebase.com/chat/claimed"
SITE_HOST = "chathomebase.com"


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


def _norm_path(value: str | None) -> str:
    return (value or "").lower().replace("\\", "/")


def is_ix_chromium_exe(exe_path: str | None) -> bool:
    """The open profile Chromium, not the IX dashboard/launcher."""
    path = _norm_path(exe_path)
    name = path.rsplit("/", 1)[-1]
    if name in {"ixbrowser.exe", "ix browser.exe"}:
        return False
    if name not in {"chrome.exe", "chromium.exe"}:
        return False
    return "ixbrowser" in path or "ix-browser" in path


def is_ix_launcher(title: str | None = None, exe_path: str | None = None) -> bool:
    lowered = (title or "").lower()
    path = _norm_path(exe_path)
    name = path.rsplit("/", 1)[-1]
    if name in {"ixbrowser.exe", "ix browser.exe"}:
        return True
    tokens = (
        "edit notes",
        "profile list",
        "create profile",
        "browser profile",
        "proxy resources",
        "extension management",
        "team management",
        "purchase plan",
        "synchronizer",
    )
    return any(token in lowered for token in tokens)


def is_stock_chrome_path(exe_path: str | None) -> bool:
    lowered = _norm_path(exe_path)
    return any(marker in lowered for marker in STOCK_CHROME_MARKERS)


def is_claimed_chat_url(url: str) -> bool:
    lowered = (url or "").lower()
    return SITE_HOST in lowered and "/chat/claimed" in lowered.split("?", 1)[0]


def is_site_url(url: str) -> bool:
    return SITE_HOST in (url or "").lower()


def probe_devtools(url: str, timeout: float = 0.6) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/json/version", timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        return "webSocketDebuggerUrl" in payload or "Browser" in payload
    except Exception:
        return False


def _candidate_http_urls() -> list[str]:
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
        for proc in psutil.process_iter(["pid", "name", "cmdline", "exe"]):
            try:
                info = proc.info
                cmdline_list = info.get("cmdline") or []
                cmd = " ".join(str(part) for part in cmdline_list)
                exe = info.get("exe") or ""
                if is_ix_launcher(info.get("name"), exe):
                    continue
                if is_stock_chrome_path(exe):
                    continue
                if not is_ix_chromium_exe(exe):
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

    for url in _ix_devtools_file_urls():
        add(url)
    return found


def _ix_devtools_file_urls() -> list[str]:
    import os

    urls: list[str] = []
    skip_dir = {"cache", "gpucache", "code cache", "crashpad", "dictionaries", "chrome"}
    roots: list[Path] = []
    for env in ("APPDATA", "LOCALAPPDATA"):
        raw = os.environ.get(env)
        if raw:
            roots.append(Path(raw))
    for root in roots:
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or "ixbrowser" not in child.name.lower():
                continue
            stack = [(child, 0)]
            while stack:
                current, depth = stack.pop()
                if depth > 4:
                    continue
                portfile = current / "DevToolsActivePort"
                if portfile.is_file():
                    port = read_devtools_active_port(current)
                    if port:
                        urls.append(f"http://127.0.0.1:{port}")
                try:
                    for entry in current.iterdir():
                        if entry.is_dir() and entry.name.lower() not in skip_dir:
                            stack.append((entry, depth + 1))
                except OSError:
                    continue
    return urls


def discover_cdp_http_urls() -> list[str]:
    found = _candidate_http_urls()
    live = [url for url in found if probe_devtools(url)]
    if live:
        logger.info("Found live DevTools on %s", live)
        return live
    logger.info("No live IX DevTools endpoint (Google Chrome listen ports are ignored)")
    return []
