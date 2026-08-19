"""Assessment enrichment: missing actions, rejected verbs, draft recovery."""

from label_generator import (
    assessment_enrich_label,
    preserve_draft_required_actions,
)
from label_pipeline import generate_label_hybrid


def test_assessment_enrich_injects_offhand_hold_for_wipe():
    draft = "wipe plate with cloth in right hand"
    out = assessment_enrich_label(draft)
    assert "hold plate with left hand" in out.lower()
    assert "wipe plate" in out.lower()


def test_assessment_enrich_rejects_adjust_verb():
    draft = "adjust plastic bag with left hand"
    out = assessment_enrich_label(draft)
    assert "adjust" not in out.lower()


def test_preserve_dual_container_pickup_from_draft():
    draft = (
        "pick up container with left hand, pick up container with right hand, "
        "walk to refrigerator"
    )
    collapsed = "pick up container with both hands"
    out = preserve_draft_required_actions(collapsed, draft)
    assert "left hand" in out.lower()
    assert "right hand" in out.lower()
    assert "both hands" not in out.lower()


def test_preserve_pass_chain_when_enrichment_drops_pass():
    draft = (
        "pick up sachet with right hand, pass sachet from right hand to left hand"
    )
    trimmed = "pick up sachet with right hand"
    out = preserve_draft_required_actions(trimmed, draft, duration_seconds=4.0)
    assert "pass sachet" in out.lower()


def test_generate_label_hybrid_runs_assessment_enrichment(monkeypatch):
    """Hybrid path applies enrich + preserve, not draft-only cleaner."""
    from hybrid_annotator import AtlasHybridPipeline, HandMotionProfile

    pipeline = AtlasHybridPipeline()
    motion = HandMotionProfile(detected_hand="with right hand", frames_analyzed=5)
    label = generate_label_hybrid(
        [],
        pipeline,
        draft_label="wipe plate with cloth in right hand",
        duration_seconds=5.0,
        motion=motion,
    )
    assert "hold plate" in label.lower()
