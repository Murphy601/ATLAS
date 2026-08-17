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


def test_unknown_work_verbs_with_hands_are_kept():
    assert sanitize_label("dig soil with tool in right hand") == (
        "dig soil with tool in right hand"
    )
    assert sanitize_label("scoop dirt with shovel in left hand") == (
        "scoop dirt with shovel in left hand"
    )
    gold = "hold mushrooms on board with left hand, chop mushrooms on board with knife in right hand"
    assert sanitize_label(gold) == gold
    trim = "hold animal with left hand, trim animal with scissors in right hand"
    assert sanitize_label(trim) == trim
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
    assert "both hands" in SYSTEM_PROMPT
    assert "hold paper with left hand" in SYSTEM_PROMPT
    assert "Instrumental pickup" in SYSTEM_PROMPT or "Instrumental Pickup" in SYSTEM_PROMPT
    assert 'NEVER write generic "animal"' in SYSTEM_PROMPT
    assert '"tool" FAILS audit' in SYSTEM_PROMPT
    assert "five seconds" in SYSTEM_PROMPT
    assert "OFF-HAND CLAUSE" in SYSTEM_PROMPT
    assert "pass cup from left hand to right hand" in SYSTEM_PROMPT
    assert "seal snacks bag with both hands" in SYSTEM_PROMPT
    assert "NO PRONOUNS" in SYSTEM_PROMPT
    assert 'USE "grab" NEVER' in SYSTEM_PROMPT


def test_action_system_prompt_forbids_no_action():
    from config import ACTION_SYSTEM_PROMPT

    assert "five seconds" in ACTION_SYSTEM_PROMPT
    assert 'or "No Action"' not in ACTION_SYSTEM_PROMPT
    assert "EXTRA ACTION" in ACTION_SYSTEM_PROMPT
    assert "MISSING ACTION" in ACTION_SYSTEM_PROMPT
    assert "hold carrot with left hand" in ACTION_SYSTEM_PROMPT
    assert "grab → pick up" in ACTION_SYSTEM_PROMPT


def test_collapses_cooperating_hands_into_one_both_hands_action():
    assert sanitize_label(
        "water plant in bucket with hose in left hand, hold watering can with right hand"
    ) == "water plant in bucket with hose in both hands"
    assert sanitize_label(
        "fill watering can with hose in left hand, hold watering can with right hand"
    ) == "fill watering can with water with hose in both hands"


def test_keeps_off_hand_hold_while_the_other_hand_works():
    gold = "hold paper with left hand, cut paper with scissors in right hand"
    assert sanitize_label(gold) == gold
    assert sanitize_label(
        "cut paper with scissors in right hand, hold paper with left hand"
    ) == "cut paper with scissors in right hand, hold paper with left hand"


def test_keeps_two_actions_when_one_hand_sets_and_the_other_holds():
    assert sanitize_label(
        "place hose on ground with left hand, hold watering can with right hand"
    ) == "place hose on ground with left hand, hold watering can with right hand"


def test_does_not_collapse_stabilize_then_work():
    gold = (
        "hold mushrooms on board with left hand, "
        "chop mushrooms on board with knife in right hand"
    )
    assert sanitize_label(gold) == gold


def test_place_on_ground_stays_place():
    assert sanitize_label("place hoe on ground with right hand") == (
        "place hoe on ground with right hand"
    )
    assert sanitize_label("place bucket on floor with left hand") == (
        "place bucket on floor with left hand"
    )


def test_strips_narrative_words():
    assert "other" not in sanitize_label(
        "move soil from pot to other pot with trowel in right hand"
    ).lower()


def test_replaces_generic_tool_from_previous_label():
    from label_generator import apply_context_fixes

    assert apply_context_fixes(
        "dig soil with tool in right hand",
        previous_label="place bucket on floor with left hand, pick up hoe with right hand",
    ) == "dig soil with hoe in right hand"


def test_reconcile_keeps_pick_up_draft_instead_of_trailing_hold():
    from label_generator import reconcile_with_draft

    assert reconcile_with_draft(
        "cut paper with scissors in right hand, hold paper with left hand",
        "cut paper with scissors in right hand",
    ) == "cut paper with scissors in right hand, hold paper with left hand"
    assert reconcile_with_draft(
        "set hose on ground with left hand, hold watering can with right hand",
        "set hose on ground with left hand, pick up watering can with right hand",
    ) == "set hose on ground with left hand, pick up watering can with right hand"


def test_usable_draft_ignores_no_action():
    from label_generator import usable_draft

    assert usable_draft("No Action") is None
    assert usable_draft("  no action  ") is None
    assert usable_draft("") is None
    assert usable_draft("pick up sock with both hands") == "pick up sock with both hands"


