"""Tests for official ATLAS guide label pipeline."""

import re

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


def test_rake_both_hands_protected_from_motion_downgrade():
    from hybrid_annotator import HandMotionProfile

    motion = HandMotionProfile(
        v_left=0.005,
        v_right=0.05,
        detected_hand="with right hand",
    )
    draft = "rake leaves on lawn with rake in both hands"
    out = atlas_guide_cleaner(draft, motion=motion)
    assert out.lower() == draft.lower()
    assert "both hands" in out.lower()


def test_generic_tool_resolved_to_hoe_for_dig():
    out = atlas_guide_cleaner("dig soil with tool in right hand")
    assert "dig soil with hoe in right hand" in out.lower()
    assert re.search(r"\btool\b", out.lower()) is None


def test_tool_backpropagates_from_later_segment_drafts():
    out = atlas_guide_cleaner(
        "dig soil with tool in right hand",
        clip_draft_blob=(
            "place bucket on floor with left hand | "
            "pick up hoe with right hand | dig soil with hoe in right hand"
        ),
    )
    assert "dig soil with hoe in right hand" in out.lower()
    assert re.search(r"\btool\b", out.lower()) is None


def test_pick_up_bucket_becomes_place_with_downward_motion():
    from hybrid_annotator import HandMotionProfile

    motion = HandMotionProfile(vy_left=0.02, vy_right=0.0, frames_analyzed=4)
    out = atlas_guide_cleaner(
        "pick up bucket with left hand",
        motion=motion,
        clip_draft_blob="place bucket on floor pick up hoe dig soil with hoe",
    )
    assert out.lower() == "place bucket on floor with left hand"


def test_pick_up_bucket_becomes_place_before_hoe_setup():
    out = atlas_guide_cleaner(
        "pick up bucket with left hand",
        next_label="pick up hoe with right hand",
        clip_draft_blob="place bucket on floor with left hand, pick up hoe with right hand",
    )
    assert out.lower() == (
        "place bucket on floor with left hand, pick up hoe with right hand"
    )


def test_inject_place_hoe_before_gather():
    out = atlas_guide_cleaner(
        "gather soil with both hands",
        previous_label="dig soil with hoe in right hand",
    )
    assert "place hoe on ground with right hand" in out.lower()
    assert "gather soil with both hands" in out.lower()


def test_cut_demoted_to_align_when_scissors_sandwiched():
    out = atlas_guide_cleaner(
        "hold paper with left hand, cut paper with scissors in right hand",
        previous_label="hold paper with left hand, hold scissors with right hand",
        next_label="hold paper with left hand, hold scissors in right hand",
    )
    assert "align papers" in out.lower()
    assert "cut paper" not in out.lower()


def test_cut_papers_becomes_align_after_scissors_hold():
    out = atlas_guide_cleaner(
        "hold papers with left hand, cut papers with scissors in right hand",
        previous_label="hold paper with left hand, hold scissors with right hand",
    )
    assert out.lower() == (
        "hold scissors with right hand, align papers with both hands"
    )


def test_real_cut_preserved_when_prior_was_cutting():
    out = atlas_guide_cleaner(
        "hold paper with left hand, cut paper with scissors in right hand",
        previous_label="hold paper with left hand, cut paper with scissors in right hand",
    )
    assert "cut paper" in out.lower()
    assert "align papers" not in out.lower()


def test_scissors_alignment_clause_order():
    out = atlas_guide_cleaner(
        "align papers with both hands, hold scissors with right hand"
    )
    assert out.lower() == (
        "hold scissors with right hand, align papers with both hands"
    )


def test_pick_up_and_place_expands_to_two_clauses():
    out = atlas_guide_cleaner("pick up and place wrench with right hand")
    assert "pick up wrench with right hand" in out.lower()
    assert "place wrench on table with right hand" in out.lower()
    assert "pick up," not in out.lower()


def test_malformed_pick_up_comma_place_repaired():
    out = atlas_guide_cleaner("pick up, place wrench with right hand")
    assert "pick up wrench with right hand" in out.lower()
    assert "place wrench on table with right hand" in out.lower()


def test_pick_up_cloth_both_hands_defaults_to_left():
    out = atlas_guide_cleaner("pick up red cloth with both hands")
    assert "pick up red cloth with left hand" in out.lower()
    assert "both hands" not in out.lower()


