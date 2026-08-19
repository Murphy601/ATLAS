from hybrid_annotator import HandMotionProfile, _angular_sweep, _infer_hand_roles
from vision_hands import apply_vision_hand_corrections


def test_angular_sweep_detects_rotation_path():
    center = (0.5, 0.5)
    # Quarter circle around center
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


def test_infer_hand_roles_right_working():
    work, stab = _infer_hand_roles(0.002, 0.06, 0.01, 0.05, 0.015)
    assert work == "right hand"
    assert stab == "left hand"


def test_vision_corrects_swapped_plate_wipe_hands():
    motion = HandMotionProfile(
        v_left=0.06,
        v_right=0.003,
        angular_left=0.1,
        angular_right=0.01,
        work_hand="left hand",
        stabilize_hand="right hand",
        frames_analyzed=8,
        start_left_contact=True,
        start_right_contact=True,
    )
    draft = "hold plate with left hand, wipe plate with cloth in right hand"
    out = apply_vision_hand_corrections(draft, motion)
    assert out.lower() == (
        "hold plate with right hand, wipe plate with cloth in left hand"
    )


def test_vision_keeps_correct_plate_wipe_hands():
    motion = HandMotionProfile(
        v_left=0.003,
        v_right=0.06,
        angular_left=0.01,
        angular_right=0.08,
        work_hand="right hand",
        stabilize_hand="left hand",
        frames_analyzed=8,
        start_left_contact=True,
        start_right_contact=True,
    )
    draft = "hold plate with left hand, wipe plate with cloth in right hand"
    assert apply_vision_hand_corrections(draft, motion).lower() == draft.lower()
