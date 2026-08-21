from pathlib import Path

import cv2

from browser_automation import VideoBrowserBot, frame_in_segment_window, sample_segment_timestamps

FIXTURE = Path(__file__).parent / "fixtures" / "annotation_portal.html"


def test_patch_playwright_frame_listener_swallows_value_error():
    from browser_automation import patch_playwright_frame_listener

    class FakeFrame:
        pass

    class FakePage:
        def __init__(self):
            self._frame_detach_patched = False

        def _on_frame_detached(self, frame):
            raise ValueError("list.remove(x): x not in list")

    page = FakePage()
    patch_playwright_frame_listener(page)
    page._on_frame_detached(FakeFrame())  # should not raise


def test_seek_capture_timestamps_inset_from_segment_edges(tmp_path):
    bot = VideoBrowserBot(user_data_dir=str(tmp_path / "chrome-profile"), headless=True)
    times = bot._seek_capture_timestamps(10.0, 10.0, 1.0)
    assert times[0] > 10.0
    assert times[-1] < 20.0
    assert all(10.0 <= t <= 20.0 for t in times)
    assert len(times) >= 5


def test_seek_capture_timestamps_short_segment_untouched(tmp_path):
    bot = VideoBrowserBot(user_data_dir=str(tmp_path / "chrome-profile"), headless=True)
    times = bot._seek_capture_timestamps(3.0, 0.8, 0.4)
    assert times[0] == 3.0


def test_open_work_queue_from_assessment_landing_clicks_practice(tmp_path):
    bot = VideoBrowserBot(user_data_dir=str(tmp_path / "chrome-profile"), headless=True)
    try:
        bot.start(FIXTURE.resolve().as_uri())
        assert bot.segment_count() == 0
        mode = bot.open_work_queue()
        assert mode == "practice"
        assert bot.segment_count() >= 2
        assert bot.page.locator("#clip-page").is_visible()
    finally:
        bot.stop()


def test_open_work_queue_clicks_assessment_practice(tmp_path):
    bot = VideoBrowserBot(user_data_dir=str(tmp_path / "chrome-profile"), headless=True)
    try:
        bot.start(FIXTURE.resolve().as_uri())
        assert bot.page.locator("#clip-page").is_hidden()
        mode = bot.open_work_queue()
        assert mode == "practice"
        assert bot.page.locator("#clip-page").is_visible()
    finally:
        bot.stop()


def test_open_work_queue_clicks_listed_review_when_practice_is_gone(tmp_path):
    bot = VideoBrowserBot(user_data_dir=str(tmp_path / "chrome-profile"), headless=True)
    try:
        bot.start(FIXTURE.resolve().as_uri())
        bot.page.locator("#continue-practice").evaluate("el => el.remove()")
        bot.page.locator("#review-task").evaluate("el => el.hidden = false")
        mode = bot.open_work_queue()
        assert mode == "live"
        assert bot.page.locator("#clip-page").is_visible()
    finally:
        bot.stop()


def test_fill_replaces_ai_draft_without_deleting_row(tmp_path):
    bot = VideoBrowserBot(user_data_dir=str(tmp_path / "chrome-profile"), headless=True)
    try:
        bot.start(FIXTURE.resolve().as_uri())
        bot.open_work_queue()
        segments = bot.discover_segments()
        assert [row.number for row in segments] == [1, 2]
        assert segments[0].start_seconds == 0.0
        assert segments[0].end_seconds == 1.67
        assert "bucket" in segments[0].draft_label
        assert segments[1].start_seconds == 1.67

        bot.fill_segment_label(
            1,
            "pick up bucket with left hand, pick up tool with right hand",
            start_seconds=0,
        )
        assert (
            bot.page.locator('input[aria-label="Segment 1 label"]').input_value()
            == "pick up bucket with left hand, pick up tool with right hand"
        )
        assert bot.page.locator('input[aria-label="Segment 2 label"]').count() == 1
        assert (
            bot.page.locator('input[aria-label="Segment 2 label"]').input_value()
            == "dig soil with tool in right hand"
        )

        bot.submit_final_task()
        assert bot.page.locator("#submitted").is_visible()
    finally:
        bot.stop()