def test_smooth_both_hands_splits_hold_smoothen():
    draft = "smooth green cloth with both hands"
    out = atlas_guide_cleaner(draft)
    assert out.lower() == (
        "hold cloth in left hand, smoothen cloth with right hand"
    )


def test_sewing_needle_in_cap_context():
    blob = "hold cap with left hand, insert needle into patch with right hand"
    out = atlas_guide_cleaner(
        "hold cap with left hand, insert needle into patch with right hand",
        clip_draft_blob=blob,
    )
    assert "sewing needle" in out.lower()


def test_pull_after_pull_thread_segment():
    out = atlas_guide_cleaner(
        "hold cap with left hand, insert needle into patch with right hand",
        previous_label="hold cap with left hand, pull thread through patch with right hand",
        clip_draft_blob="hold cap patch thread insert needle pull thread",
    )
    assert "pull sewing needle" in out.lower()
    assert "insert sewing needle into patch" not in out.lower()


def test_no_duplicate_hand_on_tool_clause():
    draft = (
        "hold paper with left hand, cut papers with scissors in right hand"
    )
    out = atlas_guide_cleaner(draft)
    assert "in right hand with" not in out.lower()
    assert "scissors in right hand" in out.lower()


def test_no_duplicate_hand_on_strip_clause():
    draft = (
        "strip blue wire with pliers in right hand, hold blue wire with left hand"
    )
    out = atlas_guide_cleaner(
        draft,
        clip_draft_blob=draft,
    )
    assert "in right hand with" not in out.lower()
    assert "pliers in right hand" in out.lower()


def test_pass_syntax_preserved():
    draft = "pass wrench from left hand to right hand"
    out = atlas_guide_cleaner(draft)
    assert out.lower() == draft.lower()


def test_format_hand_transfer_helper():
    from label_pipeline import format_hand_transfer

    assert (
        format_hand_transfer("bottle", "right hand", "left hand")
        == "pass bottle from right hand to left hand"
    )


def test_simplify_kitchen_nouns():
    out = atlas_guide_cleaner("pick up syrup bottle with right hand")
    assert "syrup" not in out.lower()
    assert "pick up bottle with right hand" in out.lower()


def test_simplify_blue_cable_to_blue_wire():
    out = atlas_guide_cleaner("strip blue cable with pliers in right hand")
    assert "blue wire" in out.lower()
    assert "blue cable" not in out.lower()


def test_glass_hold_becomes_rotate_after_wipe_segment():
    draft = "hold glass cup with left hand, wipe glass cup with cloth in right hand"
    previous = (
        "rotate glass cup with left hand, wipe glass cup with cloth in right hand"
    )
    out = atlas_guide_cleaner(draft, previous_label=previous)
    assert out.lower().startswith("rotate glass cup")
    assert "wipe glass cup with cloth in right hand" in out.lower()


def test_glass_single_hold_becomes_rotate_during_continuous_wipe():
    previous = (
        "hold glass cup with left hand, wipe glass cup with cloth in right hand"
    )
    out = atlas_guide_cleaner(
        "hold glass cup with left hand",
        previous_label=previous,
        clip_draft_blob="glass cup wipe cloth",
    )
    assert out.lower() == "rotate glass cup with left hand"


def test_glass_hold_wipe_becomes_rotate_after_first_wipe_segment():
    previous = (
        "hold glass cup with left hand, wipe glass cup with cloth in right hand"
    )
    draft = "hold glass cup with left hand, wipe glass cup with cloth in right hand"
    out = atlas_guide_cleaner(
        draft,
        previous_label=previous,
        clip_draft_blob="glass cup wipe cloth",
    )
    assert out.lower() == (
        "rotate glass cup with left hand, wipe glass cup with cloth in right hand"
    )


def test_kitchen_bottle_pickup_injects_pass():
    draft = "open refrigerator door with right hand, pick up bottle with right hand"
    out = atlas_guide_cleaner(
        draft,
        next_label="place bottle on counter with left hand",
    )
    assert out.lower() == (
        "pick up bottle with right hand, pass bottle from right hand to left hand"
    )


