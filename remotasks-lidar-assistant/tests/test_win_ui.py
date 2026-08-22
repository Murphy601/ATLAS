from __future__ import annotations

import pytest

from win_ui import score_window


def test_score_window_prefers_ix_and_task_words() -> None:
    ix = score_window("IX Browser - Profile 1 - Review", "Chrome_WidgetWin_1")
    chrome = score_window("Google Chrome", "Chrome_WidgetWin_1")
    assert ix > chrome
    assert ix >= 3


def test_score_window_ignores_unrelated_apps() -> None:
    assert score_window("Notepad", "Notepad") == 0


def test_drive_open_task_requires_windows(monkeypatch) -> None:
    import win_ui

    monkeypatch.setattr(win_ui.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows-only"):
        win_ui.drive_open_task()