def test_model_fits_draft_rejects_wrong_objects():
    from label_generator import model_fits_draft

    plate = "rotate glass plate with both hands"
    toy = (
        "hold stuffed animal with left hand, trim stuffed animal with scissors in right hand"
    )
    assert not model_fits_draft(toy, plate)
    assert model_fits_draft(
        "wipe glass plate with cloth in right hand, hold glass plate with left hand",
        "wipe glass plate with cloth in right hand, hold glass plate with left hand",
    )
    assert model_fits_draft(toy, None)
    assert model_fits_draft(toy, "No Action")


def test_choose_final_label_is_draft_first():
    from label_generator import choose_final_label

    plate = "rotate glass plate with both hands"
    toy = (
        "hold stuffed animal with left hand, trim stuffed animal with scissors in right hand, "
        "pass scissors from right hand to left hand"
    )
    assert choose_final_label(toy, plate) == plate
    assert choose_final_label("No Action", plate) == plate
    assert choose_final_label(
        "hold stuffed animal with left hand, trim stuffed animal with scissors in right hand, "
        "pass scissors from right hand to left hand",
        "hold animal with left hand, trim animal with scissors in right hand",
    ) == (
        "hold stuffed animal with left hand, trim stuffed animal with scissors in right hand"
    )
    leftover = (
        "hold stuffed animal with left hand, trim stuffed animal with scissors in right hand"
    )
    dish = (
        "hold glass plate with left hand, wipe glass plate with cloth in right hand"
    )
    assert (
        choose_final_label(
            "wipe glass plate with cloth in right hand",
            leftover,
            frames_have_video=True,
        )
        == dish
    )
    assert choose_final_label(
        "wipe glass plate with cloth in right hand", leftover
    ) == leftover


def test_reconcile_does_not_keep_generic_animal_draft():
    from label_generator import (
        is_generic_placeholder_label,
        reconcile_with_draft,
        rewrite_generic_animal_draft,
    )

    animal = "hold animal with left hand, trim animal with scissors in right hand"
    stuffed = (
        "hold stuffed animal with left hand, trim stuffed animal with scissors in right hand"
    )
    species = "hold sheep with left hand, trim wool with scissors in right hand"
    assert is_generic_placeholder_label(animal)
    assert not is_generic_placeholder_label(species)
    assert not is_generic_placeholder_label(stuffed)
    assert rewrite_generic_animal_draft(animal) == stuffed
    assert rewrite_generic_animal_draft(stuffed) == stuffed
    assert reconcile_with_draft(species, animal) == species
    assert reconcile_with_draft(
        "cut paper with scissors in right hand, hold paper with left hand",
        animal,
    ) == "cut paper with scissors in right hand, hold paper with left hand"


def test_strips_instrumental_pickup_before_immediate_use():
    assert sanitize_label(
        "pick up hose with right hand, water plant with hose in right hand"
    ) == "water plant with hose in right hand"
    assert sanitize_label(
        "pick up iron with right hand, iron shirt with right hand"
    ) == "iron shirt with right hand"
    assert sanitize_label(
        "pick up wrench with right hand, place wrench on table with right hand"
    ) == "pick up wrench with right hand, place wrench on table with right hand"
    assert sanitize_label(
        "pick up scissors with right hand, cut paper with scissors in right hand"
    ) == "cut paper with scissors in right hand"
    assert sanitize_label(
        "hold plate with left hand, pick up cloth with right hand, "
        "wipe plate with cloth in right hand"
    ) == "hold plate with left hand, wipe plate with cloth in right hand"
    assert sanitize_label(
        "grab hose with right hand, water plant with hose in right hand"
    ) == "water plant with hose in right hand"


def test_strips_micro_movement_during_continuous_work():
    assert sanitize_label(
        "cut paper with scissors in right hand, shift paper with left hand"
    ) == "cut paper with scissors in right hand"
    assert sanitize_label(
        "hold paper with left hand, cut paper with scissors in right hand, "
        "shift paper with left hand"
    ) == "hold paper with left hand, cut paper with scissors in right hand"
    assert sanitize_label(
        "wipe plate with cloth in right hand, rotate plate with left hand"
    ) == "wipe plate with cloth in right hand, rotate plate with left hand"
    assert sanitize_label(
        "shift plastic bag with left hand, pick up plastic bag with right hand"
    ) == "shift plastic bag with left hand, pick up plastic bag with right hand"


