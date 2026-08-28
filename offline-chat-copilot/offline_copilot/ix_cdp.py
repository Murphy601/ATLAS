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

IX_PATH_MARKERS = (
    "ixbrowser",
    "ix-browser",
    "/ix browser/",
    "\\ix browser\\",
    "sensorfusionlab",
)
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
DEFAULT_DEBUG_PORTS = (9222, 9229, 9333)
CDP_EMPTY_ROUNDS_BEFORE_FALLBACK = 1


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


def _blob_has_ix_marker(blob: str) -> bool:
    lowered = _norm_path(blob)
    return any(marker.replace("\\", "/") in lowered for marker in IX_PATH_MARKERS)


def is_ix_chromium_exe(
    exe_path: str | None,
    parent_exe: str | None = None,
    command_line: str | None = None,
) -> bool:
    """The open profile Chromium, not the IX dashboard/launcher."""
    path = _norm_path(exe_path)
    name = path.rsplit("/", 1)[-1]
    if name in {"ixbrowser.exe", "ix browser.exe"}:
        return False
    if name not in {"chrome.exe", "chromium.exe"}:
        return False
    blob = " ".join(part for part in (path, _norm_path(parent_exe), command_line or "") if part)
    return _blob_has_ix_marker(blob)


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
        "please enter content",
    )
    if any(token in lowered for token in tokens):
        return True
    if "dashboard" in lowered and "profile" in lowered:
        return True
    return False


def is_stock_chrome_path(exe_path: str | None) -> bool:
    lowered = _norm_path(exe_path)
    return any(marker in lowered for marker in STOCK_CHROME_MARKERS)


def is_claimed_chat_url(url: str) -> bool:
    lowered = (url or "").lower()
    return SITE_HOST in lowered and "/chat/claimed" in lowered.split("?", 1)[0]


def is_site_url(url: str) -> bool:
    return SITE_HOST in (url or "").lower()


def should_fallback_to_desktop(empty_rounds: int) -> bool:
    """Stop waiting for DevTools and use the already-open SensorFusionLab window."""
    return int(empty_rounds) >= CDP_EMPTY_ROUNDS_BEFORE_FALLBACK


def probe_devtools(url: str, timeout: float = 0.6) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/json/version", timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        return "webSocketDebuggerUrl" in payload or "Browser" in payload
    except Exception:
        return False


def _parent_exe(proc) -> str:
    try:
        parent = proc.parent()
        if parent is None:
            return ""
        return parent.exe() or parent.name() or ""
    except Exception:
        return ""


def _listen_ports(proc) -> list[int]:
    ports: list[int] = []
    try:
        for conn in proc.net_connections(kind="inet"):
            if getattr(conn, "status", "") != "LISTEN":
                continue
            laddr = getattr(conn, "laddr", None)
            port = getattr(laddr, "port", None) if laddr is not None else None
            if port:
                ports.append(int(port))
    except Exception:
        return []
    return ports


def describe_open_ix() -> list[str]:
    """Human-readable scan of IX processes. Does not launch anything."""
    try:
        import psutil
    except ImportError:
        return ["[Scan] psutil is missing; cannot list the open IX process."]

    lines: list[str] = []
    saw_chromium = False
    saw_launcher = False
    for proc in psutil.process_iter(["pid", "name", "cmdline", "exe"]):
        try:
            info = proc.info
            cmdline_list = info.get("cmdline") or []
            cmd = " ".join(str(part) for part in cmdline_list)
            exe = info.get("exe") or ""
            name = info.get("name") or ""
            parent = _parent_exe(proc)
            launcher = is_ix_launcher(name, exe)
            chromium = is_ix_chromium_exe(exe, parent_exe=parent, command_line=cmd)
            if not launcher and not chromium:
                continue
            kind = "launcher" if launcher else "chromium"
            if launcher:
                saw_launcher = True
            if chromium:
                saw_chromium = True
            debug = parse_debug_port(cmd)
            ports = _listen_ports(proc)
            lines.append(
                f"[Scan] IX {kind} pid={info.get('pid')} exe={exe or name} "
                f"debug_port={debug or 'none'} listen={ports or 'none'}"
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    if saw_chromium:
        lines.append(
            "[Scan] SensorFusionLab Chromium is running. DevTools is optional; "
            "the open window can be driven from the desktop if port 9222 is off."
        )
    elif saw_launcher:
        lines.append(
            "[Scan] Saw the IX profile manager, not SensorFusionLab. Click Open on the profile."
        )
    else:
        lines.append(
            "[Scan] No IX Browser process. Open the IX profile so SensorFusionLab is visible."
        )
    return lines


def _candidate_http_urls() -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    saw_ix_chromium = False

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
                name = info.get("name") or ""
                if is_ix_launcher(name, exe):
                    continue
                if is_stock_chrome_path(exe):
                    continue
                parent = _parent_exe(proc)
                if not is_ix_chromium_exe(exe, parent_exe=parent, command_line=cmd):
                    continue
                saw_ix_chromium = True
                for url in command_line_cdp_urls(cmd):
                    add(url)
                for port in _listen_ports(proc):
                    add(f"http://127.0.0.1:{port}")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

    for url in _ix_devtools_file_urls():
        add(url)
    if saw_ix_chromium:
        for port in DEFAULT_DEBUG_PORTS:
            add(f"http://127.0.0.1:{port}")
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
