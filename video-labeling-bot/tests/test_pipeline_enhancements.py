from label_generator import (
    GlobalVideoContext,
    align_verb_state,
    apply_state_continuity,
    apply_verb_state_from_frames,
    enforce_atlas_template,
    finalize_pipeline_label,
    held_objects_at_segment_end,
    lint_label_final,
    perform_draft_surgery,
)
from frame_sampling import (
    SegmentMotionProfile,
    analyze_segment_motion,
    ensure_start_frame,
    max_frames_for_duration,
    prepare_segment_frames,
)


def test_max_frames_scales_with_short_segments():
    assert max_frames_for_duration(1.5) >= 8
    assert max_frames_for_duration(3.0) >= 10
    assert max_frames_for_duration(8.0) >= 5


def test_ensure_start_frame_keeps_segment_baseline():
    frames = ["b", "a", "c"]
    times = [1.0, 0.0, 2.0]
    ordered, ordered_times = ensure_start_frame(frames, times, start_seconds=0.0)
    assert ordered[0] == "a"
    assert ordered_times[0] == 0.0


def test_state_continuity_rewrites_pick_up_to_hold():
    prev = "hold hose with both hands"
    assert held_objects_at_segment_end(prev) == {"hose"}
    assert apply_state_continuity("pick up hose with both hands", prev) == (
        "hold hose with both hands"
    )


def test_perform_draft_surgery_locks_pouch_noun():
    draft = "pick up glass cleaner pouch with right hand"
    vision = "pick up blue package with right hand"
    assert perform_draft_surgery(draft, vision) == (
        "pick up glass cleaner pouch with right hand"
    )


def test_lint_label_final_splits_scrub_and_squeeze():
    raw = "scrub and squeeze grey shirt with both hands"
    assert lint_label_final(raw) == (
        "scrub grey shirt with both hands, squeeze grey shirt with both hands"
    )


def test_finalize_pipeline_applies_surgery_and_continuity():
    draft = "scrub grey shirt with both hands, squeeze garment with both hands"
    model = "wash clothes with both hands"
    context = GlobalVideoContext(objects=("grey shirt", "garment"))
    final = finalize_pipeline_label(
        model,
        draft_label=draft,
        previous_label="hold garment with left hand",
        duration_seconds=3.5,
        global_context=context,
    )
    assert "clothes" not in final.lower()
    assert "scrub" in final.lower() or "grey shirt" in final.lower()


def test_align_verb_state_contact_and_motion():
    assert align_verb_state("pick up", True, False) == "hold"
    assert align_verb_state("hold", False, False) == "pick up"
    assert align_verb_state("wipe", True, True) == "wipe"
    assert align_verb_state("pick up", False, False) == "pick up"


def test_apply_verb_state_from_frames_rewrites_pick_up_at_contact():
    profile = SegmentMotionProfile(
        start_has_contact=True, has_active_motion=False, reliable=True
    )
    label = apply_verb_state_from_frames(
        "pick up hose with right hand", profile
    )
    assert label == "hold hose with right hand"


def test_enforce_atlas_template_adds_missing_hand():
    assert enforce_atlas_template("pick up fork") == "pick up fork with right hand"


def test_static_segment_collapses_to_start_frame():
    static_frame = (
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsL"
        "DBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/"
        "2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
        "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QA"
        "FAABAAAAAAAAAAAAAAAAAAAAAv/EABQBAQAAAAAAAAAAAAAAAAAAAAD/xAAUEAEA"
        "AAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAGfAP/Z"
    )
    frames = [static_frame] * 6
    times = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
    profile = analyze_segment_motion(frames, times)
    assert profile.is_static
    picked, picked_times = prepare_segment_frames(
        frames, times, duration_seconds=2.5, motion_profile=profile
    )
    assert len(picked) == 1
    assert picked_times == [0.0]
