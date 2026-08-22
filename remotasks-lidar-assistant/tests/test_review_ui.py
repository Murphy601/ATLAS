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


def test_caption_field_click_skips_video_overlay() -> None:
    from review_ui import find_caption_field_click

    words = [
        {"text": "Rotate", "x": 220, "y": 310, "w": 70, "h": 18},
        {"text": "the", "x": 294, "y": 310, "w": 28, "h": 18},
        {"text": "red", "x": 326, "y": 310, "w": 28, "h": 18},
        {"text": "mayonnaise", "x": 358, "y": 310, "w": 90, "h": 18},
        {"text": "jar", "x": 452, "y": 310, "w": 28, "h": 18},
        {"text": "Rotate", "x": 180, "y": 760, "w": 70, "h": 18},
        {"text": "the", "x": 254, "y": 760, "w": 28, "h": 18},
        {"text": "red", "x": 286, "y": 760, "w": 28, "h": 18},
        {"text": "mayonnaise", "x": 318, "y": 760, "w": 90, "h": 18},
        {"text": "jar", "x": 412, "y": 760, "w": 28, "h": 18},
    ]
    hit = find_caption_field_click(words, "Rotate the red mayonnaise jar", 1575, 1050)
    assert hit is not None
    assert hit[1] > 650


def test_review_tab_is_not_a_timeline_chip() -> None:
    from review_ui import is_timeline_status_label

    assert is_timeline_status_label("done")
    assert is_timeline_status_label("pending")
    assert not is_timeline_status_label("review")
    assert not is_timeline_status_label("Review")


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
        is_clip_export_end_mismatch,
        is_clip_export_hands_error,
        is_clip_export_missing_error,
        is_grammar_row_label,
        is_idle_too_long_error,
        is_ignore_all_label,
        is_ignore_warning_label,
        is_pending_clip_label,
        is_slow_around_transitions_label,
        parse_grammar_clip_count,
        review_work_remaining,
    )

    assert parse_grammar_clip_count("Grammar 2 clips Ignore all") == 2
    assert is_grammar_row_label("Grammar 2 clips Ignore all")
    assert is_ignore_all_label("Ignore all")
    assert not is_ignore_all_label("Grammar 2 clips Ignore all")
    assert is_ignore_warning_label("Ignore")
    assert not is_ignore_warning_label("Ignore all")
    assert is_clip_export_end_mismatch("All ClipExport end must match a Sub-goal end")
    assert is_clip_export_end_mismatch("Warning All ClipExport end must match a Sub-goal end 1 clip")
    assert not is_clip_export_end_mismatch(
        "All ClipExports must be fully filled in parallel with Sub-goals"
    )
    assert is_clip_export_hands_error(
        "ClipExports must not contain hands wording like mentioning which hand/hands are being used."
    )
    assert not is_clip_export_hands_error("Pick up the jar with the left hand")
    from review_ui import is_clip_export_caption_label

    assert is_clip_export_caption_label(
        "The person stands at a kitchen counter and moves jars with both hands"
    )
    assert is_clip_export_caption_label(
        "The person stands at a kitchen counter and moves jars, a bowl, and a refrigerator door during a household task."
    )
    assert not is_clip_export_caption_label(
        "Text Annotation 1ab9: ClipExports must not contain hands wording like mentioning which hand/hands are being used.. On frames: 165."
    )
    assert not is_clip_export_caption_label(
        "Error All ClipExports must be fully filled in parallel with Sub-goals"
    )
    assert not is_clip_export_caption_label(
        "Warning All ClipExport end must match a Sub-goal end. On frames: 165."
    )
    assert not is_clip_export_caption_label(
        "Pour the black bucket from the right to the left hand and put the blue container into the middle layer of the refrigerator with the right hand"
    )
    assert is_slow_around_transitions_label("Slow around transitions")
    assert not is_slow_around_transitions_label("Playback speed (away from transitions)")
    assert is_pending_clip_label("pending")
    assert is_clip_export_missing_error(
        "All ClipExports must be fully filled in parallel with Sub-goals"
    )
    assert not is_clip_export_missing_error("ClipExport and Sub-goal clips must contain text")
    assert is_idle_too_long_error(
        "Text Annotation Sub-goal 4a01: No idle time should be more than 5s, please split it into smaller segments"
    )
    from review_ui import is_create_clip_hint, is_false_idle_review_error, is_hte_label

    assert is_create_clip_hint("click or press K to create")
    assert not is_hte_label("Clip Export")
    assert is_hte_label("Hand Tracking Error")
    assert is_false_idle_review_error(
        "All Sub-goal descriptions must contain 'left hand', 'right hand' or 'both hands' within, unless they're 'Idle'"
    )
    assert is_false_idle_review_error("Sub-goals must be at least 10 words long")
    assert is_false_idle_review_error("Please make sure the text matches with the format expected")
    assert review_work_remaining("Grammar 2 clips Ignore all")
    assert review_work_remaining("All ClipExports must be fully filled in parallel with Sub-goals")
    assert not review_work_remaining("Focused Timeline Idle Watched")


