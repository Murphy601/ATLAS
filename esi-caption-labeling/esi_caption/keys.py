"""US-keyboard virtual keys. Never Ctrl+V. Never Unicode SendInput."""

from __future__ import annotations

import random
import time

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_OEM_1 = 0xBA
VK_OEM_PLUS = 0xBB
VK_OEM_COMMA = 0xBC
VK_OEM_MINUS = 0xBD
VK_OEM_PERIOD = 0xBE
VK_OEM_2 = 0xBF
VK_OEM_3 = 0xC0
VK_OEM_4 = 0xDB
VK_OEM_5 = 0xDC
VK_OEM_6 = 0xDD
VK_OEM_7 = 0xDE


def _us_char_vk_map() -> dict[str, tuple[int, bool]]:
    mapping: dict[str, tuple[int, bool]] = {" ": (0x20, False)}
    for idx, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        mapping[letter] = (0x41 + idx, True)
        mapping[letter.lower()] = (0x41 + idx, False)
    for idx, digit in enumerate("123456789"):
        mapping[digit] = (0x31 + idx, False)
    mapping["0"] = (0x30, False)
    for digit, mark in zip("1234567890", "!@#$%^&*()"):
        mapping[mark] = (mapping[digit][0], True)
    mapping.update(
        {
            ";": (VK_OEM_1, False),
            ":": (VK_OEM_1, True),
            "=": (VK_OEM_PLUS, False),
            "+": (VK_OEM_PLUS, True),
            ",": (VK_OEM_COMMA, False),
            "<": (VK_OEM_COMMA, True),
            "-": (VK_OEM_MINUS, False),
            "_": (VK_OEM_MINUS, True),
            ".": (VK_OEM_PERIOD, False),
            ">": (VK_OEM_PERIOD, True),
            "/": (VK_OEM_2, False),
            "?": (VK_OEM_2, True),
            "`": (VK_OEM_3, False),
            "~": (VK_OEM_3, True),
            "[": (VK_OEM_4, False),
            "{": (VK_OEM_4, True),
            "\\": (VK_OEM_5, False),
            "|": (VK_OEM_5, True),
            "]": (VK_OEM_6, False),
            "}": (VK_OEM_6, True),
            "'": (VK_OEM_7, False),
            '"': (VK_OEM_7, True),
        }
    )
    return mapping


_US_CHAR_VK = _us_char_vk_map()


def us_vk_for_char(ch: str) -> tuple[int, bool] | None:
    if not ch:
        return None
    pair = _US_CHAR_VK.get(ch)
    if pair is None:
        return None
    vk, _shift = pair
    if vk == VK_CONTROL:
        return None
    return pair


def tap_vk(vk: int, *, shift: bool = False, hold_s: float = 0.04) -> None:
    import ctypes

    if vk == VK_CONTROL:
        return
    user32 = ctypes.windll.user32
    scan = user32.MapVirtualKeyW(vk, 0)
    if shift:
        user32.keybd_event(VK_SHIFT, 0, 0, 0)
    user32.keybd_event(vk, scan, 0, 0)
    time.sleep(max(hold_s, 0.02))
    user32.keybd_event(vk, scan, 2, 0)
    if shift:
        user32.keybd_event(VK_SHIFT, 0, 2, 0)


def type_text(text: str) -> None:
    from .captions import us_keyboard_text

    for ch in us_keyboard_text(text):
        if ch in {"\n", "\r", "\t"}:
            continue
        pair = us_vk_for_char(ch)
        if pair is None:
            continue
        vk, shift = pair
        tap_vk(vk, shift=shift, hold_s=random.uniform(0.02, 0.05))
        time.sleep(0.04 + random.uniform(0.01, 0.04))
