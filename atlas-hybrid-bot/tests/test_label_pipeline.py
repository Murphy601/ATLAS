"""Tests for minimalist do-no-harm label pipeline."""

from label_pipeline import (
    generate_label_hybrid,
    minimal_atlas_cleaner,
    resolve_hand_tag,
)
from hybrid_annotator import AtlasHybridPipeline


def test_minimal_cleaner_user_example():
    out = minimal_atlas_cleaner(
        "picking up glass cleaner pouch and wiping table with right hand",
        "with right hand",
    )
    assert out == "pick up glass cleaner pouch with right hand"


def test_minimal_cleaner_keeps_draft_nouns():
    out = minimal_atlas_cleaner(
        "sweep ground with hand broom in both hands",
        "with both hands",
    )
    assert "ground" in out
    assert "hand broom" in out
    assert out.count(",") == 0
    assert out.endswith("with both hands")
    assert "in both hands" not in out.lower() or out.endswith("with both hands")


def test_minimal_cleaner_first_clause_only():
    out = minimal_atlas_cleaner(
        "hold wrench with right hand, tighten bolt with right hand",
        "with right hand",
    )
    assert out == "hold wrench with right hand"
    assert "tighten" not in out


def test_resolve_hand_tag_prefers_draft():
    assert (
        resolve_hand_tag(
            "sweep ground with hand broom in both hands",
            "with right hand",
        )
        == "with both hands"
    )


def test_generate_label_hybrid_no_lexicon_no_verb_swap():
    pipeline = AtlasHybridPipeline()
    try:
        label = generate_label_hybrid(
            base64_frames=[],
            pipeline=pipeline,
            draft_label="picking up blue package and clothes",
            duration_seconds=2.5,
        )
        assert "blue package" in label.lower()
        assert "clothes" not in label.lower()
        assert "pick up blue package" in label.lower()
        assert " and " not in label.lower()
    finally:
        pipeline.close()


def test_generate_label_hybrid_does_not_swap_pick_up_to_hold():
    pipeline = AtlasHybridPipeline()
    try:
        first = generate_label_hybrid(
            [],
            pipeline,
            draft_label="pick up wrench with right hand",
            duration_seconds=2.0,
        )
        second = generate_label_hybrid(
            [],
            pipeline,
            draft_label="pick up wrench, tighten bolt with right hand",
            duration_seconds=4.0,
            previous_label=first,
        )
        assert "pick up wrench" in second.lower()
        assert "tighten" not in second.lower()
    finally:
        pipeline.close()
