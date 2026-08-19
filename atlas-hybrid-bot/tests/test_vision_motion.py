from hybrid_annotator import HandMotionProfile, infer_clip_hand_roles
from vision_motion import (
    apply_clip_motion_enrichment,
    build_bimanual_wipe_label,
    extract_manipulation_object,
    infer_segment_work_hands,
    motion_indicates_wiping,
)


def test_extract_object_from_reposition_on_shelf():
    label = "reposition socks on shelf with right hand"
    assert extract_manipulation_object(label) == "socks"


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


def test_reposition_socks_upgrades_to_wipe_without_exchange():
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
        label.lower() == "hold socks with left hand, wipe socks with cloth in right hand"
        for label in out
    )


def test_reposition_socks_injects_pass_on_hand_exchange():
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
    assert out[0].lower() == build_bimanual_wipe_label(
        "socks", "right hand", "left hand"
    ).lower()
    assert "pass socks from right hand to left hand" in out[2].lower()
    assert "wipe socks with cloth in left hand" in out[2].lower()
    assert out[3].lower() == build_bimanual_wipe_label(
        "socks", "left hand", "right hand"
    ).lower()


def test_motion_enrichment_skips_when_no_wipe_signal():
    draft = "reposition socks on shelf with right hand"
    profiles = [
        HandMotionProfile(peak_left=0.005, peak_right=0.004, frames_analyzed=8)
        for _ in range(4)
    ]
    out = apply_clip_motion_enrichment([draft] * 4, profiles)
    assert all(label.lower() == draft.lower() for label in out)


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
