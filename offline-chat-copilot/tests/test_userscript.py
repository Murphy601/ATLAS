from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "userscript" / "chat-copilot.user.js").read_text(encoding="utf-8")


def test_userscript_never_sends_and_is_not_site_wide() -> None:
    assert "@match        https://*/*" not in SCRIPT
    assert "YOUR-OPERATOR-DASHBOARD" in SCRIPT
    assert "autoSend: false" in SCRIPT
    assert "never sends" in SCRIPT.casefold()
    assert "GM_xmlhttpRequest" in SCRIPT
    assert "127.0.0.1" in SCRIPT
    assert "setNativeValue" in SCRIPT
    assert "unclaimed" in SCRIPT.casefold()
    assert "sendButton:" in SCRIPT
    assert "qs(CONFIG.selectors.sendButton).click" not in SCRIPT
    assert "save.click()" in SCRIPT
    assert "save !== send" in SCRIPT
