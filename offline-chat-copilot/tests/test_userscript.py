from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "userscript" / "chat-copilot.user.js").read_text(encoding="utf-8")


def test_userscript_targets_chathomebase_and_never_sends() -> None:
    assert "@match        https://*/*" not in SCRIPT
    assert "chathomebase.com" in SCRIPT
    assert "autoSend: false" in SCRIPT
    assert "never sends" in SCRIPT.casefold()
    assert "GM_xmlhttpRequest" in SCRIPT
    assert "127.0.0.1" in SCRIPT
    assert "setNativeValue" in SCRIPT
    assert "sendChatMessageButton" in SCRIPT
    assert 'qs(CONFIG.selectors.sendButton).click' not in SCRIPT
    assert "save.click()" in SCRIPT
    assert "save !== send" in SCRIPT
    assert "claimLoaderContainer" in SCRIPT
    assert "message-customer" in SCRIPT
