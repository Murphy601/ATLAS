from esi_caption.browsers import (
    is_family_chromium,
    is_ix_chromium_exe,
    is_ix_launcher,
    is_morelogin_chromium_exe,
    is_morelogin_launcher,
    score_task_window,
)


def test_ix_chromium_not_launcher() -> None:
    exe = r"C:\Users\user\AppData\Roaming\ixBrowser-Resources\chrome\148-0005\chrome.exe"
    assert is_ix_chromium_exe(exe) is True
    assert is_morelogin_chromium_exe(exe) is False
    assert is_ix_launcher("ixBrowser | v2.9.20", r"C:\Program Files (x86)\ixBrowser\ixBrowser.exe") is True


def test_morelogin_chromium_not_manager() -> None:
    exe = r"C:\Users\user\AppData\Roaming\MoreLogin\chrome\chrome.exe"
    assert is_morelogin_chromium_exe(exe) is True
    assert is_ix_chromium_exe(exe) is False
    assert is_morelogin_launcher("MoreLogin", r"C:\Program Files\MoreLogin\MoreLogin.exe") is True
    assert (
        is_morelogin_launcher(
            "Hierarchical Egocentric Video Captioning - Chromium",
            exe,
        )
        is False
    )


def test_score_prefers_large_task_window_not_tiny_stub() -> None:
    ix_exe = r"C:\Users\user\AppData\Roaming\ixBrowser-Resources\chrome\chrome.exe"
    title = "Hierarchical Egocentric Video Captioning (Environment, Segments & Actions) - Chromium"
    tiny = score_task_window(title, "Chrome_WidgetWin_1", ix_exe, family="ix", width=158, height=26)
    large = score_task_window(title, "Chrome_WidgetWin_1", ix_exe, family="ix", width=1575, height=1050)
    handshake = score_task_window(
        "1:53:04 - Handshake AI - Chromium",
        "Chrome_WidgetWin_1",
        ix_exe,
        family="ix",
        width=1050,
        height=700,
    )
    assert large > tiny
    assert tiny < 0
    assert handshake == 0
    chrome = score_task_window(
        title,
        "Chrome_WidgetWin_1",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        family="ix",
        width=1575,
        height=1050,
    )
    assert chrome == 0


def test_family_helper() -> None:
    assert is_family_chromium("ix", r"C:\ixBrowser-Resources\chrome.exe") is True
    assert is_family_chromium("morelogin", r"C:\MoreLogin\chrome.exe") is True