def test_caps_labels_at_three_actions():
    assert sanitize_label(
        "hold bowl with left hand, stir soup with spoon in right hand, "
        "wipe rim with left hand, tap bowl with right hand"
    ) == (
        "hold bowl with left hand, stir soup with spoon in right hand, "
        "wipe rim with left hand"
    )
    assert sanitize_label(
        "hold bowl with left hand, stir soup with spoon in right hand, "
        "wipe rim with left hand, place bowl on table with left hand"
    ) == (
        "hold bowl with left hand, stir soup with spoon in right hand, "
        "place bowl on table with left hand"
    )


def test_collapses_same_tool_hold_but_keeps_workpiece_stabilize():
    assert sanitize_label(
        "dig soil with hoe in right hand, hold hoe with left hand"
    ) == "dig soil with hoe in both hands"
    gold = "hold paper with left hand, cut paper with scissors in right hand"
    assert sanitize_label(gold) == gold


def test_attaches_object_to_bare_place():
    assert sanitize_label(
        "pick up cup with right hand, place on table with right hand"
    ) == "pick up cup with right hand, place cup on table with right hand"
    assert sanitize_label(
        "pick up cup, place cup on table with right hand"
    ) == "pick up cup with right hand, place cup on table with right hand"


def test_keeps_workpiece_pickup_before_wipe():
    assert sanitize_label(
        "pick up plate with left hand, wipe plate with cloth in right hand"
    ) == (
        "pick up plate with left hand, wipe plate with cloth in right hand"
    )


def test_choose_final_label_drops_extra_pickup_keeps_missing_place():
    from label_generator import choose_final_label

    draft = "water plant with hose in right hand"
    bloated = (
        "pick up watering can with right hand, water plant with hose in right hand"
    )
    assert choose_final_label(bloated, draft) == draft
    short = "pick up wrench with right hand"
    with_place = (
        "pick up wrench with right hand, place wrench on table with right hand"
    )
    assert choose_final_label(with_place, short) == with_place


def test_splits_false_both_hands_on_dish_wipe():
    assert sanitize_label("wipe plate with both hands") == (
        "hold plate with left hand, wipe plate with cloth in right hand"
    )
    assert sanitize_label("hold plate with both hands, wipe plate with right") == (
        "hold plate with left hand, wipe plate with cloth in right hand"
    )
    gold = (
        "hold glass plate with left hand, wipe glass plate with cloth in right hand"
    )
    assert sanitize_label(gold) == gold
    assert sanitize_label("wipe glass plate with cloth in right hand") == gold


def test_does_not_split_true_both_hands_work():
    assert sanitize_label("unfold red shirt with both hands") == (
        "unfold red shirt with both hands"
    )
    assert sanitize_label("work dough with both hands") == "work dough with both hands"
    assert sanitize_label(
        "water plant in bucket with hose in left hand, hold watering can with right hand"
    ) == "water plant in bucket with hose in both hands"
    assert sanitize_label("rotate glass plate with both hands") == (
        "rotate glass plate with both hands"
    )


def test_aligns_bowl_to_plate_and_restores_hold_wipe():
    from label_generator import apply_context_fixes, choose_final_label

    prev = "hold plate with left hand, wipe plate with cloth in right hand"
    assert apply_context_fixes(
        "hold bowl with both hands", previous_label=prev
    ) == prev
    glass_prev = (
        "hold glass plate with left hand, wipe glass plate with cloth in right hand"
    )
    assert apply_context_fixes(
        "hold bowl with both hands", previous_label=glass_prev
    ) == glass_prev
    model = (
        "hold glass plate with left hand, wipe glass plate with cloth in right hand"
    )
    assert choose_final_label(model, "wipe plate with both hands") == model
    assert choose_final_label(
        "wipe plate with both hands", "wipe plate with both hands"
    ) == "hold plate with left hand, wipe plate with cloth in right hand"


def test_official_atlas_format_examples():
    assert sanitize_label("Sealing their snacks bag with their hands") == (
        "seal snacks bag with both hands"
    )
    assert sanitize_label("wash spoon with fingers") == "wash spoon with right hand"
    gold = "hold carrot with left hand, cut carrot with right hand"
    assert sanitize_label(gold) == gold
    assert sanitize_label(
        "pick up cup with right hand / place cup on table with right hand"
    ) == "pick up cup with right hand, place cup on table with right hand"


def test_rewrites_hand_change_as_pass():
    from label_generator import apply_context_fixes

    assert apply_context_fixes(
        "hold cup with right hand",
        previous_label="hold cup with left hand",
    ) == "pass cup from left hand to right hand"


