from review_ui import (
    estimated_use_point,
    find_phrase_click,
    find_review_use_clicks,
    parse_watched_percent,
)


def test_parse_watched_percent() -> None:
    assert parse_watched_percent("Watched 92%") == 92
    assert parse_watched_percent("idle") is None


def test_find_review_use_not_submit_or_video() -> None:
    words = [
        {"text": "Review", "x": 900, "y": 80, "w": 70, "h": 18},
        {"text": "Grammar", "x": 900, "y": 120, "w": 80, "h": 18},
        {"text": "Ignore", "x": 860, "y": 260, "w": 55, "h": 22},
        {"text": "Use", "x": 940, "y": 260, "w": 40, "h": 22},
        {"text": "Submit", "x": 920, "y": 720, "w": 70, "h": 24},
        {"text": "Use", "x": 80, "y": 400, "w": 40, "h": 20},
    ]
    clicks = find_review_use_clicks(words, 1100, 800)
    assert clicks == [(960, 271)]


def test_estimated_use_is_in_right_panel() -> None:
    x, y = estimated_use_point(1600, 1000)
    assert x > 1200
    assert 110 < y < 500


def test_find_click_to_add_text_on_timeline() -> None:
    words = [
        {"text": "click", "x": 80, "y": 620, "w": 40, "h": 16},
        {"text": "to", "x": 124, "y": 620, "w": 18, "h": 16},
        {"text": "add", "x": 148, "y": 620, "w": 30, "h": 16},
        {"text": "text", "x": 184, "y": 620, "w": 36, "h": 16},
        {"text": "Use", "x": 980, "y": 240, "w": 40, "h": 20},
    ]
    hit = find_phrase_click(words, "click to add text", 1100, 800)
    assert hit is not None
    assert hit[0] < 400
    assert hit[1] > 500
