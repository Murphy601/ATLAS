from esi_caption.planner import MotionSample, parse_clock_blob, plan_episode, seconds_to_timestamp
from esi_caption.scenes import parse_video_id, pick_scene
from esi_caption.captions import lint_caption


def test_parse_clock() -> None:
    parsed = parse_clock_blob("0:28.7 / 1:13.5 | Frame 864 / 2208")
    assert parsed is not None
    cur, total, frame, frames = parsed
    assert abs(cur - 28.7) < 0.05
    assert abs(total - 73.5) < 0.05
    assert frame == 864
    assert frames == 2208


def test_video_id_and_makeup_scene() -> None:
    blob = "luna_organize_makeup_v7_trio_2026-08-25_07-13-34 Hierarchical Egocentric"
    assert "makeup" in parse_video_id(blob).casefold()
    scene = pick_scene(blob)
    assert scene.key == "makeup"
    assert scene.environment == "Home"


def test_plan_covers_whole_video_without_gaps() -> None:
    plan = plan_episode(
        duration_s=73.5,
        frame_count=2208,
        video_blob="luna_organize_makeup_v7_trio_2026-08-25_07-13-34",
    )
    assert plan.environment == "Home"
    assert plan.segments
    assert abs(plan.segments[0].start_s) < 0.05
    assert abs(plan.segments[-1].end_s - 73.5) < 0.2
    cursor = 0.0
    captions = []
    for segment in plan.segments:
        assert abs(segment.start_s - cursor) < 0.11
        for action in segment.actions:
            assert action.start_s >= segment.start_s - 0.05
            assert action.end_s <= segment.end_s + 0.05
            assert action.end_s - action.start_s >= 0.3
            if not action.idle:
                assert lint_caption("L3", action.caption) == "", action.caption
                captions.append(action.caption)
                assert action.caption != captions[0] or len(captions) == 1 or action.obj != plan.actions[0].obj
        if not segment.idle:
            assert lint_caption("L2", segment.caption) == "", segment.caption
        cursor = segment.end_s
    assert lint_caption("L1", plan.episode_caption) == ""
    assert len(set(captions)) == len(captions)
    assert not plan.issues, plan.issues
    for action in plan.actions:
        if not action.idle:
            assert action.duration_s <= 8.05


def test_idle_prefix_from_still_samples() -> None:
    samples = [MotionSample(t=x * 0.5, left=0.0, right=0.0) for x in range(0, 8)]
    samples += [MotionSample(t=4.0 + x * 0.5, left=0.2, right=0.01) for x in range(0, 8)]
    plan = plan_episode(
        duration_s=20.0,
        frame_count=600,
        video_blob="luna_organize_makeup_v7_trio",
        samples=samples,
    )
    assert plan.actions[0].idle is True
    assert plan.actions[0].end_s >= 2.0


def test_timestamp_format() -> None:
    assert seconds_to_timestamp(0) == "0:00.0"
    assert seconds_to_timestamp(73.5) == "1:13.5"
