from esi_caption.guidelines import ACTIONS, ENVIRONMENTS, HAND_BUTTONS
from esi_caption.keys import us_vk_for_char
from esi_caption.process_cdp import is_task_url, parse_debug_port


def test_environment_and_hand_lists() -> None:
    assert "Home" in ENVIRONMENTS
    assert HAND_BUTTONS["right_only"] == "Right hand only"
    assert "pick" in ACTIONS
    assert "place" in ACTIONS
    assert "open" in ACTIONS


def test_task_url() -> None:
    assert is_task_url("https://www.multimango.com/tasks/vs-1781285808-260612-esi-caption-labeling")
    assert not is_task_url("https://chathomebase.com/chat/claimed")


def test_debug_port_parse() -> None:
    assert parse_debug_port("--remote-debugging-port=9222") == 9222
    assert parse_debug_port("chrome.exe") is None


def test_us_keys_cover_caption_alphabet() -> None:
    for ch in "pick up the blue toothbrush with the right hand":
        assert us_vk_for_char(ch) is not None
