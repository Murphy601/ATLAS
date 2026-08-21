from hybrid_annotator import (
    HandMotionProfile,
    _angular_sweep,
    _hand_activity_score,
    _infer_hand_roles,
    infer_clip_hand_roles,
)
from vision_hands import apply_clip_hand_consensus, apply_vision_hand_corrections


def test_angular_sweep_detects_rotation_path():
    center = (0.5, 0.5)
    positions = [
        (0.6, 0.5),
        (0.55, 0.45),
        (0.5, 0.4),
        (0.45, 0.45),
    ]
    assert _angular_sweep(positions, center) > 0.5


def test_angular_sweep_static_hand_is_near_zero():
    center = (0.5, 0.5)
    positions = [(0.4, 0.5), (0.401, 0.5), (0.399, 0.501)]
    assert _angular_sweep(positions, center) < 0.05


def test_hand_activity_prefers_angular_for_wiping_when_peaks_low():
    # Plate clip: low linear peaks but left wrist arcs while wiping.
    assert _hand_activity_score(0.012, 0.136) > _hand_activity_score(0.008, 0.028)


def test_infer_hand_roles_from_peak_velocity_left_wiping():
    work, stab, conf = _infer_hand_roles(0.08, 0.01, 0.02, 0.01, 0.015)
    assert work == "left hand"
    assert stab == "right hand"
    assert conf > 0.25


def test_infer_hand_roles_from_angular_when_peaks_ambiguous():
    """User plate clip: vL=0.003 vR=0.001 with aL=0.136 → left wipes, right holds."""
    work, stab, conf = _infer_hand_roles(0.012, 0.008, 0.136, 0.028, 0.015)
    assert work == "left hand"
    assert stab == "right hand"
    assert conf > 0.25


def test_infer_hand_roles_rejects_both_hands_low_motion():
    work, stab, conf = _infer_hand_roles(0.012, 0.008, 0.03, 0.025, 0.015)
    assert work is None
    assert stab is None
    assert conf == 0.0


def test_infer_hand_roles_ignores_stabilizer_rotation_when_peaks_present():
    """Left stabilizer rotates object (high angular); right sands — do not swap hands."""
    work, stab, conf = _infer_hand_roles(0.08, 0.06, 0.25, 0.05, 0.015)
    assert work is None
    assert stab is None
    assert conf == 0.0


def test_clip_consensus_left_wipes_right_holds():
    draft = "hold plate with left hand, wipe plate with cloth in right hand"
    profiles = [
        HandMotionProfile(
            peak_left=0.09,
            peak_right=0.012,
            angular_left=0.05,
            angular_right=0.01,
            hand_confidence=0.85,
            work_hand="left hand",
            stabilize_hand="right hand",
            frames_analyzed=8,
            start_left_contact=True,
            start_right_contact=True,
        )
        for _ in range(4)
    ]
    out = apply_clip_hand_consensus([draft] * 4, profiles)
    assert all(
        label.lower() == "hold plate with right hand, wipe plate with cloth in left hand"
        for label in out
    )


def test_clip_consensus_keeps_draft_when_peaks_ambiguous():
    draft = "hold plate with left hand, wipe plate with cloth in right hand"
    profiles = [
        HandMotionProfile(
            peak_left=0.01,
            peak_right=0.009,
            angular_left=0.03,
            angular_right=0.028,
            hand_confidence=0.0,
            frames_analyzed=8,
        )
        for _ in range(4)
    ]
    out = apply_clip_hand_consensus([draft] * 4, profiles)
    assert all(label.lower() == draft.lower() for label in out)


def test_clip_consensus_ignores_noisy_seek_fallback_segments():
    """Seg 2–4 seek noise must not block a clear wipe signal in segment 1."""
    draft = "hold plate with left hand, wipe plate with cloth in right hand"
    profiles = [
        HandMotionProfile(
            peak_left=0.012,
            peak_right=0.008,
            angular_left=0.136,
            angular_right=0.028,
            frames_analyzed=9,
        ),
        HandMotionProfile(
            peak_left=0.05,
            peak_right=0.045,
            angular_left=0.02,
            angular_right=0.03,
            frames_analyzed=10,
        ),
        HandMotionProfile(
            peak_left=0.048,
            peak_right=0.044,
            angular_left=0.018,
            angular_right=0.025,
            frames_analyzed=10,
        ),
        HandMotionProfile(
            peak_left=0.046,
            peak_right=0.042,
            angular_left=0.022,
            angular_right=0.028,
            frames_analyzed=10,
        ),
    ]
    work, stab, conf = infer_clip_hand_roles(profiles)
    assert work == "left hand"
    assert stab == "right hand"
    assert conf > 0.25
    out = apply_clip_hand_consensus([draft] * 4, profiles)
    assert all(
        label.lower() == "hold plate with right hand, wipe plate with cloth in left hand"
        for label in out
    )


def test_aggregate_peaks_would_fail_without_best_segment():
    """Regression: max peak aggregation hides angular asymmetry from segment 1."""
    # Old aggregate: peaks inflated by seek segments, angular diluted.
    work, stab, conf = _infer_hand_roles(0.05, 0.045, 0.136, 0.03, 0.015)
    assert work is None or conf < 0.25
    # Per-segment seg1 alone is clear.
    work, stab, conf = _infer_hand_roles(0.012, 0.008, 0.136, 0.028, 0.015)
    assert work == "left hand"
    assert conf > 0.25


def test_clip_consensus_uses_best_segment_across_clip():
    draft = "hold plate with left hand, wipe plate with cloth in right hand"
    profiles = [
        HandMotionProfile(peak_left=0.012, peak_right=0.008, frames_analyzed=8),
        HandMotionProfile(
            peak_left=0.11,
            peak_right=0.015,
            angular_left=0.05,
            angular_right=0.01,
            frames_analyzed=10,
        ),
        HandMotionProfile(peak_left=0.009, peak_right=0.007, frames_analyzed=8),
        HandMotionProfile(peak_left=0.012, peak_right=0.01, frames_analyzed=8),
    ]
    work, stab, conf = infer_clip_hand_roles(profiles)
    assert work == "left hand"
    assert stab == "right hand"
    assert conf > 0.25
    out = apply_clip_hand_consensus([draft] * 4, profiles)
    assert out[1].lower() == (
        "hold plate with right hand, wipe plate with cloth in left hand"
    )


def test_segment_vision_skips_low_confidence():
    draft = "hold plate with left hand, wipe plate with cloth in right hand"
    motion = HandMotionProfile(
        v_left=0.003,
        v_right=0.001,
        peak_left=0.012,
        peak_right=0.008,
        angular_left=0.03,
        angular_right=0.025,
        hand_confidence=0.0,
        frames_analyzed=8,
        start_left_contact=True,
        start_right_contact=True,
    )
    assert apply_vision_hand_corrections(draft, motion).lower() == draft.lower()