def test_short_bag_pickup_place_becomes_pass():
    draft = "pick up bag with right hand, place bag on counter with right hand"
    out = atlas_guide_cleaner(draft, duration_seconds=2.0)
    assert out.lower() == (
        "pick up bag with right hand, pass bag from right hand to left hand"
    )


def test_place_bottle_uses_hand_after_prior_pass():
    previous = "pick up bottle with right hand, pass bottle from right hand to left hand"
    out = atlas_guide_cleaner(
        "place bottle on counter with right hand",
        previous_label=previous,
    )
    assert out.lower() == "place bottle on counter with left hand"


def test_sewing_stitch_cycle_expands_pull_before_insert():
    draft = "hold cap with left hand, insert sewing needle into patch with right hand"
    out = atlas_guide_cleaner(
        draft,
        clip_draft_blob="hold cap sewing needle patch thread",
    )
    assert out.lower() == (
        "hold cap with left hand, pull sewing needle with right hand, "
        "insert sewing needle into cap with right hand"
    )


def test_twist_wire_appends_trailing_pliers_pickup():
    out = atlas_guide_cleaner(
        "twist blue wire with both hands",
        next_label="pick up pliers with right hand, hold blue wire with left hand",
    )
    assert out.lower() == (
        "twist blue wire with both hands, pick up pliers with right hand"
    )


def test_wire_fold_rewrites_pickup_hold_to_shears_twist_fold():
    previous = (
        "twist blue wire with both hands, pick up pliers with right hand"
    )
    draft = "pick up pliers with right hand, hold blue wire with left hand"
    out = atlas_guide_cleaner(draft, previous_label=previous)
    assert out.lower() == (
        "hold shears with right hand, twist blue cable with both hands, "
        "fold blue cable with both hands"
    )


def test_hose_water_plant_collapses_to_both_hands():
    draft = (
        "water plant in bucket with hose in left hand, "
        "hold watering can with right hand"
    )
    out = atlas_guide_cleaner(draft)
    assert out.lower() == "water plant in bucket with hose in both hands"


def test_hose_fill_collapses_with_water_substance():
    draft = (
        "fill watering can with hose in left hand, "
        "hold watering can with right hand"
    )
    out = atlas_guide_cleaner(draft)
    assert out.lower() == "fill watering can with water with hose in both hands"


def test_set_hose_appends_watering_can_pickup():
    previous = "fill watering can with water with hose in both hands"
    out = atlas_guide_cleaner(
        "set hose on ground with left hand",
        previous_label=previous,
    )
    assert out.lower() == (
        "set hose on ground with left hand, pick up watering can with right hand"
    )


def test_set_hose_hold_can_becomes_pickup():
    out = atlas_guide_cleaner(
        "set hose on ground with left hand, hold watering can with right hand",
        previous_label="fill watering can with water with hose in both hands",
    )
    assert out.lower() == (
        "set hose on ground with left hand, pick up watering can with right hand"
    )


def test_short_sewing_tail_drops_trailing_insert():
    draft = (
        "hold cap with left hand, pull sewing needle with right hand, "
        "insert sewing needle into cap with right hand"
    )
    out = atlas_guide_cleaner(draft, duration_seconds=1.4)
    assert out.lower() == (
        "hold cap with left hand, pull sewing needle with right hand"
    )


def test_sewing_targets_drop_through_patch():
    out = atlas_guide_cleaner(
        "hold cap with left hand, pull sewing needle through patch with right hand",
        clip_draft_blob="hold cap sewing needle patch",
    )
    assert out.lower() == (
        "hold cap with left hand, pull sewing needle with right hand"
    )


def test_reposition_patch_becomes_insert_needle():
    out = atlas_guide_cleaner(
        "reposition patch on cap with both hands",
        clip_draft_blob="hold cap sewing needle patch",
    )
    assert out.lower() == "insert sewing needle into cap with right hand"


def test_glass_jar_wipe_both_hands_splits_hold_wipe():
    out = atlas_guide_cleaner(
        "wipe glass jar with cloth in both hands",
        previous_label=(
            "rotate glass cup with left hand, wipe glass cup with cloth in right hand"
        ),
        clip_draft_blob="glass cup wipe cloth",
    )
    assert out.lower() == (
        "hold glass cup with left hand, wipe glass cup with cloth in right hand"
    )
