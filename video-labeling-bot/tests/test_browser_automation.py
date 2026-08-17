from pathlib import Path

from browser_automation import VideoBrowserBot

FIXTURE = Path(__file__).parent / "fixtures" / "annotation_portal.html"


def test_fill_atlas_segment_labels(tmp_path):
    bot = VideoBrowserBot(user_data_dir=str(tmp_path / "chrome-profile"), headless=True)
    try:
        bot.start(FIXTURE.resolve().as_uri())
        segments = bot.discover_segments()
        assert [row.number for row in segments] == [1, 2]
        assert [row.start_seconds for row in segments] == [0.0, 3.0]

        bot.fill_segment_label(
            1,
            "pick up bucket with left hand, pick up tool with right hand",
            start_seconds=0,
        )
        bot.fill_segment_label(2, "No Action", start_seconds=3)

        assert (
            bot.page.locator('input[aria-label="Segment 1 label"]').input_value()
            == "pick up bucket with left hand, pick up tool with right hand"
        )
        assert (
            bot.page.locator('input[aria-label="Segment 2 label"]').input_value()
            == "No Action"
        )

        bot.add_timestamp_and_label("00:00", "00:03", "place bucket on floor")
        assert (
            bot.page.locator('input[aria-label="Segment 1 label"]').input_value()
            == "place bucket on floor"
        )

        bot.submit_final_task()
        assert bot.page.locator("#submitted").is_visible()
    finally:
        bot.stop()


def test_capture_live_segment_frames(tmp_path):
    bot = VideoBrowserBot(user_data_dir=str(tmp_path / "chrome-profile"), headless=True)
    try:
        bot.start(FIXTURE.resolve().as_uri())
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
        frames = bot.capture_segment_frames(0.0, segment_duration=3.0, interval_seconds=1.0)
        assert len(frames) == 3
        assert [round(item[0]) for item in frames] == [0, 1, 2]
        assert all(len(item[1]) > 100 for item in frames)
    finally:
        bot.stop()
