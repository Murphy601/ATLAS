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
