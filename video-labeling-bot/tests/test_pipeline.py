from unittest.mock import patch

from browser_automation import SegmentRow
from main import process_live_task, process_video_task


def test_process_live_task_fills_every_segment_including_no_action():
    recorded = []

    class FakeBot:
        def prepare_video_playback(self):
            return None

        def discover_segments(self):
            return [
                SegmentRow(number=1, start_seconds=0.0, locator_index=0),
                SegmentRow(number=2, start_seconds=3.0, locator_index=1),
            ]

        def capture_segment_frames(self, start_seconds, segment_duration, interval_seconds):
            count = int(segment_duration / interval_seconds)
            return [
                (start_seconds + index, f"frame-{start_seconds}-{index}")
                for index in range(count)
            ]

        def fill_segment_label(self, segment_number, label, start_seconds=None):
            recorded.append((segment_number, start_seconds, label))

    labels = iter(["pick up fork", "No Action"])
    with (
        patch("main.generate_label_from_frames", side_effect=lambda _: next(labels)),
        patch("main.time.sleep", return_value=None),
    ):
        process_live_task(FakeBot(), segment_duration=3.0, interval_seconds=1.0)

    assert recorded == [
        (1, 0.0, "pick up fork"),
        (2, 3.0, "No Action"),
    ]


def test_process_video_task_maps_chunks_onto_atlas_rows(tmp_path):
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
        def discover_segments(self):
            return [
                SegmentRow(number=1, start_seconds=0.0, locator_index=0),
                SegmentRow(number=2, start_seconds=3.0, locator_index=1),
            ]

        def fill_segment_label(self, segment_number, label, start_seconds=None):
            recorded.append((segment_number, label))

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

    assert recorded == [(1, "pick up fork"), (2, "No Action")]