def test_episode_fingerprint_ignores_typed_labels(tmp_path):
    bot = VideoBrowserBot(user_data_dir=str(tmp_path / "chrome-profile"), headless=True)
    try:
        bot.start(FIXTURE.resolve().as_uri())
        bot.open_work_queue()
        before = bot.episode_fingerprint()
        bot.fill_segment_label(
            1,
            "pick up bucket with left hand, pick up tool with right hand",
            start_seconds=0,
        )
        after = bot.episode_fingerprint()
        assert before
        assert before == after
    finally:
        bot.stop()


def test_wait_for_new_episode_after_submit_clicks_next_task(tmp_path):
    bot = VideoBrowserBot(user_data_dir=str(tmp_path / "chrome-profile"), headless=True)
    try:
        bot.start(FIXTURE.resolve().as_uri())
        bot.open_work_queue()
        first = bot.episode_fingerprint()
        bot.submit_final_task()
        assert bot.page.locator("#next-task").is_visible()
        assert bot.wait_for_new_episode(first, timeout=8)
        assert "2 of 3" in bot.page.locator("#clip-heading").inner_text()
        second = bot.episode_fingerprint()
        assert second != first
        segments = bot.discover_segments()
        assert "stir" in segments[0].draft_label
        assert bot.has_open_episode()
    finally:
        bot.stop()


def test_capture_live_segment_frames(tmp_path):
    bot = VideoBrowserBot(user_data_dir=str(tmp_path / "chrome-profile"), headless=True)
    try:
        bot.start(FIXTURE.resolve().as_uri())
        bot.open_work_queue()
        bot.page.evaluate(
            """() => {
                const video = document.querySelector('video');
                const canvas = document.createElement('canvas');
                canvas.width = 320;
                canvas.height = 180;
                const ctx = canvas.getContext('2d');
                ctx.fillStyle = '#cc3333';
                ctx.fillRect(0, 0, 320, 180);
                video.poster = canvas.toDataURL('image/jpeg', 0.8);
                video.width = 320;
                video.height = 180;
            }"""
        )
        frames = bot.capture_segment_frames(0.0, segment_duration=3.0, interval_seconds=0.5)
        times = [round(item[0], 2) for item in frames]
        assert all(0.0 <= t <= 3.0 for t in times)
        # Seek-fallback samples are inset from cut-transition edges.
        assert times[-1] - times[0] >= 1.5
        assert 5 <= len(frames) <= 10
        assert all(len(item[1]) > 100 for item in frames)
    finally:
        bot.stop()


