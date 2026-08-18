import pytest

from hybrid_annotator import (
    AtlasHybridPipeline,
    SegmentStateMemory,
    transform_draft_non_llm,
    _hand_from_velocities,
)


def test_transform_draft_lexicon_and_duration_cap():
    out = transform_draft_non_llm(
        "picking up blue package and clothes",
        segment_duration=2.5,
        detected_hand="with left hand",
    )
    assert "blue package" not in out
    assert "clothes" not in out
    assert "glass cleaner pouch" in out
    assert "pick up" in out
    assert "with left hand" in out
    assert "," not in out


def test_duration_allows_two_clauses_at_4_seconds():
    out = transform_draft_non_llm(
        "hold bottle with left hand, pass bottle from left hand to right hand",
        segment_duration=4.0,
        detected_hand="with left hand",
    )
    assert "," in out


def test_state_memory_pick_up_to_hold():
    memory = SegmentStateMemory()
    memory.right_hand_object = "wrench"
    pipeline = AtlasHybridPipeline(state_memory=memory)
    corrected = pipeline.resolve_state_verbs(
        "pick up wrench with right hand",
        is_held_from_memory=True,
        start_has_contact=False,
    )
    assert corrected == "hold wrench with right hand"


def test_hand_from_velocities_both_hands():
    assert _hand_from_velocities(0.05, 0.04, 0.015) == "with both hands"
    assert _hand_from_velocities(0.05, 0.001, 0.015) == "with left hand"


def test_process_frame_batch_empty_frames():
    pipeline = AtlasHybridPipeline()
    out = pipeline.process_frame_batch(
        [],
        0.0,
        2.0,
        "scrubbing shirt and clothes",
        target_object="grey shirt",
    )
    assert "scrub" in out
    assert "garment" in out or "grey shirt" in out
