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
    ix = score_window(
        "SensorFusionLab - Chromium",
        "Chrome_WidgetWin_1",
        r"C:\Users\user\AppData\Roaming\ixBrowser-Resources\chrome\148-0005\chrome.exe",
    )
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


def test_page_click_points_skip_tab_strip() -> None:
    from win_ui import page_click_points

    points = page_click_points(0, 0, 1050, 700)
    assert points
    _x, y, label = points[0]
    assert label == "video-center"
    assert y > 160
    assert all(pt[1] > 100 for pt in points)


def test_parse_media_clock() -> None:
    from win_ui import parse_media_clock

    assert parse_media_clock("0:12 / 1:45") == 105
    assert parse_media_clock("no clock") is None


def test_sensorfusionlab_title_scores_as_ix_task() -> None:
    from win_ui import score_window

    score = score_window(
        "SensorFusionLab - Chromium",
        "Chrome_WidgetWin_1",
        r"C:\Users\user\AppData\Roaming\ixBrowser-Resources\chrome\148-0005\chrome.exe",
    )
    assert score > 50


def test_rejects_ix_profile_manager_not_chromium() -> None:
    dashboard = score_window(
        "Edit Notes",
        "Chrome_WidgetWin_1",
        r"C:\Users\user\AppData\Local\IXBrowser\IXBrowser.exe",
    )
    manager = score_window(
        "Dashboard / Browser Profile / Profile List",
        "Chrome_WidgetWin_1",
        r"C:\Users\user\AppData\Local\IXBrowser\IXBrowser.exe",
    )
    assert dashboard == 0
    assert manager == 0


def test_launcher_title_is_not_the_task() -> None:
    from win_ui import keep_enumerated_window, score_window

    launcher = r"C:\Users\user\AppData\Local\IXBrowser\IXBrowser.exe"
    chromium = r"C:\Users\user\AppData\Roaming\ixBrowser-Resources\chrome\148-0005\chrome.exe"
    assert score_window("ixBrowser | v2.9.20", "Chrome_WidgetWin_1", launcher) == 0
    assert keep_enumerated_window(
        160,
        28,
        visible=True,
        minimized=True,
        title="SensorFusionLab - क्रोमियम",
        class_name="Chrome_WidgetWin_1",
        exe_path=chromium,
    )
    assert keep_enumerated_window(
        180,
        32,
        minimized=True,
        title="SensorFusionLab - Chromium",
        class_name="Chrome_WidgetWin_1",
        exe_path=chromium,
    )
    assert keep_enumerated_window(
        160,
        28,
        minimized=True,
        title="",
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


def test_pick_ix_window_retries_until_sensorfusionlab(monkeypatch) -> None:
    import win_ui

    calls = {"n": 0}
    task = {
        "hwnd": 9,
        "title": "SensorFusionLab - Chromium",
        "class_name": "Chrome_WidgetWin_1",
        "exe_path": r"C:\Users\user\AppData\Roaming\ixBrowser-Resources\chrome\148-0005\chrome.exe",
        "minimized": True,
    }

    def fake_enum():
        calls["n"] += 1
        if calls["n"] < 3:
            return [], ["ixBrowser | v2.9.20"], ["Saw IX window (1200x800): ixBrowser | v2.9.20"]
        return [task], ["ixBrowser | v2.9.20"], ["Saw IX window (minimized): SensorFusionLab - Chromium"]

    monkeypatch.setattr(win_ui, "_enumerate_task_windows", fake_enum)
    monkeypatch.setattr(win_ui.time, "sleep", lambda _s: None)
    hwnd, title = win_ui._pick_ix_window()
    assert hwnd == 9
    assert title.startswith("SensorFusionLab")
    assert calls["n"] >= 3


def test_drive_open_task_requires_windows(monkeypatch) -> None:
    import win_ui

    monkeypatch.setattr(win_ui.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows-only"):
        win_ui.drive_open_task()


def test_empty_clip_and_use_helpers_match_screenshot_labels() -> None:
    from review_ui import is_empty_clip_label, is_quality_empty_error, is_review_use_label

    assert is_empty_clip_label("click to add text")
    assert is_review_use_label("Use")
    assert is_quality_empty_error("ClipExport and Sub-goal clips must contain text")
    assert not is_review_use_label("Ignore")