def test_keeps_cleaning_verb_consistent():
    from label_generator import apply_context_fixes

    assert apply_context_fixes(
        "wipe plate with cloth in right hand",
        previous_label="wash plate with cloth in right hand",
    ) == "wash plate with cloth in right hand"


def test_adds_place_location_from_previous_or_set_ground():
    from label_generator import apply_context_fixes

    assert apply_context_fixes(
        "place cup with right hand",
        previous_label="pick up cup on table with right hand",
    ) == "place cup on table with right hand"
    assert sanitize_label("set hoe with right hand") == "set hoe on ground with right hand"


def test_short_window_does_not_keep_no_action_over_work_draft():
    from label_generator import choose_final_label

    draft = "seal snacks bag with both hands"
    assert choose_final_label(
        "No Action",
        draft,
        frames_have_video=True,
        duration_seconds=3.0,
    ) == draft
    assert choose_final_label(
        "No Action",
        draft,
        frames_have_video=True,
        duration_seconds=7.4,
    ) == "No Action"


def test_practice_golds_cloth_book_and_rake():
    from label_generator import apply_context_fixes, choose_final_label

    assert sanitize_label("fold cloth with both hands") == (
        "hold cloth in left hand, smoothen cloth with right hand"
    )
    assert sanitize_label("fold garment on table with both hands") == (
        "fold garment on table with both hands"
    )
    assert sanitize_label("erase book with eraser in right hand") == (
        "hold book with left hand, wipe book with cloth in right hand"
    )
    assert sanitize_label("rake leaves with both hands") == (
        "rake leaves on ground with rake in both hands"
    )
    assert choose_final_label(
        "pick up cloth with both hands",
        "place cloth on shelf with both hands",
    ) == "place cloth on shelf with both hands"
    assert apply_context_fixes(
        "pick up cloth with left hand",
        previous_label="pick up red cloth with left hand",
    ) == "pick up red cloth with left hand"


def test_splits_glass_cup_wipe_and_keeps_iron_shirt():
    from label_generator import apply_context_fixes, choose_final_label

    assert sanitize_label("wipe glass with cloth in both hands") == (
        "hold glass cup with left hand, wipe glass cup with cloth in right hand"
    )
    assert sanitize_label("wipe glass cup with cloth in both hands") == (
        "hold glass cup with left hand, wipe glass cup with cloth in right hand"
    )
    assert sanitize_label("wipe glass door with cloth in both hands") == (
        "wipe glass door with cloth in both hands"
    )
    assert sanitize_label("iron shirt with right hand") == "iron shirt with right hand"
    prev = (
        "hold glass cup with left hand, wipe glass cup with cloth in right hand"
    )
    assert apply_context_fixes(
        "hold glass with both hands", previous_label=prev
    ) == (
        "rotate glass cup with left hand, wipe glass cup with cloth in right hand"
    )
    assert choose_final_label(
        "wipe glass with cloth in both hands",
        "wipe glass with cloth in both hands",
    ) == prev


def test_keeps_cap_needle_draft_over_hat_pen_hallucination():
    from label_generator import choose_final_label

    draft = "hold cap with left hand, insert needle into patch with right hand"
    hallucinated = "hold hat with left hand, write on hat with pen in right hand"
    assert (
        choose_final_label(hallucinated, draft, frames_have_video=True) == draft
    )


def test_keeps_trailing_pickup_and_strip_draft():
    from label_generator import apply_context_fixes, choose_final_label

    assert choose_final_label(
        "twist blue wire with both hands, pick up pliers with right hand",
        "twist blue wire with both hands",
    ) == "twist blue wire with both hands, pick up pliers with right hand"
    assert apply_context_fixes(
        "twist blue wire with both hands",
        next_label="pick up pliers with right hand, hold blue wire with left hand",
    ) == "twist blue wire with both hands, pick up pliers with right hand"
    strip = "strip blue wire with pliers in right hand, hold wire with left hand"
    assert choose_final_label(
        "hold blue wire with left hand, twist blue wire with pliers in right hand",
        strip,
        previous_label="hold blue wire with left hand, twist blue wire with pliers in right hand",
        frames_have_video=True,
        ) == "strip blue wire with pliers in right hand, hold wire with left hand"


def test_keeps_mop_floor_draft_over_hold_toy():
    from label_generator import choose_final_label

    assert (
        choose_final_label(
            "hold toy with both hands",
            "mop floor with both hands",
            frames_have_video=True,
        )
        == "mop floor with both hands"
    )
    assert (
        choose_final_label(
            "hold mop with both hands",
            "mop floor with both hands",
            frames_have_video=True,
        )
        == "mop floor with both hands"
    )


