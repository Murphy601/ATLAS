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


def test_score_prefers_task_title() -> None:
    ix_exe = r"C:\Users\user\AppData\Roaming\ixBrowser-Resources\chrome\chrome.exe"
    ml_exe = r"C:\Users\user\AppData\Roaming\MoreLogin\chrome\chrome.exe"
    title = "Hierarchical Egocentric Video Captioning (Environment, Segments & Actions) - Chromium"
    ix = score_task_window(title, "Chrome_WidgetWin_1", ix_exe, family="ix")
    ml = score_task_window(title, "Chrome_WidgetWin_1", ml_exe, family="morelogin")
    chrome = score_task_window(title, "Chrome_WidgetWin_1", r"C:\Program Files\Google\Chrome\Application\chrome.exe", family="ix")
    assert ix > 80
    assert ml > 80
    assert chrome == 0
    gmail = score_task_window("Inbox - Gmail - Google Chrome", "Chrome_WidgetWin_1", ix_exe, family="ix")
    assert gmail == 0


def test_family_helper() -> None:
    assert is_family_chromium("ix", r"C:\ixBrowser-Resources\chrome.exe") is True
    assert is_family_chromium("morelogin", r"C:\MoreLogin\chrome.exe") is True
