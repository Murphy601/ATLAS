from ix_api import extract_debug_addresses, to_cdp_http


def test_extracts_debugging_address_from_ix_payload():
    payload = {
        "error": {"code": 0},
        "data": [
            {
                "profile_id": 12,
                "debugging_address": "127.0.0.1:18789",
                "webdriver": "C:\\ix\\chromedriver.exe",
            }
        ],
    }
    assert extract_debug_addresses(payload) == ["127.0.0.1:18789"]
    assert to_cdp_http("127.0.0.1:18789") == "http://127.0.0.1:18789"


def test_to_cdp_http_from_websocket():
    assert to_cdp_http("ws://127.0.0.1:9222/devtools/browser/abc") == (
        "http://127.0.0.1:9222/devtools/browser/abc"
    )
