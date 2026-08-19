from hybrid_annotator import HandMotionProfile, infer_clip_hand_roles
from vision_motion import (
    apply_clip_motion_enrichment,
    build_bimanual_wipe_label,
    build_surface_wipe_label,
    extract_manipulation_object,
    extract_wipe_target,
    infer_segment_work_hands,
    motion_indicates_wiping,
)


def test_extract_surface_from_reposition_on_shelf():
    label = "reposition socks on shelf with right hand"
    target, kind = extract_wipe_target(label)
    assert target == "shelf"
    assert kind == "surface"
    assert extract_manipulation_object(label) == "shelf"


def test_extract_wardrobe_surface():
    label = "reposition items on wardrobe with left hand"
    target, kind = extract_wipe_target(label)
    assert target == "wardrobe"
    assert kind == "surface"


def test_motion_indicates_wiping_from_bimanual_asymmetry():
    profiles = [
        HandMotionProfile(
            peak_left=0.012,
            peak_right=0.008,
            angular_left=0.136,
            angular_right=0.028,
            frames_analyzed=9,
            start_left_contact=True,
            start_right_contact=True,
        )
    ]
    is_wipe, work, stab, conf = motion_indicates_wiping(profiles)
    assert is_wipe
    assert work == "left hand"
    assert stab == "right hand"
    assert conf >= 0.20


def test_infer_segment_work_hands_tracks_exchange():
    profiles = [
        HandMotionProfile(
            peak_left=0.01,
            peak_right=0.06,
            v_right=0.04,
            frames_analyzed=8,
            start_left_contact=True,
            start_right_contact=True,
        ),
        HandMotionProfile(
            peak_left=0.01,
            peak_right=0.055,
            v_right=0.038,
            frames_analyzed=8,
            start_left_contact=True,
            start_right_contact=True,
        ),
        HandMotionProfile(
            peak_left=0.07,
            peak_right=0.012,
            v_left=0.045,
            frames_analyzed=8,
            start_left_contact=True,
            start_right_contact=True,
        ),
        HandMotionProfile(
            peak_left=0.065,
            peak_right=0.01,
            v_left=0.04,
            frames_analyzed=8,
            start_left_contact=True,
            start_right_contact=True,
        ),
    ]
    hands = infer_segment_work_hands(profiles)
    assert hands[0] == "right hand"
    assert hands[1] == "right hand"
    assert hands[2] == "left hand"
    assert hands[3] == "left hand"


def test_reposition_socks_on_shelf_becomes_surface_wipe():
    draft = "reposition socks on shelf with right hand"
    profiles = [
        HandMotionProfile(
            peak_left=0.012,
            peak_right=0.08,
            angular_left=0.02,
            angular_right=0.05,
            frames_analyzed=9,
            start_left_contact=True,
            start_right_contact=True,
        )
        for _ in range(4)
    ]
    out = apply_clip_motion_enrichment([draft] * 4, profiles)
    assert all(
        label.lower() == "wipe shelf with cloth in right hand"
        for label in out
    )


def test_surface_wipe_passes_cloth_not_socks_on_exchange():
    draft = "reposition socks on shelf with right hand"
    profiles = [
        HandMotionProfile(
            peak_left=0.01,
            peak_right=0.07,
            frames_analyzed=9,
            start_left_contact=True,
            start_right_contact=True,
        ),
        HandMotionProfile(
            peak_left=0.012,
            peak_right=0.065,
            frames_analyzed=9,
            start_left_contact=True,
            start_right_contact=True,
        ),
        HandMotionProfile(
            peak_left=0.075,
            peak_right=0.01,
            frames_analyzed=9,
            start_left_contact=True,
            start_right_contact=True,
        ),
        HandMotionProfile(
            peak_left=0.07,
            peak_right=0.012,
            frames_analyzed=9,
            start_left_contact=True,
            start_right_contact=True,
        ),
    ]
    out = apply_clip_motion_enrichment([draft] * 4, profiles)
    assert out[0].lower() == "wipe shelf with cloth in right hand"
    assert out[1].lower() == "wipe shelf with cloth in right hand"
    assert out[2].lower() == (
        "pass cloth from right hand to left hand, wipe shelf with cloth in left hand"
    )
    assert out[3].lower() == "wipe shelf with cloth in left hand"
    assert "socks" not in " ".join(out).lower()


def test_surface_wipe_ignores_exchange_at_segment_two_seek_noise():
    """Hand change at segment 2 alone is seek noise — keep draft hand for whole clip."""
    draft = "reposition socks on shelf with right hand"
    profiles = [
        HandMotionProfile(
            peak_left=0.01,
            peak_right=0.07,
            frames_analyzed=9,
            start_left_contact=True,
            start_right_contact=True,
        ),
        HandMotionProfile(
            peak_left=0.075,
            peak_right=0.01,
            frames_analyzed=9,
            start_left_contact=True,
            start_right_contact=True,
        ),
        HandMotionProfile(
            peak_left=0.07,
            peak_right=0.012,
            frames_analyzed=9,
            start_left_contact=True,
            start_right_contact=True,
        ),
        HandMotionProfile(
            peak_left=0.065,
            peak_right=0.01,
            frames_analyzed=9,
            start_left_contact=True,
            start_right_contact=True,
        ),
    ]
    out = apply_clip_motion_enrichment([draft] * 4, profiles)
    assert all(label.lower() == "wipe shelf with cloth in right hand" for label in out)


def test_single_hand_tracking_uses_draft_hand_no_false_exchange():
    """Regression: peakR=0 must not invent a hand exchange from noise."""
    draft = "reposition socks on shelf with right hand"
    profiles = [
        HandMotionProfile(
            peak_left=0.083,
            peak_right=0.0,
            angular_left=0.683,
            angular_right=0.0,
            v_left=0.05,
            v_right=0.0,
            frames_analyzed=9,
            start_left_contact=True,
            start_right_contact=False,
        )
        for _ in range(4)
    ]
    out = apply_clip_motion_enrichment([draft] * 4, profiles)
    assert all(label.lower() == "wipe shelf with cloth in right hand" for label in out)


def test_motion_enrichment_skips_when_no_wipe_signal():
    draft = "reposition socks on shelf with right hand"
    profiles = [
        HandMotionProfile(peak_left=0.005, peak_right=0.004, frames_analyzed=8)
        for _ in range(4)
    ]
    out = apply_clip_motion_enrichment([draft] * 4, profiles)
    assert all(label.lower() == draft.lower() for label in out)


def test_object_wipe_for_non_surface_items():
    draft = "reposition plate on counter with right hand"
    profiles = [
        HandMotionProfile(
            peak_left=0.012,
            peak_right=0.08,
            frames_analyzed=9,
            start_left_contact=True,
            start_right_contact=True,
        )
        for _ in range(4)
    ]
    out = apply_clip_motion_enrichment([draft] * 4, profiles)
    assert "wipe plate with cloth" in out[0].lower()


def test_clip_hand_roles_still_work_after_enrichment():
    draft = "reposition socks on shelf with right hand"
    profiles = [
        HandMotionProfile(
            peak_left=0.09,
            peak_right=0.01,
            angular_left=0.05,
            angular_right=0.01,
            frames_analyzed=8,
            start_left_contact=True,
            start_right_contact=True,
        )
        for _ in range(4)
    ]
    work, stab, conf = infer_clip_hand_roles(profiles)
    assert work == "left hand"
    assert stab == "right hand"
    assert conf > 0.25
