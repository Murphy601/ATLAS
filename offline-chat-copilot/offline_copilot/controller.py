"""Local desktop controller. Binds 127.0.0.1 only. No LLM. Never sends a chat."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .engine import CopilotResult, handle_claimed_chat
from .logbook import Logbook

MAX_BODY = 1_000_000
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def result_payload(result: CopilotResult) -> dict[str, Any]:
    return {
        "blocked": result.blocked,
        "reason": result.reason,
        "options": list(result.options),
        "checks": list(result.checks),
        "suggested_facts": list(result.suggested_facts),
        "logbook_fields": dict(result.logbook_fields),
        "save_logbook": bool(result.save_logbook),
        "save_reason": result.save_reason,
        "never_send": True,
        "fill_draft": result.fill_draft,
    }


def handle_payload(payload: dict[str, Any], logbook: Logbook) -> dict[str, Any]:
    history = payload.get("history") or []
    if not isinstance(history, list):
        return {
            "blocked": True,
            "reason": "history must be a list",
            "options": [],
            "never_send": True,
            "fill_draft": None,
            "logbook_fields": {},
            "save_logbook": False,
        }
    result = handle_claimed_chat(
        history,
        client_id=str(payload.get("client_id") or ""),
        header_name=str(payload.get("client_name") or payload.get("header_name") or ""),
        header_city=str(payload.get("client_city") or payload.get("header_city") or ""),
        persona_city=str(payload.get("persona_city") or ""),
        logbook=logbook,
        remember=bool(payload.get("remember", True)),
    )
    return result_payload(result)


class CopilotHandler(BaseHTTPRequestHandler):
    logbook: Logbook

    def log_message(self, fmt: str, *args: Any) -> None:
        super().log_message(fmt, *args)

    def _forbidden(self, message: str, status: int = 403) -> None:
        self._write(status, {"blocked": True, "reason": message, "never_send": True})

    def _write(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/", "/health"}:
            self._write(200, {"ok": True, "never_send": True, "bind": "127.0.0.1"})
            return
        self._forbidden("unknown route", 404)

    def do_POST(self) -> None:  # noqa: N802
        host = (self.headers.get("Host") or "").split(":")[0].strip().casefold()
        if host not in ALLOWED_HOSTS:
            self._forbidden("localhost only")
            return
        path = urlparse(self.path).path
        if path not in {"/claim", "/event/claimed", "/draft"}:
            self._forbidden("unknown route", 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._forbidden("body too large", 413)
            return
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._forbidden("invalid json", 400)
            return
        if not isinstance(payload, dict):
            self._forbidden("json object required", 400)
            return
        result = handle_payload(payload, self.logbook)
        self._write(200, result)


def make_server(host: str, port: int, logbook: Logbook) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Controller refuses to bind off localhost")

    class BoundHandler(CopilotHandler):
        pass

    BoundHandler.logbook = logbook
    return ThreadingHTTPServer((host, int(port)), BoundHandler)


def serve_forever(host: str = "127.0.0.1", port: int = 8765, logbook_path: str = "logbook.json") -> None:
    server = make_server(host, port, Logbook(logbook_path))
    print(f"[copilot] desktop controller on http://{host}:{port} (never sends messages)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[copilot] stopped")
    finally:
        server.server_close()


def serve_in_thread(
    host: str = "127.0.0.1",
    port: int = 8765,
    logbook: Logbook | None = None,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = make_server(host, port, logbook or Logbook())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class CopilotController:
    """Localhost-only HTTP front for the userscript. Never sends a chat."""

    def __init__(self, logbook_dir: str | Path | None = None, logbook: Logbook | None = None) -> None:
        if logbook is not None:
            self.logbook = logbook
        elif logbook_dir is not None:
            self.logbook = Logbook(Path(logbook_dir) / "logbook.json")
        else:
            self.logbook = Logbook()

    def serve(self, host: str, port: int) -> None:
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Controller refuses to bind off localhost")
        serve_forever(host, port, str(self.logbook.path))
