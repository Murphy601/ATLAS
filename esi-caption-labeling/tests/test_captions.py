from esi_caption.captions import l1_caption, l2_caption, l3_caption, lint_caption, captions_too_similar
from esi_caption.guidelines import is_forbidden_click


def test_l3_hand_phrasing() -> None:
    text = l3_caption(
        action="pick",
        obj="the blue toothbrush on the right side of the table",
        target=None,
        hand="right_only",
    )
    assert text == "pick up the blue toothbrush on the right side of the table with the right hand"
    assert lint_caption("L3", text) == ""


def test_l3_skip_target_on_pick() -> None:
    text = l3_caption(
        action="pick",
        obj="the brown beer bottle on the left side of the purple mug",
        target="the table",
        hand="left_only",
    )
    assert "table" not in text
    assert lint_caption("L3", text) == ""


def test_l3_tool_and_place_slot() -> None:
    text = l3_caption(
        action="open",
        obj="the brown beer bottle",
        target=None,
        hand="right_only",
        tool="the black bottle opener",
    )
    assert "black bottle opener" in text
    assert "with the right hand" in text
    assert lint_caption("L3", text) == ""


def test_l3_both_hands_different() -> None:
    text = l3_caption(
        action="hold",
        obj="the brown beer bottle",
        target=None,
        hand="both_diff",
        left_action="hold",
        left_object="the brown beer bottle",
        right_action="pick",
        right_object="the black bottle opener from the purple mug",
    )
    assert "with the left hand, and" in text
    assert "with the right hand" in text
    assert lint_caption("L3", text) == ""


def test_l2_does_not_name_a_hand() -> None:
    text = l2_caption(
        verb="move",
        obj="the purple toothbrush",
        target="the bottom left slot of the organizer",
        extra="move the purple toothbrush from the table to the bottom left slot of the organizer",
    )
    assert "hand" not in text
    assert lint_caption("L2", text) == ""


def test_l1_episode() -> None:
    text = l1_caption("Organize the makeup tools in the mini organizer on the desk")
    assert text.startswith("organize")
    assert not text.endswith(".")
    assert lint_caption("L1", text) == ""


def test_lint_rejects_run_on_l3() -> None:
    bad = "pick up the green turtle at the bottom with both hands and place it on the bed"
    assert lint_caption("L3", bad)


def test_lint_rejects_gripper_and_period() -> None:
    assert lint_caption("L3", "pick up the cup with the gripper.")
    assert lint_caption("L3", "Picking up the cup with the right hand")


def test_repeated_captions_blocked() -> None:
    same = ["organize the makeup tools with both hands"] * 6
    assert captions_too_similar(same) is True
    distinct = [
        "pick up the blue toothbrush on the right side of the table with the right hand",
        "place the blue toothbrush in the top mid slot of the organizer with the right hand",
        "pick up the red toothbrush on the right side of the table with the right hand",
    ]
    assert captions_too_similar(distinct) is False


def test_never_click_skip_or_flag() -> None:
    assert is_forbidden_click("Skip") is True
    assert is_forbidden_click("Flag bad video") is True
    assert is_forbidden_click("Flag for removal") is True
    assert is_forbidden_click("Submit Captions (2 segs)") is False
    assert is_forbidden_click("Generate with AI") is False
    assert is_forbidden_click("no placement destination / object not moving / no object") is False
