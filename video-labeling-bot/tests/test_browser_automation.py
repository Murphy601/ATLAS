from pathlib import Path

from browser_automation import VideoBrowserBot

FIXTURE = Path(__file__).parent / "fixtures" / "annotation_portal.html"


def test_add_timestamp_and_label_on_local_fixture():
    bot = VideoBrowserBot(user_data_dir="./browser_session_test", headless=True)
    try:
        bot.start(FIXTURE.resolve().as_uri())
        bot.add_timestamp_and_label("00:00", "00:03", "pick up fork")
        items = bot.page.locator("#segments li")
        assert items.count() == 1
        assert items.first.inner_text() == "00:00 - 00:03 -> pick up fork"
        bot.submit_final_task()
        assert bot.page.locator("#submitted").is_visible()
    finally:
        bot.stop()
