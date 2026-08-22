from review_ui import (
    estimated_use_point,
    find_phrase_click,
    find_review_use_clicks,
    interesting_uia_names,
    is_empty_clip_label,
    is_quality_empty_error,
    is_review_use_label,
    parse_watched_percent,
    should_skip_watch,
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


def test_play_is_not_playback_speed() -> None:
    from review_ui import is_pause_control_label, is_play_control_label

    assert is_play_control_label("Play")
    assert not is_play_control_label("Playback speed (away from transitions)")
    assert not is_play_control_label("Playback mode")
    assert is_pause_control_label("Pause")
    assert not is_pause_control_label("Play")


def test_use_and_empty_clip_labels() -> None:
    assert is_review_use_label("Use")
    assert is_review_use_label("Use suggestion")
    assert not is_review_use_label("User")
    assert not is_review_use_label("Submit")
    assert not is_review_use_label("Find & Replace")
    assert is_empty_clip_label("click to add text")
    assert is_empty_clip_label("review 5.5s click to add text")
    assert is_empty_clip_label("(empty clip)")
    assert not is_empty_clip_label("Pick up the jar")


def test_quality_empty_error_and_skip_watch() -> None:
    assert is_quality_empty_error("ClipExport and Sub-goal clips must contain text")
    assert not is_quality_empty_error("All ClipExports must be fully filled in parallel with Sub-goals")
    assert not is_quality_empty_error("Sub-goals must be at least 10 words long")
    assert should_skip_watch(100, use_ready=False, quality_ready=False)
    assert should_skip_watch(None, use_ready=True, quality_ready=False)
    assert should_skip_watch(None, use_ready=False, quality_ready=True)
    assert not should_skip_watch(None, use_ready=False, quality_ready=False)
    assert not should_skip_watch(12, use_ready=False, quality_ready=False)


def test_interesting_uia_names_prefer_review_controls() -> None:
    names = ["Chrome", "Address", "Use", "click to add text", "New Tab"]
    out = interesting_uia_names(names)
    assert "Use" in out
    assert "click to add text" in out


def test_grammar_advance_and_remaining_work() -> None:
    from review_ui import (
        is_clip_export_missing_error,
        is_grammar_row_label,
        is_idle_too_long_error,
        is_ignore_all_label,
        is_pending_clip_label,
        parse_grammar_clip_count,
        review_work_remaining,
    )

    assert parse_grammar_clip_count("Grammar 2 clips Ignore all") == 2
    assert is_grammar_row_label("Grammar 2 clips Ignore all")
    assert is_ignore_all_label("Ignore all")
    assert not is_ignore_all_label("Grammar 2 clips Ignore all")
    assert is_pending_clip_label("pending")
    assert is_clip_export_missing_error(
        "All ClipExports must be fully filled in parallel with Sub-goals"
    )
    assert not is_clip_export_missing_error("ClipExport and Sub-goal clips must contain text")
    assert is_idle_too_long_error(
        "No idle time should be more than 5s, please split it into smaller segments"
    )
    assert review_work_remaining("Grammar 2 clips Ignore all")
    assert review_work_remaining("All ClipExports must be fully filled in parallel with Sub-goals")
    assert not review_work_remaining("Focused Timeline Idle Watched")