def test_idle_card_split_is_between_idle_label_and_next_pending() -> None:
    from review_ui import idle_card_split_xy, pick_idle_split_rects

    overlay_idle = (400, 220, 460, 250)
    card_idle = (80, 820, 130, 858)
    next_pending = (280, 818, 330, 856)
    idle, nxt = pick_idle_split_rects(
        [
            ("Idle", overlay_idle),
            ("Idle", card_idle),
            ("pending", next_pending),
        ],
        min_y=700,
    )
    assert idle == card_idle
    assert nxt == next_pending
    x45, y45 = idle_card_split_xy(idle, nxt, 0.45)
    assert y45 == 839
    assert 160 <= x45 <= 190
    x90, _y90 = idle_card_split_xy(idle, nxt, 0.90)
    assert x90 > x45
    assert x90 < next_pending[0]


def test_clip_export_does_not_press_k_when_pending_exists() -> None:
    from review_ui import (
        clip_export_needs_new_clip,
        is_clip_export_placeholder,
        quality_linters_remaining,
        selected_timeline_kind,
        timeline_dropdown_is_open,
    )

    assert not clip_export_needs_new_clip(
        ["ClipExport", "Focused Timeline", "pending", "Watched"]
    )
    assert clip_export_needs_new_clip(["ClipExport", "Focused Timeline", "Watched"])
    assert is_clip_export_placeholder("Focus annotation The person stands at")
    assert not is_clip_export_placeholder(
        "The person stands at a kitchen counter and handles jars."
    )
    assert timeline_dropdown_is_open(["Sub-goal", "ClipExport", "Hand Tracking Error"])
    assert selected_timeline_kind(["Sub-goal", "Sub-goal", "Play", "Review"]) == "sub-goal"
    assert selected_timeline_kind(["ClipExport", "ClipExport", "Play"]) == "clip export"
    assert quality_linters_remaining(
        [
            "All ClipExports must be fully filled in parallel with Sub-goals",
            "Text Annotation Sub-goal 4a01: No idle time should be more than 5s, please split it into smaller segments",
        ]
    )


def test_playback_and_false_idle_helpers() -> None:
    from review_ui import (
        clip_export_cut_fractions,
        clip_export_end_fractions_from_status_rects,
        clip_export_needs_parallel_splits,
        full_timeline_xy,
        playback_confirmed,
        should_recaption_false_idle,
        should_split_overlong_idle,
    )

    assert playback_confirmed(["Pause", "Review"])
    assert not playback_confirmed(["Play", "Playback speed (away from transitions)"])
    names = [
        "Error All Sub-goal descriptions must contain left hand, right hand or both hands within, unless they're Idle 1 clip",
        "Error Please make sure the text matches with the format expected 1 clip",
        "Error Sub-goals must be at least 10 words long 1 clip",
        "Error No idle time should be more than 5s, please split it into smaller segments",
        "pending",
    ]
    assert should_recaption_false_idle(names)
    assert not should_split_overlong_idle(names)
    assert should_split_overlong_idle(
        ["Error No idle time should be more than 5s, please split it into smaller segments", "Idle"]
    )
    assert clip_export_needs_parallel_splits(
        ["All ClipExports must be fully filled in parallel with Sub-goals", "ClipExport"],
        7,
    )
    fracs = clip_export_cut_fractions([5.1, 3.1, 1.8, 3.9], 4)
    assert fracs[0] < fracs[-1]
    assert 0.2 < fracs[0] < 0.5
    assert clip_export_cut_fractions(None, 6) == []
    assert clip_export_cut_fractions([], 6) == []
    ends = clip_export_end_fractions_from_status_rects(
        [(100, 800, 140, 830), (400, 800, 440, 830), (900, 800, 940, 830)],
        80,
        1400,
    )
    assert ends == [round((400 - 80) / (1400 - 80), 4), round((900 - 80) / (1400 - 80), 4)]
    from review_ui import clip_export_end_fractions_from_times, clip_export_slot_mid_fractions

    kitchen_ends = clip_export_end_fractions_from_times([5.1, 8.2, 16.9, 19.7, 22.0])
    assert kitchen_ends[0] == round(5.1 / 22.0, 4)
    assert kitchen_ends[-1] == round(19.7 / 22.0, 4)
    assert 0.20 < kitchen_ends[0] < 0.28
    mids = clip_export_slot_mid_fractions(kitchen_ends, 5)
    assert len(mids) == 5
    assert mids[0] < kitchen_ends[0] < mids[1]
    x, y = full_timeline_xy((80, 940, 120, 970), 0.02, (0, 0, 1575, 1050))
    assert x > 80
    assert y > 940


def test_sort_hits_does_not_compare_wrappers() -> None:
    from review_ui import count_subgoal_spans, sort_hits_by_y

    class TooltipWrapper:
        pass

    class ButtonWrapper:
        pass

    hits = [(120, TooltipWrapper(), "Play"), (120, ButtonWrapper(), "Play")]
    ordered = sort_hits_by_y(hits)
    assert len(ordered) == 2
    assert count_subgoal_spans(["done", "done", "done", "done"], "") == 4
    assert count_subgoal_spans(["Play", "Review"], "done done done done") == 4
    assert (
        count_subgoal_spans(
            [
                "Sub-goal",
                "Play",
                "Review",
                "QUALITY ASSISTANT",
                "done",
                "done",
                "done",
                "done",
                "done",
                "Watched",
                "Submit",
            ],
            "",
        )
        == 5
    )
