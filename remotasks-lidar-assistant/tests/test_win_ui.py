from __future__ import annotations

import pytest

from win_ui import score_window, select_ix_window


GEMINI_CHROME = {
    "title": "Atlas Capture: Get Paid Recording Tasks - Google Gemini - Google Chrome",
    "class_name": "Chrome_WidgetWin_1",
    "exe_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
}

IX_TASK = {
    "hwnd": 42,
    "title": "ego_rectified_canonical",
    "class_name": "Chrome_WidgetWin_1",
    "exe_path": r"C:\Users\user\AppData\Local\IXBrowser\Application\chrome.exe",
}


def test_score_window_prefers_ix_and_task_words() -> None:
    ix = score_window("IX Browser - Profile 1 - Review", "Chrome_WidgetWin_1")
    chrome = score_window("Google Chrome", "Chrome_WidgetWin_1")
    assert ix > chrome
    assert ix >= 3
    assert chrome == 0


def test_score_window_ignores_unrelated_apps() -> None:
    assert score_window("Notepad", "Notepad") == 0


def test_rejects_google_chrome_gemini_tab() -> None:
    assert score_window(GEMINI_CHROME["title"], GEMINI_CHROME["class_name"], GEMINI_CHROME["exe_path"]) == 0


def test_select_ix_not_gemini_chrome() -> None:
    chosen = select_ix_window([GEMINI_CHROME, IX_TASK])
    assert chosen is not None
    assert chosen["title"] == "ego_rectified_canonical"
    assert "IXBrowser" in chosen["exe_path"]


def test_select_ix_by_exe_when_title_is_generic() -> None:
    ix = {
        "title": "New Tab",
        "class_name": "Chrome_WidgetWin_1",
        "exe_path": r"C:\Users\user\AppData\Local\IXBrowser\Application\chrome.exe",
    }
    chosen = select_ix_window([GEMINI_CHROME, ix])
    assert chosen is not None
    assert chosen["title"] == "New Tab"


def test_select_ix_window_none_when_only_chrome() -> None:
    assert select_ix_window([GEMINI_CHROME]) is None


def test_drive_open_task_requires_windows(monkeypatch) -> None:
    import win_ui

    monkeypatch.setattr(win_ui.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows-only"):
        win_ui.drive_open_task()
