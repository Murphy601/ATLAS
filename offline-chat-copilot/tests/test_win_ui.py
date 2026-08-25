from __future__ import annotations

import pytest

from offline_copilot.chathomebase import is_forbidden_click
from offline_copilot.win_ui import (
    keep_enumerated_window,
    parse_messages_from_names,
    pick_draft_edit,
    run_uia_attach,
    score_window,
    select_ix_window,
    snapshot_from_uia_names,
)


GEMINI_CHROME = {
    "title": "Atlas Capture: Get Paid Recording Tasks - Google Gemini - Google Chrome",
    "class_name": "Chrome_WidgetWin_1",
    "exe_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
}

IX_TASK = {
    "hwnd": 42,
    "title": "Chat Home Base - Chromium",
    "class_name": "Chrome_WidgetWin_1",
    "exe_path": r"C:\Users\user\AppData\Local\IXBrowser\Application\chrome.exe",
}


def test_score_window_prefers_ix_and_sensorfusionlab() -> None:
    ix = score_window(
        "SensorFusionLab - Chromium",
        "Chrome_WidgetWin_1",
        r"C:\Users\user\AppData\Roaming\ixBrowser-Resources\chrome\148-0005\chrome.exe",
    )
    chrome = score_window("Google Chrome", "Chrome_WidgetWin_1")
    assert ix > chrome
    assert ix >= 3
    assert chrome == 0


def test_rejects_google_chrome_and_ix_launcher() -> None:
    assert score_window(GEMINI_CHROME["title"], GEMINI_CHROME["class_name"], GEMINI_CHROME["exe_path"]) == 0
    assert (
        score_window(
            "ixBrowser | v2.9.20",
            "Chrome_WidgetWin_1",
            r"C:\Users\user\AppData\Local\IXBrowser\IXBrowser.exe",
        )
        == 0
    )
    assert (
        score_window(
            "Edit Notes",
            "Chrome_WidgetWin_1",
            r"C:\Users\user\AppData\Local\IXBrowser\IXBrowser.exe",
        )
        == 0
    )


def test_select_ix_not_gemini_chrome() -> None:
    chosen = select_ix_window([GEMINI_CHROME, IX_TASK])
    assert chosen is not None
    assert chosen["title"] == "Chat Home Base - Chromium"
    assert "IXBrowser" in chosen["exe_path"]


def test_select_chromium_not_profile_manager() -> None:
    manager = {
        "title": "Edit Notes",
        "class_name": "Chrome_WidgetWin_1",
        "exe_path": r"C:\Users\user\AppData\Local\IXBrowser\IXBrowser.exe",
    }
    task = {
        "hwnd": 7,
        "title": "SensorFusionLab - क्रोमियम",
        "class_name": "Chrome_WidgetWin_1",
        "exe_path": r"C:\Users\user\AppData\Roaming\ixBrowser-Resources\chrome\148-0005\chrome.exe",
    }
    chosen = select_ix_window([manager, task])
    assert chosen is not None
    assert chosen["title"].startswith("SensorFusionLab")
    assert "ixBrowser-Resources" in chosen["exe_path"]


def test_keep_minimized_sensorfusionlab() -> None:
    chromium = r"C:\Users\user\AppData\Roaming\ixBrowser-Resources\chrome\148-0005\chrome.exe"
    assert keep_enumerated_window(
        160,
        28,
        visible=True,
        minimized=True,
        title="SensorFusionLab - Chromium",
        class_name="Chrome_WidgetWin_1",
        exe_path=chromium,
    )
    assert not keep_enumerated_window(
        180,
        32,
        minimized=True,
        title="New project build | Cursor - Google Chrome",
        class_name="Chrome_WidgetWin_1",
        exe_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    )


def test_pick_draft_edit_is_lowest_not_address_bar_or_send() -> None:
    chosen = pick_draft_edit(
        [
            {"name": "Address and search bar", "control_type": "Edit", "top": 40, "width": 800},
            {"name": "Send", "control_type": "Button", "top": 900, "width": 80},
            {"name": "", "control_type": "Edit", "top": 880, "width": 420},
            {"name": "Search", "control_type": "Edit", "top": 120, "width": 200},
        ]
    )
    assert chosen is not None
    assert chosen["top"] == 880
    assert not is_forbidden_click(label=chosen.get("name") or "")


def test_snapshot_waiting_vs_live_from_uia() -> None:
    waiting = snapshot_from_uia_names(
        ["Chat Home Base", "Waiting for a claim"],
        has_edit=False,
        has_send=False,
        title="SensorFusionLab - Chromium",
    )
    assert waiting.waiting is True
    assert waiting.claimed is False
    live = snapshot_from_uia_names(
        ["Chat Home Base", "USETN4695969", "Nthabiseng", "Hey! Where are you located?"],
        has_edit=True,
        has_send=True,
        title="SensorFusionLab - Chromium",
    )
    assert live.claimed is True
    assert live.chat_id == "USETN4695969"


def test_parse_messages_skips_chrome_and_send() -> None:
    rows = parse_messages_from_names(
        [
            "SensorFusionLab",
            "Address and search bar",
            "Send",
            "Hey! Where are you located? Are you watching any games today?",
            "USETN4695969",
        ]
    )
    assert [row["text"] for row in rows] == [
        "Hey! Where are you located? Are you watching any games today?"
    ]
    assert rows[0]["sender"] == "client"


def test_desktop_attach_requires_windows(monkeypatch) -> None:
    import offline_copilot.win_ui as win_ui

    monkeypatch.setattr(win_ui.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows-only"):
        run_uia_attach()
