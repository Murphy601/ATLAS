from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from offline_copilot.controller import CopilotController, serve_in_thread


def test_controller_refuses_non_localhost() -> None:
    controller = CopilotController()
    try:
        controller.serve("0.0.0.0", 8765)
        raise AssertionError("should have refused non-localhost bind")
    except ValueError as exc:
        assert "localhost" in str(exc)


def test_claim_endpoint_returns_never_send(tmp_path: Path) -> None:
    controller = CopilotController(logbook_dir=tmp_path)
    server, thread = serve_in_thread("127.0.0.1", 0, controller.logbook)
    try:
        port = server.server_address[1]
        body = json.dumps(
            {
                "client_id": "USETN4695969",
                "client_name": "Nthabiseng",
                "persona_city": "Atlanta",
                "history": [
                    {"sender": "client", "text": "I'm from Atlanta. Where are you located?"},
                ],
            }
        ).encode("utf-8")
        req = Request(
            f"http://127.0.0.1:{port}/claim",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["never_send"] is True
        assert payload["blocked"] is False
        assert payload["save_logbook"] is True
        assert payload["logbook_fields"]["clientCity"] == "Atlanta"
        assert payload["fill_draft"]
        assert len(payload["options"]) == 3
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_health_and_unknown_route(tmp_path: Path) -> None:
    controller = CopilotController(logbook_dir=tmp_path)
    server, thread = serve_in_thread("127.0.0.1", 0, controller.logbook)
    try:
        port = server.server_address[1]
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["ok"] is True
        assert payload["never_send"] is True
        try:
            urlopen(f"http://127.0.0.1:{port}/nope", timeout=5)
            raise AssertionError("unknown route should 404")
        except HTTPError as exc:
            assert exc.code == 404
    finally:
        server.shutdown()
        thread.join(timeout=2)
