"""Discover the CDP address of an already-open IX Browser profile."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger("ego.ix")

IX_API_PORTS = (53200, 53201, 3030, 35000)
IX_OPENED_PATHS = (
    "/api/v2/get-opened-profiles",
    "/api/getOpenedProfile",
    "/api/v2/profile-opened-list",
    "/api/retrieveOpenedProfiles",
    "/api/v1/browser/opened",
)

DEBUG_KEYS = (
    "debugging_address",
    "debuggerAddress",
    "debugger_address",
    "debuggingAddress",
    "ws",
    "cdp",
    "selenium",
    "webSocketDebuggerUrl",
)


def discover_cdp_http_urls() -> list[str]:
    """Ask the IX local API which profiles are already open. Never opens a new window."""
    found: list[str] = []
    for port in IX_API_PORTS:
        for path in IX_OPENED_PATHS:
            payload = _post_json(f"http://127.0.0.1:{port}{path}")
            if payload is None:
                continue
            logger.info("IX local API responded at port %s path %s", port, path)
            for addr in extract_debug_addresses(payload):
                http = to_cdp_http(addr)
                if http and http not in found:
                    found.append(http)
                    logger.info("IX opened profile CDP: %s", http)
            if found:
                return found
    return found


def extract_debug_addresses(payload: Any) -> list[str]:
    out: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in DEBUG_KEYS and isinstance(value, str) and value.strip():
                    out.append(value.strip())
                if key in {"debugging_port", "debug_port", "remote_debugging_port"} and value:
                    out.append(f"127.0.0.1:{value}")
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return out


def to_cdp_http(address: str) -> str | None:
    text = address.strip()
    if text.startswith("ws://") or text.startswith("wss://"):
        return text.replace("ws://", "http://", 1).replace("wss://", "https://", 1)
    if text.startswith("http://") or text.startswith("https://"):
        return text
    if ":" in text and not text.startswith("/"):
        host, _, port = text.partition(":")
        host = host or "127.0.0.1"
        return f"http://{host}:{port.split('/')[0]}"
    return None


def _post_json(url: str) -> Any | None:
    try:
        req = urllib.request.Request(
            url,
            data=b"{}",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw else None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
        return None
