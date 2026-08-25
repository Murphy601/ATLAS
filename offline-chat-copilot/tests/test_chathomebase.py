from pathlib import Path

from offline_copilot.chathomebase import (
    CLAIMED_URL,
    claim_became_live,
    is_forbidden_click,
    locality_from_profile_location,
    logbook_comment,
    parse_messages,
    parse_testid_text,
    snapshot_from_flags,
)
from offline_copilot.ix_cdp import (
    is_claimed_chat_url,
    is_ix_chromium_exe,
    is_stock_chrome_path,
    parse_debug_port,
)


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "claimed_chat.html"


def test_claimed_url_is_not_enough_to_treat_as_live() -> None:
    assert is_claimed_chat_url(CLAIMED_URL) is True
    waiting = snapshot_from_flags(url=CLAIMED_URL, has_loader=True, has_draft=False)
    assert waiting.waiting is True
    assert waiting.claimed is False
    live = snapshot_from_flags(url=CLAIMED_URL, has_loader=False, has_draft=True, chat_id="abc")
    assert live.claimed is True
    assert claim_became_live(waiting, live) is True
    assert claim_became_live(live, live) is False
    next_chat = snapshot_from_flags(url=CLAIMED_URL, has_draft=True, chat_id="def")
    assert claim_became_live(live, next_chat) is True


def test_parse_fixture_splits_customer_and_operator() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    messages = parse_messages(html)
    assert [row["sender"] for row in messages] == ["client", "operator", "client"]
    assert "Atlanta" in messages[0]["text"]
    assert messages[1]["sender"] == "operator"
    assert parse_testid_text(html, "chat-id") == "USETN4695969"
    assert parse_testid_text(html, "logbookCustomerName") == "Nthabiseng"


def test_never_click_send() -> None:
    assert is_forbidden_click(testid="sendChatMessageButton") is True
    assert is_forbidden_click(testid="sendChatMessageoptions") is True
    assert is_forbidden_click(label="Send") is True
    assert is_forbidden_click(testid="logbookSaveButton") is False
    assert is_forbidden_click(testid="addNewLogbookButton-customer") is False


def test_logbook_comment_and_locality() -> None:
    comment = logbook_comment({"clientName": "Nthabiseng", "clientCity": "Atlanta", "clientInterests": "Sports"})
    assert "City: Atlanta" in comment
    assert "Sports" in comment
    assert locality_from_profile_location("locality: Dallas") == "Dallas"


def test_ix_attach_ignores_stock_chrome() -> None:
    assert is_stock_chrome_path(r"C:\Program Files\Google\Chrome\Application\chrome.exe") is True
    assert is_ix_chromium_exe(r"C:\Users\user\AppData\Local\IXBrowser\chrome.exe") is True
    assert is_ix_chromium_exe(r"C:\Program Files\Google\Chrome\Application\chrome.exe") is False
    assert parse_debug_port("--remote-debugging-port=9222") == 9222
