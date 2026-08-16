from label_generator import sanitize_label


def test_spec_example_sanitization():
    raw = "picking up 2 spoons and inspect handle."
    assert sanitize_label(raw) == "pick up two spoons and adjust handle"


def test_no_action_variants():
    assert sanitize_label("No Action") == "No Action"
    assert sanitize_label("no action.") == "No Action"
    assert sanitize_label("") == "No Action"
    assert sanitize_label(None) == "No Action"


def test_strips_trailing_period_and_quotes():
    assert sanitize_label('"place plate on table."') == "place plate on table"


def test_digit_map_and_numbers_above_ten():
    assert sanitize_label("grab 1 fork") == "grab one fork"
    assert sanitize_label("grab 10 forks") == "grab ten forks"
    assert sanitize_label("grab 12 forks") == "grab twelve forks"
    assert sanitize_label("move 23 plates") == "move twenty three plates"


def test_verb_corrections():
    assert sanitize_label("holding cup") == "hold cup"
    assert sanitize_label("placing bowl on table") == "place bowl on table"
    assert sanitize_label("opening drawer") == "open drawer"


def test_forbidden_word_replacements():
    assert sanitize_label("check lid") == "adjust lid"
    assert sanitize_label("examine knob") == "adjust knob"
    assert sanitize_label("reach drawer") == "move to drawer"
    assert sanitize_label("touching spoon") == "grab spoon"
    assert sanitize_label("touch knob") == "grab knob"