def test_jpeg_is_blank_detects_black_gpu_frames():
    import numpy as np

    from browser_automation import jpeg_has_video_content, jpeg_is_blank

    black = np.zeros((48, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", black)
    assert ok
    assert jpeg_is_blank(buf.tobytes())
    assert not jpeg_has_video_content(buf.tobytes())

    color = np.zeros((48, 64, 3), dtype=np.uint8)
    color[:] = (40, 180, 90)
    ok, buf = cv2.imencode(".jpg", color)
    assert ok
    assert not jpeg_is_blank(buf.tobytes())


def test_jpeg_rejects_player_chrome_around_black_video():
    import numpy as np

    from browser_automation import jpeg_has_video_content, jpeg_is_blank

    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    frame[0:8, :] = (210, 210, 210)
    frame[165:180, :] = (40, 180, 90)
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    assert ok
    assert not jpeg_has_video_content(buf.tobytes())

    hands = np.zeros((180, 320, 3), dtype=np.uint8)
    rng = np.random.default_rng(0)
    hands[:] = rng.integers(40, 200, size=hands.shape, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", hands)
    assert ok
    assert not jpeg_is_blank(buf.tobytes())
    assert jpeg_has_video_content(buf.tobytes())


def test_remember_original_drafts_restores_first_visit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "browser_automation.ORIGINAL_DRAFTS_DIR", tmp_path / "original_drafts"
    )
    bot = VideoBrowserBot(user_data_dir=str(tmp_path / "chrome-profile"), headless=True)
    try:
        bot.start(FIXTURE.resolve().as_uri())
        bot.open_work_queue()
        first = bot.discover_segments()
        original = first[0].draft_label
        bot.remember_original_drafts(first)
        bot.fill_segment_label(
            1,
            "hold stuffed animal with left hand, trim stuffed animal with scissors in right hand",
            start_seconds=0,
        )
        leftover = bot.discover_segments()
        assert leftover[0].draft_label != original
        restored = bot.remember_original_drafts(leftover)
        assert restored[0].draft_label == original
    finally:
        bot.stop()


def test_repeated_copy_drafts_ignores_leftover_stuffed_animal_rows():
    from browser_automation import SegmentRow, _repeated_copy_drafts

    toy = (
        "hold stuffed animal with left hand, "
        "trim stuffed animal with scissors in right hand"
    )
    leftover = [
        SegmentRow(number=1, start_seconds=42.29, locator_index=0, draft_label=toy),
        SegmentRow(
            number=2,
            start_seconds=44.89,
            locator_index=1,
            draft_label=toy + ", pass scissors from right hand to left hand",
        ),
        SegmentRow(
            number=3,
            start_seconds=54.28,
            locator_index=2,
            draft_label=toy + ", pass scissors from left hand to right hand",
        ),
        SegmentRow(
            number=4,
            start_seconds=59.27,
            locator_index=3,
            draft_label=toy + ", pass scissors from right hand to left hand",
        ),
    ]
    assert _repeated_copy_drafts(leftover)

    laundry = [
        SegmentRow(
            number=1,
            start_seconds=0.0,
            locator_index=0,
            draft_label="pick up red shirt with both hands",
        ),
        SegmentRow(
            number=2,
            start_seconds=3.0,
            locator_index=1,
            draft_label="unfold red shirt with both hands",
        ),
        SegmentRow(
            number=3,
            start_seconds=6.0,
            locator_index=2,
            draft_label="place red shirt on drying rack with both hands",
        ),
        SegmentRow(
            number=4,
            start_seconds=9.0,
            locator_index=3,
            draft_label="pick up sock with both hands",
        ),
    ]
    assert not _repeated_copy_drafts(laundry)

    mop = [
        SegmentRow(
            number=index + 1,
            start_seconds=float(index * 5),
            locator_index=index,
            draft_label="mop floor with both hands",
        )
        for index in range(4)
    ]
    assert not _repeated_copy_drafts(mop)
    rake = [
        SegmentRow(
            number=index + 1,
            start_seconds=float(index * 4),
            locator_index=index,
            draft_label="rake leaves on lawn with rake in both hands",
        )
        for index in range(4)
    ]
    assert not _repeated_copy_drafts(rake)


def test_frame_in_segment_window_rejects_previous_segment_timestamp():
    assert not frame_in_segment_window(45.40, 54.28, 4.99)
    assert frame_in_segment_window(54.76, 54.28, 4.99)
    assert frame_in_segment_window(59.27, 54.28, 4.99)


def test_sample_segment_timestamps_includes_start_and_end():
    times = sample_segment_timestamps(0.0, 3.0, interval_seconds=0.5)
    assert times[0] == 0.0
    assert times[-1] == 3.0
    assert 5 <= len(times) <= 10
    dense = sample_segment_timestamps(10.0, 8.0, interval_seconds=0.5)
    assert dense[0] == 10.0
    assert dense[-1] == 18.0
    assert len(dense) == 10
