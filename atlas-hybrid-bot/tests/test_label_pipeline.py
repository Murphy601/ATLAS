"""Tests for hybrid label pipeline (no LLM)."""

from hybrid_annotator import AtlasHybridPipeline
from label_pipeline import build_draft_global_context, generate_label_hybrid


def test_build_draft_global_context_from_drafts():
    ctx = build_draft_global_context(
        ["pick up glass cleaner pouch with right hand", "hold wrench, tighten bolt"]
    )
    assert ctx.objects
    assert any("glass" in obj.lower() or "wrench" in obj.lower() for obj in ctx.objects)


def test_generate_label_hybrid_uses_draft_and_lints():
    pipeline = AtlasHybridPipeline()
    try:
        label = generate_label_hybrid(
            base64_frames=[],
            pipeline=pipeline,
            draft_label="picking up blue package and clothes",
            duration_seconds=2.5,
            segment_start_seconds=0.0,
        )
        assert "glass cleaner pouch" in label.lower()
        assert " and " not in label.lower()
        assert "with right hand" in label.lower() or "with left hand" in label.lower()
    finally:
        pipeline.close()


def test_generate_label_hybrid_hold_continuity():
    pipeline = AtlasHybridPipeline()
    try:
        first = generate_label_hybrid(
            [],
            pipeline,
            draft_label="pick up wrench with right hand",
            duration_seconds=2.0,
        )
        assert "pick up" in first.lower() or "hold" in first.lower()
        second = generate_label_hybrid(
            [],
            pipeline,
            draft_label="pick up wrench, tighten bolt",
            duration_seconds=4.0,
            previous_label=first,
        )
        assert "pick up wrench" not in second.lower()
        assert "hold" in second.lower()
    finally:
        pipeline.close()
