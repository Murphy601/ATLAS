from unittest.mock import patch

from browser_automation import SegmentRow
from main import process_live_task, process_video_task, run_live_queue


def test_process_live_task_fills_every_segment_including_no_action():
    recorded = []

    class FakeBot:
        def prepare_video_playback(self):
            return None

        def play_segment_clip(self, segment_number):
            return None

        def discover_segments(self):
            return [
                SegmentRow(number=1, start_seconds=0.0, locator_index=0),
                SegmentRow(number=2, start_seconds=3.0, locator_index=1),
            ]

        def capture_segment_frames(self, start_seconds, segment_duration, interval_seconds, **kwargs):
            count = int(segment_duration / interval_seconds)
            return [
                (start_seconds + index, f"frame-{start_seconds}-{index}")
                for index in range(count)
            ]

        def fill_segment_label(self, segment_number, label, start_seconds=None):
            recorded.append((segment_number, start_seconds, label))

    labels = iter(["pick up fork", "No Action"])
    with (
        patch("main.generate_label_hybrid", side_effect=lambda *args, **kwargs: next(labels)),
        patch("main.time.sleep", return_value=None),
    ):
        process_live_task(FakeBot(), segment_duration=3.0, interval_seconds=1.0)

    assert recorded == [
        (1, 0.0, "pick up fork"),
        (2, 3.0, "No Action"),
    ]


def test_process_live_task_keeps_ai_draft_when_model_says_no_action():
    recorded = []

    class FakeBot:
        def prepare_video_playback(self):
            return None

        def play_segment_clip(self, segment_number):
            return None

        def discover_segments(self):
            return [
                SegmentRow(
                    number=1,
                    start_seconds=0.0,
                    locator_index=0,
                    draft_label="dig soil with tool in right hand",
                )
            ]

        def capture_segment_frames(self, start_seconds, segment_duration, interval_seconds, **kwargs):
            return [(0.0, "frame-a")]

        def fill_segment_label(self, segment_number, label, start_seconds=None):
            recorded.append((segment_number, label))

    with (
        patch("main.generate_label_hybrid", return_value="No Action"),
        patch("main.time.sleep", return_value=None),
    ):
        process_live_task(FakeBot(), segment_duration=3.0, interval_seconds=1.0)

    assert recorded == [(1, "dig soil with tool in right hand")]


def test_process_live_task_rewrites_generic_animal_draft_when_model_says_no_action():
    recorded = []

    class FakeBot:
        def prepare_video_playback(self):
            return None

        def play_segment_clip(self, segment_number):
            return None

        def discover_segments(self):
            return [
                SegmentRow(
                    number=1,
                    start_seconds=0.0,
                    locator_index=0,
                    draft_label=(
                        "hold animal with left hand, trim animal with scissors in right hand"
                    ),
                )
            ]

        def capture_segment_frames(self, start_seconds, segment_duration, interval_seconds, **kwargs):
            return [(0.0, "frame-a")]

        def fill_segment_label(self, segment_number, label, start_seconds=None):
            recorded.append((segment_number, label))

    with (
        patch("main.generate_label_hybrid", return_value="No Action"),
        patch("main.time.sleep", return_value=None),
    ):
        process_live_task(FakeBot(), segment_duration=3.0, interval_seconds=1.0)

    assert recorded == [
        (
            1,
            "hold stuffed animal with left hand, trim stuffed animal with scissors in right hand",
        )
    ]


def test_browser_disconnect_message_matches_playwright_crash():
    from main import _is_browser_disconnect

    assert _is_browser_disconnect(
        Exception("Connection closed while reading from the driver")
    )
    assert not _is_browser_disconnect(Exception("OpenRouter rate limit"))


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
        patch("main.generate_label_hybrid", side_effect=lambda *args, **kwargs: next(labels)),
        patch("main.time.sleep", return_value=None),
    ):
        process_video_task(
            FakeBot(),
            str(video_path),
            segment_duration=3.0,
            interval_seconds=1.0,
        )

    assert recorded == [(1, "pick up fork"), (2, "No Action")]


def test_run_live_queue_labels_the_clip_after_submit():
    labeled = []

    class FakeBot:
        def __init__(self):
            self.index = 0

        def has_open_episode(self):
            return True

        def episode_fingerprint(self):
            return f"clip-{self.index}"

        def open_work_queue(self):
            return "practice"

        def wait_for_new_episode(self, previous, timeout=None):
            if self.index >= 1:
                return False
            self.index += 1
            return previous != self.episode_fingerprint()

        def submit_final_task(self):
            return None

    def fake_process(bot, segment_duration=3.0, interval_seconds=1.0):
        labeled.append(bot.episode_fingerprint())
        return True

    with (
        patch("main.process_live_task", side_effect=fake_process),
        patch("main._pause_for_review_then_submit", return_value="submitted"),
    ):
        run_live_queue(
            FakeBot(),
            auto_submit=True,
            max_episodes=2,
            next_timeout=1,
        )

    assert labeled == ["clip-0", "clip-1"]
