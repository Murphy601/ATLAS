from esi_caption.cards import empty_cards, parse_sidebar_cards
from esi_caption.planner import timestamp_to_seconds
from esi_caption.scenes import pick_scene


def test_parse_empty_action_cards() -> None:
    names = [
        "Level 3 — Actions",
        "A1",
        "action (empty)",
        "0:00.0-0:01.5",
        "A2",
        "action (empty)",
        "0:30.3-0:31.8",
        "A3",
        "action (empty)",
        "1:07.5-1:09.0",
        "Level 2 — Segments",
        "S1",
        "result (empty)",
        "0:00.0-0:01.5",
    ]
    cards = parse_sidebar_cards(names)
    l3 = [card for card in cards if card["level"] == "L3"]
    assert [card["id"] for card in l3] == ["A1", "A2", "A3"]
    assert all(card["empty"] for card in l3)
    assert l3[0]["start_s"] == 0.0
    assert abs(l3[0]["end_s"] - 1.5) < 0.01
    assert abs(l3[1]["start_s"] - 30.3) < 0.01
    assert empty_cards(names, "L3")[0]["id"] == "A1"


def test_timestamp_roundtrip() -> None:
    assert timestamp_to_seconds("1:13.5") == 73.5
    assert timestamp_to_seconds("0:16.8") == 16.8


def test_makeup_scene_from_clock_when_id_missing() -> None:
    scene = pick_scene("Video Caption Labeling | 0 labeled", duration_s=73.5, frame_count=2208)
    assert scene.key == "makeup"
    assert scene.environment == "Home"
