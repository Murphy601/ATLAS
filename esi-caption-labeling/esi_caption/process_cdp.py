"""Find DevTools on an already-open IX or MoreLogin Chromium. Never launches a browser."""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from pathlib import Path

from .browsers import is_family_chromium, is_family_launcher, is_ix_chromium_exe, is_morelogin_chromium_exe

logger = logging.getLogger("esi.process_cdp")

PORT_RE = re.compile(r"--remote-debugging-port(?:=|\s+)(\d+)", re.I)
USER_DIR_RE = re.compile(r'--user-data-dir(?:=|\s+)(?:"([^"]+)"|(\S+))', re.I)
DEFAULT_DEBUG_PORTS = (9222, 9229, 9333, 9223)


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


def probe_devtools(url: str, timeout: float = 0.6) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/json/version", timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        return "webSocketDebuggerUrl" in payload or "Browser" in payload
    except Exception:
        return False


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


def describe_open_browsers(family: str) -> list[str]:
    try:
        import psutil
    except ImportError:
        return [f"[Scan] psutil is missing; cannot list the open {family} process."]
    lines: list[str] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline", "exe"]):
        try:
            info = proc.info
            exe = info.get("exe") or ""
            name = info.get("name") or ""
            cmd = " ".join(str(part) for part in (info.get("cmdline") or []))
            if not is_family_chromium(family, exe, cmd) and not is_family_launcher(family, name, exe):
                continue
            ports = _listen_ports(proc)
            debug = parse_debug_port(cmd)
            kind = "chromium" if is_family_chromium(family, exe, cmd) else "launcher"
            listen = ",".join(str(p) for p in ports) if ports else "none"
            lines.append(
                f"[Scan] {family} {kind} pid={info.get('pid')} exe={exe} "
                f"debug_port={debug or 'none'} listen=[{listen}]"
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    if not lines:
        lines.append(f"[Scan] No {family} Chromium process found.")
    return lines


def discover_cdp_http_urls(family: str) -> list[str]:
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
                exe = info.get("exe") or ""
                cmd = " ".join(str(part) for part in (info.get("cmdline") or []))
                if not is_family_chromium(family, exe, cmd):
                    continue
                for url in command_line_cdp_urls(cmd):
                    add(url)
                for port in _listen_ports(proc):
                    add(f"http://127.0.0.1:{port}")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    for port in DEFAULT_DEBUG_PORTS:
        add(f"http://127.0.0.1:{port}")
    live = [url for url in found if probe_devtools(url)]
    return live


def is_task_url(url: str) -> bool:
    lowered = (url or "").lower()
    return "multimango.com" in lowered and "caption" in lowered


__all__ = [
    "describe_open_browsers",
    "discover_cdp_http_urls",
    "is_ix_chromium_exe",
    "is_morelogin_chromium_exe",
    "is_task_url",
    "probe_devtools",
]