def test_practice_golds_hose_scissors_stir_and_fridge():
    from label_generator import choose_final_label

    prev_fill = "fill watering can with water with hose in both hands"
    assert choose_final_label(
        "hold hose with both hands",
        "set hose on ground with left hand",
        previous_label=prev_fill,
        frames_have_video=True,
    ) == "set hose on ground with left hand, pick up watering can with right hand"

    hold_scissors = "hold paper with left hand, hold scissors in right hand"
    assert choose_final_label(
        "hold paper with left hand, cut plastic bag with scissors in right hand",
        hold_scissors,
        frames_have_video=True,
    ) == sanitize_label(hold_scissors)

    assert choose_final_label(
        "cut paper with scissors in right hand, hold paper with left hand",
        "hold paper with left hand, cut paper with scissors in right hand",
        previous_label="hold paper with left hand, hold scissors with right hand",
        frames_have_video=True,
    ) == "hold scissors with right hand, align papers with both hands"

    assert sanitize_label(
        "hold pan with left hand, stir food in pan with spoon in right hand"
    ) == "stir food in pan with spoon in right hand"
    assert choose_final_label(
        "hold pan with left hand, stir food in pan with spoon in right hand",
        "stir meat and onions with ladle in right hand",
        frames_have_video=True,
    ) == "stir meat and onions with ladle in right hand"

    assert choose_final_label(
        "open refrigerator door with right hand, pick up red bottle with right hand",
        "place syrup bottle on counter with right hand",
        frames_have_video=True,
    ) == "place syrup bottle on counter with right hand"

    assert choose_final_label(
        "pick up red bottle with right hand, close refrigerator door with left hand",
        "pick up red snack bag with right hand, place red snack bag on counter with right hand",
        previous_label="pick up red bottle with right hand, close refrigerator door with left hand",
        frames_have_video=True,
    ) == (
        "pick up red snack bag with right hand, "
        "place red snack bag on counter with right hand"
    )

    assert sanitize_label(
        "pick up red bottle with right hand, close refrigerator door with left hand"
    ) == "pick up red bottle with right hand, pass red bottle from right hand to left hand"


def test_fills_missing_object_noun_and_rejects_bare_verb():
    from label_generator import validate_clause_syntax

    assert not validate_clause_syntax("pick up with right hand")
    assert validate_clause_syntax("pick up wrench with right hand")
    assert sanitize_label(
        "pick up with right hand, place wrench on table with right hand"
    ) == "pick up wrench with right hand, place wrench on table with right hand"


def test_inserts_pass_when_object_changes_hands():
    assert sanitize_label(
        "pick up wrench with left hand, place wrench on table with right hand"
    ) == (
        "hold wrench with left hand, pass wrench from left hand to right hand, "
        "place wrench on table with right hand"
    )
    assert sanitize_label(
        "pick up wrench with right hand, place wrench on table with right hand"
    ) == "pick up wrench with right hand, place wrench on table with right hand"


def test_keeps_hold_scissors_instead_of_pick_up_or_copied_align():
    from label_generator import choose_final_label

    hold = "hold papers with left hand, hold scissors with right hand"
    assert choose_final_label(
        "hold papers with left hand, pick up scissors with right hand",
        hold,
        frames_have_video=True,
    ) == hold
    assert choose_final_label(
        "hold scissors with right hand, align papers with both hands",
        hold,
        previous_label="hold scissors with right hand, align papers with both hands",
        frames_have_video=True,
    ) == hold


def test_completes_bucket_hoe_and_keeps_draft_tools():
    from label_generator import apply_context_fixes, choose_final_label

    assert apply_context_fixes(
        "place bucket on ground with left hand"
    ) == "place bucket on floor with left hand, pick up hoe with right hand"
    assert apply_context_fixes(
        "dig soil on ground with both hands",
        previous_label="dig soil with hoe in right hand",
    ) == "place hoe on ground with right hand, gather soil with both hands"
    assert sanitize_label(
        "dig soil on ground with right hand, pick up soil with left hand"
    ) == "dig soil with hoe in right hand"
    assert apply_context_fixes(
        "dig soil with bucket in right hand",
        previous_label="place bucket on floor with left hand, pick up hoe with right hand",
    ) == "dig soil with hoe in right hand"
    assert choose_final_label(
        "pick up wrench from toolbox with right hand, place wrench on table with right hand",
        "pick up metal pin and place metal pin on table with right hand",
        frames_have_video=True,
    ) == "pick up metal pin with right hand, place metal pin on table with right hand"
