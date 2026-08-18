from label_generator import (
    GlobalVideoContext,
    apply_state_continuity,
    finalize_pipeline_label,
    held_objects_at_segment_end,
    lint_label_final,
    perform_draft_surgery,
)
from frame_sampling import max_frames_for_duration, ensure_start_frame


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
