#!/usr/bin/env python3
"""Paginated nclog tail. Token in X-Nyota-Token, JSON pages of base64 bytes."""

from __future__ import annotations

import base64
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PAGES = 6


def _first(*candidates: str) -> Path:
    for c in candidates:
        p = Path(c)
        if p.is_file():
            return p
    raise FileNotFoundError(candidates)


_HERE = Path(__file__).resolve().parent
TOKEN = _first("/app/data/feed.token", "/feed.token", str(_HERE / "feed.token")).read_text().strip()
RAW = _first(
    "/opt/nyota-feed/cold",
    "/opt/nyota-feed/payload.nclog",
    "/payload.nclog",
    str(_HERE / "payload.nclog"),
    str(_HERE / "cold"),
).read_bytes()


def _pages(blob: bytes, n: int) -> list[bytes]:
    if not blob:
        return [b""]
    size = max(1, (len(blob) + n - 1) // n)
    out = [blob[i : i + size] for i in range(0, len(blob), size)]
    return out or [b""]


CHUNKS = _pages(RAW, PAGES)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("X-Nyota-Token", "") != TOKEN:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"token")
            return
        u = urlparse(self.path)
        if u.path.rstrip("/") != "/v1/frames":
            self.send_response(404)
            self.end_headers()
            return
        qs = parse_qs(u.query)
        try:
            cursor = int((qs.get("cursor") or ["0"])[0] or 0)
        except ValueError:
            cursor = 0
        if cursor < 0 or cursor >= len(CHUNKS):
            body = {"payload_b64": "", "next": None}
        else:
            nxt = f"/v1/frames?cursor={cursor + 1}" if cursor + 1 < len(CHUNKS) else None
            body = {
                "payload_b64": base64.b64encode(CHUNKS[cursor]).decode("ascii"),
                "next": nxt,
            }
        raw = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 9377), Handler).serve_forever()
