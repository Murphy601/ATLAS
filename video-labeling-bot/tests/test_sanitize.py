from config import SYSTEM_PROMPT
from label_generator import sanitize_label


def test_spec_example_drops_inspect_instead_of_adjust():
    raw = "picking up 2 spoons and inspect handle."
    assert sanitize_label(raw) == "pick up two spoons"
    assert "adjust" not in sanitize_label(raw)


def test_no_action_variants():
    assert sanitize_label("No Action") == "No Action"
    assert sanitize_label("no action.") == "No Action"
    assert sanitize_label("") == "No Action"
    assert sanitize_label(None) == "No Action"


def test_strips_trailing_period_and_quotes():
    assert sanitize_label('"place plate on table with left hand."') == (
        "place plate on table with left hand"
    )


def test_strips_articles():
    assert (
        sanitize_label("pick up the spoon with the left hand")
        == "pick up spoon with left hand"
    )


def test_digit_map_and_numbers_above_ten():
    assert sanitize_label("pick up 1 fork with right hand") == (
        "pick up one fork with right hand"
    )
    assert sanitize_label("pick up 10 forks with right hand") == (
        "pick up ten forks with right hand"
    )
    assert sanitize_label("pick up 12 forks with right hand") == (
        "pick up twelve forks with right hand"
    )
    assert sanitize_label("move 23 plates with both hands") == (
        "move twenty three plates with both hands"
    )


def test_verb_corrections():
    assert sanitize_label("holding cup with left hand") == "hold cup with left hand"
    assert (
        sanitize_label("placing bowl on table with right hand")
        == "place bowl on table with right hand"
    )
    assert sanitize_label("opening drawer with right hand") == (
        "open drawer with right hand"
    )


def test_looking_and_banned_verbs():
    assert sanitize_label("check lid") == "No Action"
    assert sanitize_label("examine knob") == "No Action"
    assert sanitize_label("reach drawer") == "No Action"
    assert sanitize_label("adjust cloth with left hand") == "shift cloth with left hand"
    assert sanitize_label("manipulate lid with right hand") == (
        "grip lid with right hand"
    )
    assert sanitize_label("touching spoon with left hand") == (
        "hold spoon with left hand"
    )


def test_illegal_separators_and_comma_and():
    assert (
        sanitize_label(
            "pick up cup with right hand, and place cup on table with right hand"
        )
        == "pick up cup with right hand, place cup on table with right hand"
    )
    assert (
        sanitize_label("pick up cup with right hand / place cup on table with right hand")
        == "pick up cup with right hand, place cup on table with right hand"
    )


def test_plural_only_tools():
    assert sanitize_label("pick up scissor with right hand") == (
        "pick up scissors with right hand"
    )
    assert sanitize_label("hold plier with left hand") == "hold pliers with left hand"
    assert sanitize_label("pick up tongs with right hand") == (
        "pick up tongs with right hand"
    )


def test_no_action_not_mixed_with_real_action():
    assert (
        sanitize_label("No Action, pick up cup with right hand")
        == "pick up cup with right hand"
    )


def test_gold_labels_pass_through():
    gold = "hold mushrooms on board with left hand, chop mushrooms on board with knife in right hand"
    assert sanitize_label(gold) == gold
    assert (
        sanitize_label("pick up nail polish bottle with left hand")
        == "pick up nail polish bottle with left hand"
    )
    assert (
        sanitize_label("pass plastic bag to left hand, open plastic bag with both hands")
        == "pass plastic bag to left hand, open plastic bag with both hands"
    )


def test_system_prompt_bans_adjust_and_requires_hands():
    assert "HAND MANDATE" in SYSTEM_PROMPT
    assert "DO NOT USE \"adjust\"" in SYSTEM_PROMPT
    assert "scissors" in SYSTEM_PROMPT
    assert "Use \"adjust\"" not in SYSTEM_PROMPT
