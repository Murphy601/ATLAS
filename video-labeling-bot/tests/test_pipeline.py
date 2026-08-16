from unittest.mock import patch

from main import process_video_task


def test_process_video_task_writes_non_idle_labels(tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_text("placeholder")
    frames = [
        (0.0, "frame-a"),
        (1.0, "frame-b"),
        (2.0, "frame-c"),
        (3.0, "frame-d"),
    ]
    labels = iter(["pick up fork", "No Action"])
    recorded = []

    class FakeBot:
        def add_timestamp_and_label(self, start, end, label):
            recorded.append((start, end, label))

    with (
        patch("main.extract_frames_from_video", return_value=frames),
        patch("main.generate_label_from_frames", side_effect=lambda _: next(labels)),
        patch("main.time.sleep", return_value=None),
    ):
        process_video_task(
            FakeBot(),
            str(video_path),
            segment_duration=3.0,
            interval_seconds=1.0,
        )

    assert recorded == [("00:00", "00:03", "pick up fork")]
