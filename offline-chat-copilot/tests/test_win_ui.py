from __future__ import annotations

import time

import pytest

from offline_copilot.chathomebase import PageSnapshot, is_forbidden_click
from offline_copilot.parser import clean_client_line, is_timestamp_line as parser_is_timestamp
from offline_copilot.win_ui import (
    _escape_keys,
    describe_copilot_state,
    extract_customer_name,
    has_live_composer,
    human_key_delay_s,
    is_timestamp_line,
    keep_enumerated_window,
    latest_client_line_from_infos,
    looks_like_chat_line,
    parse_messages_from_names,
    pick_draft_edit,
    pick_logbook_save,
    pick_named_control,
    run_uia_attach,
    score_window,
    select_ix_window,
    snapshot_from_uia_names,
    us_vk_for_char,
    waiting_reason,
    walk_control_tree,
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
            {"name": "Search", "control_type": "Edit", "top": 120, "width": 200},
            {"name": "Your message is too short", "control_type": "Text", "top": 910, "left": 80, "width": 400, "height": 18},
            {"name": "", "control_type": "Edit", "top": 870, "width": 420, "left": 80},
        ],
        allow_fallback=True,
    )
    assert chosen is not None
    assert chosen["top"] == 870
    assert not is_forbidden_click(label=chosen.get("name") or "")
    assert (
        pick_draft_edit(
            [
                {"name": "Address and search bar", "control_type": "Edit", "top": 40, "width": 800},
                {"name": "Search", "control_type": "Edit", "top": 120, "width": 200},
                {"name": "", "control_type": "Edit", "top": 880, "width": 420},
            ],
            allow_fallback=False,
        )
        is None
    )
    marked = pick_draft_edit(
        [
            {"name": "", "control_type": "Edit", "top": 880, "width": 420},
            {"name": "reply", "automation_id": "messageTextArea", "control_type": "Edit", "top": 700, "width": 300},
        ],
        allow_fallback=False,
    )
    assert marked is not None
    assert marked.get("automation_id") == "messageTextArea"


def test_live_too_short_warning_is_a_claimed_chat() -> None:
    snap = snapshot_from_uia_names(
        [
            "chathomebase.com/chat/claimed",
            "Your message is too short",
            "I don't have anyone coming to clean if that is what you are thinking. I can move around by myself and have a cane and walker that I once used.",
            "You are so confident and I would really want to have that with you. Can get the idea as well?",
            "My fave place is Florence, Italy. Really old and its a great walking city.",
        ],
        title="Chat | Chat Home Base - Chromium",
    )
    assert snap.waiting is False
    assert snap.claimed is True
    assert has_live_composer(
        ["Your message is too short", "chathomebase.com/chat/claimed"]
    )


def test_waiting_room_leftover_bubbles_are_not_live() -> None:
    snap = snapshot_from_uia_names(
        [
            "Waiting for conversation to be claimed...",
            "I don't have anyone coming to clean if that is what you are thinking. I can move around by myself.",
        ],
        title="Chat | Chat Home Base - Chromium",
    )
    assert snap.waiting is True
    assert snap.claimed is False


def test_live_fallback_edit_skips_address_bar() -> None:
    assert (
        pick_draft_edit(
            [
                {"name": "Address and search bar", "control_type": "Edit", "top": 40, "width": 800},
                {"name": "Search", "control_type": "Edit", "top": 120, "width": 200},
                {"name": "", "control_type": "Edit", "top": 880, "width": 420},
            ],
            live=True,
        )
        is None
    )
    chosen = pick_draft_edit(
        [
            {"name": "Address and search bar", "control_type": "Edit", "top": 40, "width": 800},
            {"name": "Search", "control_type": "Edit", "top": 120, "width": 200},
            {"name": "Your message is too short", "control_type": "Text", "top": 910, "left": 80, "width": 400, "height": 18},
        ],
        live=True,
    )
    assert chosen is not None
    assert int(chosen["top"]) >= 220
    assert int(chosen["top"]) < 910
    assert "address" not in str(chosen.get("name") or "").casefold()
    assert "search" not in str(chosen.get("name") or "").casefold()
    bottom_search = pick_draft_edit(
        [
            {"name": "Search", "control_type": "Edit", "top": 880, "width": 220, "left": 20},
            {"name": "input-135-messages", "control_type": "Edit", "top": 860, "width": 300, "automation_id": "input-135-messages"},
            {"name": "Your message is too short", "control_type": "Text", "top": 910, "left": 80, "width": 400, "height": 18},
        ],
        live=True,
        allow_fallback=True,
    )
    assert bottom_search is not None
    assert "search" not in str(bottom_search.get("name") or "").casefold()
    assert "input-135" not in str(bottom_search.get("automation_id") or "").casefold()


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
        [
            "Chat Home Base",
            "messageTextArea",
            "messagesList",
            "messageItem",
            "chat-id",
            "USETN4695969",
            "Nthabiseng",
            "Hey! Where are you located?",
        ],
        has_edit=True,
        has_send=True,
        title="-> CHAT IS CLAIMED - Chromium",
    )
    assert live.claimed is True
    assert live.chat_id == "USETN4695969"


