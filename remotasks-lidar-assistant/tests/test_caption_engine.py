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
    assert idle_policy(6) == "idle_own_clip"
    assert idle_policy(12) == "split_idle"
    idle = lint_subgoal("Idle", duration_s=6)
    assert idle.rewritten == "Idle"


def test_max_three_actions():
    result = lint_subgoal(
        "Fold the pants with both hands, fold the shirt with both hands, "
        "put the shirt on the table with both hands, pick up the blouse with the left hand"
    )
    assert any(i.code == "too_many_actions" for i in result.issues)


def test_clip_export_needs_environment_and_sentences():
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
