"""Tests for official ATLAS guide label pipeline."""

from hybrid_annotator import AtlasHybridPipeline
from label_pipeline import (
    atlas_guide_cleaner,
    generate_label_hybrid,
)


def test_bimanual_hold_and_chop_preserved():
    draft = (
        "holding mushrooms on board with left hand, "
        "chopping mushrooms on board with knife in right hand"
    )
    out = atlas_guide_cleaner(draft)
    assert "hold mushrooms" in out.lower()
    assert "chop mushrooms" in out.lower()
    assert "knife in right hand" in out.lower()
    assert "left hand" in out.lower()
    assert out.count(",") >= 1


def test_place_gets_location_from_draft():
    out = atlas_guide_cleaner("placing knife on board with right hand")
    assert "place knife on board" in out.lower()
    assert "right hand" in out.lower()


def test_shift_and_pick_up_two_clauses():
    draft = "shifting plastic bag with left hand, picking up plastic bag with right hand"
    out = atlas_guide_cleaner(draft)
    assert "shift plastic bag" in out.lower()
    assert "pick up plastic bag" in out.lower()
    assert "," in out


def test_pass_and_open_bimanual():
    draft = "passing plastic bag to left hand, opening plastic bag with both hands"
    out = atlas_guide_cleaner(draft)
    assert "pass plastic bag" in out.lower()
    assert "open plastic bag" in out.lower()
    assert "both hands" in out.lower()


def test_three_action_segment_max():
    draft = (
        "holding knife with right hand, placing mushrooms in container with left hand, "
        "wiping knife with left hand"
    )
    out = atlas_guide_cleaner(draft)
    parts = [p.strip() for p in out.split(",") if p.strip()]
    assert len(parts) <= 3
    assert "hold" in out.lower()
    assert "place mushrooms in container" in out.lower()
    assert "wipe knife" in out.lower()


def test_strips_articles_and_digits():
    out = atlas_guide_cleaner("picking up the 3 spoons with right hand")
    assert "the" not in out.lower().split()
    assert "3" not in out
    assert "pick up" in out.lower()


def test_banned_adjust_becomes_shift():
    out = atlas_guide_cleaner("adjusting plastic bag with left hand")
    assert "adjust" not in out.lower()
    assert "shift" in out.lower()


def test_plural_scissors():
    out = atlas_guide_cleaner("pick up scissor with right hand")
    assert "scissors" in out.lower()


def test_generate_label_keeps_multi_clause():
    pipeline = AtlasHybridPipeline()
    try:
        label = generate_label_hybrid(
            [],
            pipeline,
            draft_label=(
                "hold bowl with left hand, scrubbing bowl with sponge in right hand"
            ),
            duration_seconds=4.0,
        )
        assert "hold bowl" in label.lower()
        assert "scrub bowl" in label.lower()
        assert label.count(",") >= 1
    finally:
        pipeline.close()


def test_state_continuity_pick_up_to_hold():
    prev = "pick up wrench with right hand"
    out = atlas_guide_cleaner(
        "pick up wrench with right hand",
        previous_label=prev,
    )
    assert "hold wrench" in out.lower()


def test_hold_not_converted_to_pick_up():
    draft = "hold wire with left hand, solder wire with soldering iron in right hand"
    out = atlas_guide_cleaner(draft)
    assert "hold wire" in out.lower()
    assert "pick up wire" not in out.lower()


def test_tool_syntax_preserved_in_hand():
    draft = "wipe exhaust pipe with cloth in left hand, hold motorcycle with right hand"
    out = atlas_guide_cleaner(draft)
    assert "with cloth in left hand" in out.lower()
    assert "with cloth with left hand" not in out.lower()


def test_no_redundant_ground_location():
    draft = "sweep ground with hand broom in both hands"
    out = atlas_guide_cleaner(draft)
    assert "on ground" not in out.lower()
    assert "sweep ground" in out.lower()


def test_bimanual_hold_preserved_for_stir():
    draft = "hold pan with left hand, stir mixture with spatula in right hand"
    out = atlas_guide_cleaner(draft)
    assert "hold pan" in out.lower()
    assert "stir mixture" in out.lower()


def test_noun_not_swapped_jar_to_cup():
    draft = (
        "place jar on counter with right hand, pick up jar with right hand, "
        "wipe jar with cloth in both hands"
    )
    out = atlas_guide_cleaner(draft)
    assert "cup" not in out.lower()
    assert "jar" in out.lower()


def test_hold_animal_not_pick_up():
    draft = "hold animal with left hand, trim animal with scissors in right hand"
    out = atlas_guide_cleaner(draft)
    assert "hold animal" in out.lower()
    assert "pick up animal" not in out.lower()


def test_smooth_not_converted_to_smoothen():
    out = atlas_guide_cleaner("smoothing shirt with right hand")
    assert "smooth shirt" in out.lower()
    assert "smoothen" not in out.lower()


def test_smooth_imperative_preserved():
    out = atlas_guide_cleaner("smooth cloth with right hand")
    assert "smooth cloth" in out.lower()
    assert "smoothen" not in out.lower()


def test_offhand_hold_added_for_cloth_work():
    out = atlas_guide_cleaner("smooth cloth with right hand")
    assert "hold cloth" in out.lower()
    assert "left hand" in out.lower()
    assert "smooth cloth with right hand" in out.lower()


def test_papers_plural_from_prior_segment():
    out = atlas_guide_cleaner(
        "shift paper with left hand",
        previous_label="hold papers with left hand",
    )
    assert "papers" in out.lower()
    assert "shift papers" in out.lower()


def test_split_both_hands_into_hold_and_wipe():
    out = atlas_guide_cleaner("wipe plate with cloth in both hands")
    assert "hold plate" in out.lower()
    assert "wipe plate" in out.lower()
    assert "left hand" in out.lower()
    assert "right hand" in out.lower()
    assert "both hands" not in out.lower()


def test_motion_corrects_false_both_hands():
    from hybrid_annotator import HandMotionProfile

    motion = HandMotionProfile(
        v_left=0.05,
        v_right=0.005,
        detected_hand="with left hand",
    )
    out = atlas_guide_cleaner("pick up sock with both hands", motion=motion)
    assert "left hand" in out.lower()
    assert "both hands" not in out.lower()
