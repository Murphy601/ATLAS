"""IX Browser vs MoreLogin process and window matching. Never launches a browser."""

from __future__ import annotations

IX_PATH_MARKERS = (
    "ixbrowser",
    "ix-browser",
    "/ix browser/",
    "\\ix browser\\",
    "sensorfusionlab",
)
MORELOGIN_PATH_MARKERS = (
    "morelogin",
    "more-login",
    "/more login/",
    "\\more login\\",
    "mlbrowser",
    "morelogin-resources",
)
STOCK_CHROME_MARKERS = (
    "/google/chrome/",
    "/google/chrome beta/",
    "/microsoft/edge/",
    "/brave software/",
)
IX_LAUNCHER_TITLES = (
    "edit notes",
    "profile list",
    "create profile",
    "ixbrowser |",
    "synchronizer",
)
MORELOGIN_LAUNCHER_TITLES = (
    "morelogin",
    "browser list",
    "fingerprint",
    "proxy setting",
)
TASK_HINTS = (
    "multimango",
    "hierarchical egocentric",
    "video caption labeling",
    "esi-caption",
    "caption labeling",
    "generate with ai",
    "level 3",
    "level 2 —",
    "environment, segments",
)
REJECT_TITLE_TOKENS = (
    "google chrome",
    "google gemini",
    "microsoft edge",
    "gmail",
)


def _norm(value: str | None) -> str:
    return (value or "").lower().replace("\\", "/")


def _blob(*parts: str | None) -> str:
    return " ".join(_norm(part) for part in parts if part)


def is_stock_chrome_path(exe_path: str | None) -> bool:
    path = _norm(exe_path)
    return any(marker in path for marker in STOCK_CHROME_MARKERS)


def is_ix_chromium_exe(exe_path: str | None, command_line: str | None = None) -> bool:
    path = _norm(exe_path)
    name = path.rsplit("/", 1)[-1]
    if name in {"ixbrowser.exe", "ix browser.exe"}:
        return False
    if name not in {"chrome.exe", "chromium.exe"}:
        return False
    hay = _blob(path, command_line)
    return any(marker.replace("\\", "/") in hay for marker in IX_PATH_MARKERS)


def is_morelogin_chromium_exe(exe_path: str | None, command_line: str | None = None) -> bool:
    path = _norm(exe_path)
    name = path.rsplit("/", 1)[-1]
    if name in {"morelogin.exe", "more login.exe"}:
        return False
    if name not in {"chrome.exe", "chromium.exe"}:
        return False
    hay = _blob(path, command_line)
    return any(marker.replace("\\", "/") in hay for marker in MORELOGIN_PATH_MARKERS)


def is_ix_launcher(title: str | None = None, exe_path: str | None = None) -> bool:
    path = _norm(exe_path)
    name = path.rsplit("/", 1)[-1]
    if name in {"ixbrowser.exe", "ix browser.exe"}:
        return True
    lowered = (title or "").lower()
    return any(token in lowered for token in IX_LAUNCHER_TITLES)


def is_morelogin_launcher(title: str | None = None, exe_path: str | None = None) -> bool:
    path = _norm(exe_path)
    name = path.rsplit("/", 1)[-1]
    if name in {"morelogin.exe", "more login.exe"}:
        return True
    lowered = (title or "").lower()
    # The task Chromium title is the MultiMango page, not the MoreLogin manager.
    if any(hint in lowered for hint in TASK_HINTS):
        return False
    if "chromium" in lowered or "multimango" in lowered:
        return False
    return any(token in lowered for token in MORELOGIN_LAUNCHER_TITLES) and "caption" not in lowered


def is_family_chromium(family: str, exe_path: str | None, command_line: str | None = None) -> bool:
    if family == "morelogin":
        return is_morelogin_chromium_exe(exe_path, command_line)
    return is_ix_chromium_exe(exe_path, command_line)


def is_family_launcher(family: str, title: str | None, exe_path: str | None) -> bool:
    if family == "morelogin":
        return is_morelogin_launcher(title, exe_path)
    return is_ix_launcher(title, exe_path)


def score_task_window(
    title: str,
    class_name: str,
    exe_path: str,
    *,
    family: str,
    command_line: str = "",
) -> int:
    lowered = (title or "").lower()
    if any(token in lowered for token in REJECT_TITLE_TOKENS):
        return 0
    if is_family_launcher(family, title, exe_path):
        return 0
    if is_stock_chrome_path(exe_path) and not is_family_chromium(family, exe_path, command_line):
        return 0
    if not is_family_chromium(family, exe_path, command_line):
        return 0
    score = 80
    chrome_like = (class_name or "") == "Chrome_WidgetWin_1" or (class_name or "").lower().startswith(
        "chrome_widgetwin"
    )
    if chrome_like:
        score += 5
    for hint in TASK_HINTS:
        if hint in lowered:
            score += 15
    if "chromium" in lowered:
        score += 10
    return score