def test_stats_and_wishlist_pages_are_not_live() -> None:
    stats = snapshot_from_uia_names(
        [
            "USETN4695969's Personal Performance",
            "Message Statistics",
            "Get insights about your message performance within different time frames.",
            "input-135-messages",
        ],
        title="Chat | Chat Home Base - Chromium",
    )
    assert stats.waiting is True
    wish = snapshot_from_uia_names(
        [
            "user Catman19 added you to her/his Wish List",
            "PROFILE DETAILS",
            "you are",
        ],
        title="Chat | Chat Home Base - Chromium",
    )
    assert wish.waiting is True


def test_waiting_room_copy_is_not_a_claimed_chat() -> None:
    snap = snapshot_from_uia_names(
        [
            "Chat | Chat Home Base",
            "Waiting for conversation to be claimed...",
            "USETN4695969",
            "UUSETN4695969",
            "Address and search bar",
        ],
        has_edit=True,
        has_send=True,
        title="Chat | Chat Home Base - Chromium",
    )
    assert snap.waiting is True
    assert snap.claimed is False


def test_waiting_room_is_not_live_just_because_chromium_has_an_edit() -> None:
    snap = snapshot_from_uia_names(
        [
            "Chat Home Base",
            "Claimed",
            "Unclaimed",
            "chathomebase.com",
            "Search",
            "claimLoaderContainer",
        ],
        has_edit=True,
        has_send=True,
        title="chathomebase.com - Chromium",
    )
    assert snap.waiting is True
    assert snap.claimed is False
    assert snap.chat_id == ""


