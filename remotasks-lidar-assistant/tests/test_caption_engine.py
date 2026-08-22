from caption_engine import lint_clip_export, lint_subgoal
from guidelines import idle_policy, subgoal_duration_ok


def test_forbidden_verbs_are_rejected():
    result = lint_subgoal("Inspect the shirt with the right hand")
    assert any(i.code == "banned_verb" for i in result.issues)
    result = lint_subgoal("Reach for the cup with the left hand")
    assert any(i.code == "banned_verb" for i in result.issues)


def test_using_and_while_rewritten():
    result = lint_subgoal("Wipe the table using the right hand while holding the cloth with the left hand")
    assert "with" in result.rewritten.lower()
    assert "while" not in result.rewritten.lower()
    assert "using" not in result.rewritten.lower()
    assert any(i.code == "using_not_with" for i in result.issues)
    assert any(i.code == "while_not_and" for i in result.issues)


def test_pick_up_uses_from_location():
    result = lint_subgoal("Pick up the pants on the table with the left hand")
    assert "from the table" in result.rewritten.lower()
    assert "on the table" not in result.rewritten.lower()


def test_fold_it_uses_named_object():
    result = lint_subgoal("Drop the pants with both hands and fold it with both hands")
    assert "fold the pants" in result.rewritten.lower()


def test_missing_hand_is_error():
    result = lint_subgoal("Drop the pants")
    assert any(i.code == "missing_hand" for i in result.issues)


def test_idle_and_duration_rules():
    assert subgoal_duration_ok(9.9).ok
    assert not subgoal_duration_ok(10).ok
    assert idle_policy(3) == "fold_into_next"
    assert idle_policy(5.0) == "fold_into_next"
    assert idle_policy(5.5) == "split_idle"
    assert idle_policy(6) == "split_idle"
    assert idle_policy(12) == "split_idle"
    idle = lint_subgoal("Idle", duration_s=6)
    assert idle.rewritten == "Idle"
    assert any(i.code == "idle_too_long" for i in idle.issues)


def test_max_three_actions():
    result = lint_subgoal(
        "Fold the pants with both hands, fold the shirt with both hands, "
        "put the shirt on the table with both hands, pick up the blouse with the left hand"
    )
    assert any(i.code == "too_many_actions" for i in result.issues)


def test_clip_export_from_kitchen_subgoals() -> None:
    from caption_engine import clip_export_from_subgoals, lint_clip_export

    text = clip_export_from_subgoals(
        ["Pick up the red mayonnaise jar with the left hand"]
    )
    result = lint_clip_export(text)
    assert result.ok
    assert "kitchen" in text.lower()
    ocr_blob = clip_export_from_subgoals(
        ["Sub-goal", "Focused Timeline Idle", "Pick up thY!9d mayonnaisejar"]
    )
    assert "kitchen" in ocr_blob.lower()


def test_mislabeled_idle_becomes_action_from_next_subgoal() -> None:
    from caption_engine import action_caption_for_mislabeled_idle, is_not_timeline_caption, lint_subgoal

    text = action_caption_for_mislabeled_idle(
        ["Idle", "Pick up the red mayonnaise jar with the left hand"]
    )
    assert "idle" not in text.lower()
    assert "mayonnaise" in text.lower()
    assert "hand" in text.lower()
    assert "reach for" not in text.lower()
    assert len(text.split()) >= 10
    assert lint_subgoal(text).ok
    assert is_not_timeline_caption("LLM check not yet run. QUALITY ASSISTANT")
    assert is_not_timeline_caption("Shortcuts q q fs40 Rotate")
    assert not is_not_timeline_caption("Pick up the red mayonnaise jar with the left hand")
    bad = lint_clip_export("Make a sandwich")
    assert not bad.ok
    good = lint_clip_export(
        "The person stands at a kitchen counter and prepares a sandwich by slicing bread, adding fillings, and placing it on a plate."
    )
    assert good.ok


def test_screenshot_pending_clips_follow_hand_and_imperative_rules():
    captions = [
        "Unstack the blouse with the left hand",
        "Flip the shirt with the right hand",
        "Smooth the blouse with the left hand, and transfer it to the right hand",
    ]
    for caption in captions:
        result = lint_subgoal(caption)
        assert not any(i.code == "banned_verb" for i in result.issues)
        assert not any(i.code == "missing_hand" for i in result.issues)


def test_the_both_hands_rewritten():
    result = lint_subgoal("Attach the refrigerator door with the both hands")
    assert "the both" not in result.rewritten.lower()
    assert "with both hands" in result.rewritten.lower()
    assert any(i.code == "the_both" for i in result.issues)
    assert len(result.rewritten.split()) >= 10


def test_placeholder_empty_clip_becomes_idle():
    result = lint_subgoal("click to add text")
    assert result.rewritten == "Idle"
    assert any(i.code == "empty_caption" for i in result.issues)


def test_trailing_period_and_min_words():
    result = lint_subgoal(
        "Open the refrigerator door with the left hand. Hold the red mayonnaise jar with the left hand."
    )
    assert not result.rewritten.endswith(".")
    assert " and " in result.rewritten.lower()
    assert any(i.code == "trailing_punct" for i in result.issues)