def test_parse_messages_skips_chrome_and_send() -> None:
    rows = parse_messages_from_names(
        [
            "SensorFusionLab",
            "Address and search bar",
            "Send",
            "chathomebase.com - Chromium",
            "Add new log",
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


def test_live_from_type_your_reply_placeholder() -> None:
    snap = snapshot_from_uia_names(
        ["Chat Home Base", "Type your reply here...", "USETN4695969"],
        title="chathomebase.com - Chromium",
    )
    assert snap.claimed is True
    assert snap.chat_id == "USETN4695969"


def test_customer_add_log_is_leftmost() -> None:
    persona = {"name": "ADD NEW LOG", "left": 900, "control_type": "Button"}
    customer = {"name": "ADD NEW LOG", "left": 80, "control_type": "Button"}
    send = {"name": "Send", "left": 10, "control_type": "Button"}
    chosen = pick_named_control([persona, customer, send], "add new log", leftmost=True)
    assert chosen is customer


def test_logbook_save_is_create_the_log_not_send() -> None:
    save = {"name": "Create the log", "control_type": "Button", "left": 200}
    send = {"name": "Send", "control_type": "Button", "left": 10}
    assert pick_logbook_save([send, save]) is save
    assert pick_logbook_save([send]) is None


def test_us_keyboard_typing_never_uses_ctrl_or_paste() -> None:
    typed = _escape_keys("I'm about 40 minutes outside of Atlanta. What's up?")
    assert "^v" not in typed.casefold()
    assert "{ENTER}" not in typed.upper()
    for ch in "I'm about 40 minutes outside of Atlanta. What's up?":
        pair = us_vk_for_char(ch)
        assert pair is not None, ch
        vk, _shift = pair
        assert vk != 0x11


def test_latest_client_line_is_the_lowest_bubble_not_old_history() -> None:
    line = latest_client_line_from_infos(
        [
            {
                "name": "I am here is because of sex, but we can build a friendship",
                "top": 220,
                "control_type": "Text",
            },
            {
                "name": "My fave place is Florence, Italy. Really old and its a great walking city.",
                "top": 700,
                "control_type": "Text",
            },
            {"name": "Your message is too short", "top": 910, "control_type": "Text"},
            {"name": "Address and search bar", "top": 40, "control_type": "Edit"},
        ]
    )
    assert "Florence" in line
    assert "i am here is because" not in line.casefold()


def test_older_mid_thread_line_is_not_the_latest() -> None:
    line = latest_client_line_from_infos(
        [
            {
                "name": "It could have been tonite but it’s on the agenda for tomorrow now",
                "top": 380,
                "left": 420,
                "width": 360,
                "control_type": "Text",
            },
            {
                "name": "I want this to be a union of love, not checking boxes off.",
                "top": 640,
                "left": 420,
                "width": 360,
                "control_type": "Text",
            },
            {"name": "Age: 75", "top": 200, "left": 40, "width": 80, "control_type": "Text"},
            {"name": "Your message is too short", "top": 910, "left": 400, "width": 400, "control_type": "Text"},
        ]
    )
    assert "union of love" in line.casefold()
    assert "tonite" not in line.casefold()
    assert "agenda" not in line.casefold()


def test_profile_fields_are_not_chat_or_latest_line() -> None:
    assert looks_like_chat_line("Rental home") is False
    assert looks_like_chat_line("Ground floor") is False
    assert looks_like_chat_line("Data analyst") is False
    line = latest_client_line_from_infos(
        [
            {"name": "Rental home", "top": 920, "left": 40, "width": 200, "control_type": "Text"},
            {"name": "Ground floor", "top": 900, "left": 40, "width": 200, "control_type": "Text"},
            {
                "name": "I would like you to start being on top of me, you kissing me working your way down",
                "top": 640,
                "left": 420,
                "width": 360,
                "control_type": "Text",
            },
            {"name": "Your message is too short", "top": 910, "left": 400, "width": 400, "control_type": "Text"},
            {"name": "Data analyst", "top": 700, "left": 1500, "width": 180, "control_type": "Text"},
        ]
    )
    assert "on top of me" in line.casefold()
    assert "rental home" not in line.casefold()
    assert "ground floor" not in line.casefold()


def test_view_1_is_not_the_customer_handle() -> None:
    assert extract_customer_name(["view_1", "you are", "Annie", "Type your reply here..."]) == ""
    assert extract_customer_name(["U USETN4695969", "you are", "Annie", "Type your reply here..."]) == ""
    assert extract_customer_name(["Bruce8111", "you are", "Annie", "Type your reply here..."]) == "Bruce8111"
    assert extract_customer_name(["Age: 75", "you are", "Annie", "Type your reply here..."]) == ""
    assert extract_customer_name(["fmsRjh9xNik3lfpt5DPC", "you are", "Annie", "Type your reply here..."]) == ""
    assert extract_customer_name(["kAt7CR5e7daLYaHMCId4", "USETN4695969", "you are"]) == ""


def test_human_typing_delay_is_slow_enough_to_avoid_auto_typing() -> None:
    assert human_key_delay_s("a", 0) >= 0.18
    assert human_key_delay_s(".", 3) >= 0.50


def test_day_month_and_short_month_stamps_are_not_latest() -> None:
    day_month = "07\u2011Aug\u20112026 \u2014 20 days ago"
    short_month = "Aug 28 (a few seconds ago)"
    assert parser_is_timestamp(day_month) is True
    assert is_timestamp_line(short_month) is True
    assert looks_like_chat_line(day_month) is False
    assert looks_like_chat_line(short_month) is False
    line = latest_client_line_from_infos(
        [
            {
                "name": "Waiting tables for a friend tonight.",
                "top": 520,
                "left": 420,
                "width": 360,
                "control_type": "Text",
            },
            {
                "name": day_month,
                "top": 700,
                "left": 420,
                "width": 280,
                "control_type": "Text",
            },
            {
                "name": short_month,
                "top": 740,
                "left": 420,
                "width": 280,
                "control_type": "Text",
            },
            {"name": "Your message is too short", "top": 910, "left": 400, "width": 400, "control_type": "Text"},
        ]
    )
    assert "waiting tables" in line.casefold()
    assert "20 days ago" not in line.casefold()
    assert "a few seconds ago" not in line.casefold()


def test_leaked_cta_is_stripped_from_latest_client_line() -> None:
    glued = (
        "That's a very sweet dick you got there. I really would love to have a taste of it"
        "g after a long day?"
    )
    cleaned = clean_client_line(glued)
    assert "taste of it" in cleaned.casefold()
    assert "after a long day" not in cleaned.casefold()
    wind_up = (
        "That's a very sweet dick you got there. I really would love to have a taste of it. "
        "Do you think that's possible? How do you usually wind up after a long day?"
    )
    stripped = clean_client_line(wind_up)
    assert "taste of it" in stripped.casefold()
    assert "do you think that's possible" in stripped.casefold()
    assert "wind up" not in stripped.casefold()
    assert "after a long day" not in stripped.casefold()
    real_day = clean_client_line("Work ran long after a long day and I still wanted to talk.")
    assert "after a long day" in real_day.casefold()
    line = latest_client_line_from_infos(
        [
            {
                "name": glued,
                "top": 640,
                "left": 420,
                "width": 360,
                "control_type": "Text",
            },
            {
                "name": "How do you usually keep things interesting after a long day?",
                "top": 680,
                "left": 420,
                "width": 360,
                "control_type": "Text",
            },
            {"name": "Your message is too short", "top": 910, "left": 400, "width": 400, "control_type": "Text"},
        ]
    )
    assert "taste of it" in line.casefold()
    assert "keep things interesting" not in line.casefold()


def test_profile_details_without_too_short_is_still_live() -> None:
    snap = snapshot_from_uia_names(
        [
            "chathomebase.com/chat/claimed",
            "PROFILE DETAILS",
            "ADD NEW LOG",
            "Waiting tables for a friend tonight.",
            "USETN4695969",
            "Yes. Are you home. If you are give me your address. I want to see you tonight.",
        ],
        title="Chat | Chat Home Base - Chromium",
    )
    assert snap.waiting is False
    assert snap.claimed is True


def test_timestamp_is_not_the_latest_client_line() -> None:
    assert is_timestamp_line("Tue, Aug 25, 2026 — a few seconds ago") is True
    assert is_timestamp_line("Tue, Aug 25, 2026 - a few seconds ago") is True
    assert looks_like_chat_line("Tue, Aug 25, 2026 — a few seconds ago") is False
    assert looks_like_chat_line("I felt that way a few seconds ago when you wrote back to me") is True
    line = latest_client_line_from_infos(
        [
            {"name": "PROFILE DETAILS", "top": 120, "left": 40, "width": 160, "control_type": "Button"},
            {
                "name": "I really felt the need to tell you that the way you use words makes me feel that you are guy whom I can trust. You make me feel secure and feel a sense of clarity. Am I making sense by saying this?",
                "top": 620,
                "left": 420,
                "width": 360,
                "control_type": "Text",
            },
            {
                "name": "Tue, Aug 25, 2026 — a few seconds ago",
                "top": 700,
                "left": 420,
                "width": 280,
                "control_type": "Text",
            },
            {"name": "Your message is too short", "top": 910, "left": 400, "width": 400, "control_type": "Text"},
            {"name": "Blond hair", "top": 500, "left": 1500, "width": 180, "control_type": "Text"},
        ]
    )
    assert "making sense" in line.casefold()
    assert "a few seconds ago" not in line.casefold()


def test_parse_skips_reply_placeholder() -> None:
    rows = parse_messages_from_names(
        [
            "Type your reply here...",
            "Your message is too short",
            "PROFILE DETAILS",
            "Where would you like to fuck and you don't have to worry about other men?",
        ]
    )
    assert len(rows) == 1
    assert "worry about other men" in rows[0]["text"]


def test_customer_name_is_the_claimed_client_not_the_persona() -> None:
    names = [
        "logbookCustomerName",
        "Dawg1953",
        "you are",
        "Lacey",
        "Type your reply here...",
        "USCA1234567",
    ]
    assert extract_customer_name(names) == "Dawg1953"
    rotated = snapshot_from_uia_names(
        ["logbookCustomerName", "Nthabiseng", "you are", "Lacey", "messageTextArea", "USZZ9999911"],
        title="chathomebase.com - Chromium",
    )
    assert rotated.customer_name == "Nthabiseng"
    assert rotated.chat_id == "USZZ9999911"


class _FakeCtrl:
    def __init__(self, name: str, kids: tuple["_FakeCtrl", ...] = ()) -> None:
        self.name = name
        self.kids = kids


def test_waiting_reason_uses_live_site_copy() -> None:
    assert waiting_reason(
        ["Waiting for conversation to be claimed..."],
        "Chat | Chat Home Base - Chromium",
    ) == "waiting for conversation to be claimed"


def test_describe_state_keeps_talking_on_waiting_and_timeout() -> None:
    waiting = snapshot_from_uia_names(
        ["Waiting for conversation to be claimed..."],
        title="Chat | Chat Home Base - Chromium",
    )
    line = describe_copilot_state(waiting, ["Waiting for conversation to be claimed..."])
    assert "Waiting room" in line
    assert "Not typing" in line
    stuck = describe_copilot_state(PageSnapshot(waiting=True), [], named_count=0, timed_out=True)
    assert "retrying" in stuck.casefold()
    live = snapshot_from_uia_names(
        ["Type your reply here...", "USETN4695969", "Dawg1953"],
        title="-> CHAT IS CLAIMED - Chromium",
    )
    live.customer_name = "Dawg1953"
    assert "Live claim" in describe_copilot_state(live, ["Type your reply here...", "USETN4695969"])


def test_walk_control_tree_respects_deadline_and_children() -> None:
    child = _FakeCtrl("Type your reply here...")
    root = _FakeCtrl("window", (child,))
    found = walk_control_tree(
        root,
        get_children=lambda node: node.kids,
        deadline=time.monotonic() + 5,
    )
    assert [node.name for node in found] == ["window", "Type your reply here..."]
    expired = walk_control_tree(
        root,
        get_children=lambda node: node.kids,
        deadline=time.monotonic() - 1,
    )
    assert expired == []
