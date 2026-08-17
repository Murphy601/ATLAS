import base64
import re
import time
from dataclasses import dataclass

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

SELECTORS = {
    # Atlas Capture audit portal (https://audit.atlascapture.io/)
    "label_input": 'input[aria-label*="label"]',
    "label_input_alt": 'input[data-ph-unmask="true"]',
    "segment_input": 'input[data-segment-start-seconds], input[aria-label^="Segment"][aria-label*="label"]',
    "video": "video",
    "play_button": 'button[aria-label*="Play" i], button:has-text("Play")',
    "submit_btn": 'button:has-text("Submit"), button:has-text("Next"), button[type="submit"]',
}

TASK_READY_SELECTOR = SELECTORS["segment_input"]
MAX_LABEL_LENGTH = 2000


@dataclass(frozen=True)
class SegmentRow:
    number: int
    start_seconds: float
    locator_index: int
    aria_label: str = ""


class VideoBrowserBot:
    def __init__(
        self, user_data_dir: str = "./browser_session", headless: bool = False
    ):
        """Initializes Playwright with persistent context to maintain user sessions."""
        self.user_data_dir = user_data_dir
        self.headless = headless
        self.playwright = None
        self.browser_context = None
        self.page = None

    def start(self, url: str):
        """Launches Chromium browser using persistent browser session state."""
        self.playwright = sync_playwright().start()
        launch_args = {
            "user_data_dir": self.user_data_dir,
            "headless": self.headless,
            "args": ["--start-maximized"],
            "viewport": None,
        }
        if self.headless:
            launch_args["args"] = [
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ]
            launch_args["viewport"] = {"width": 1280, "height": 720}

        self.browser_context = self.playwright.chromium.launch_persistent_context(
            **launch_args
        )
        self.page = (
            self.browser_context.pages[0]
            if self.browser_context.pages
            else self.browser_context.new_page()
        )
        print(f"[Browser Bot]: Navigating to {url}...")
        self.page.goto(url, wait_until="domcontentloaded")
        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeoutError:
            pass

    def wait_for_manual_login(
        self, check_selector: str = TASK_READY_SELECTOR, timeout: int = 300
    ):
        """Pauses execution to allow initial manual authentication if required."""
        print(
            "[Browser Bot]: Log in manually, then open a labeling task. "
            "Waiting for Segment label inputs..."
        )
        try:
            self.page.wait_for_selector(check_selector, timeout=timeout * 1000)
            print("[Browser Bot]: Active task interface detected.")
        except PlaywrightTimeoutError:
            print("[Browser Bot]: Interface detection timeout. Continuing...")

    def discover_segments(self) -> list[SegmentRow]:
        """Reads pre-rendered Atlas segment rows from the DOM."""
        locator = self.page.locator(SELECTORS["segment_input"])
        count = locator.count()
        segments: list[SegmentRow] = []
        for index in range(count):
            row = locator.nth(index)
            aria = row.get_attribute("aria-label") or ""
            raw_start = row.get_attribute("data-segment-start-seconds")
            match = re.search(r"Segment\s+(\d+)", aria, re.IGNORECASE)
            number = int(match.group(1)) if match else index + 1
            if raw_start is not None and raw_start != "":
                start_seconds = float(raw_start)
            else:
                start_seconds = float((number - 1) * 3)
            segments.append(
                SegmentRow(
                    number=number,
                    start_seconds=start_seconds,
                    locator_index=index,
                    aria_label=aria,
                )
            )
        segments.sort(key=lambda item: (item.start_seconds, item.number))
        print(f"[Browser Bot]: Found {len(segments)} pre-rendered segment row(s).")
        return segments

    def prepare_video_playback(self):
        """Clicks play on the in-page player so frames can be captured live."""
        video = self.page.locator(SELECTORS["video"]).first
        try:
            video.wait_for(state="attached", timeout=60000)
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                "No <video> element found. Open a task with the player visible."
            ) from exc

        play_button = self.page.locator(SELECTORS["play_button"]).first
        try:
            if play_button.count() > 0 and play_button.is_visible():
                play_button.click(timeout=2000)
                print("[Browser Bot]: Clicked Play.")
        except Exception:
            pass

        self.page.evaluate(
            """() => {
                const video = document.querySelector('video');
                if (!video) return;
                video.muted = true;
                video.playsInline = true;
                const play = video.play();
                if (play && typeof play.catch === 'function') {
                    play.catch(() => {});
                }
            }"""
        )
        time.sleep(0.6)
        self.page.evaluate(
            """() => {
                const video = document.querySelector('video');
                if (video) video.pause();
            }"""
        )
        print("[Browser Bot]: In-page video is ready for frame capture.")

    def _seek_video(self, seconds: float):
        self.page.evaluate(
            """async (seconds) => {
                const video = document.querySelector('video');
                if (!video) throw new Error('No video element on page');
                if (video.readyState < 1) {
                    await new Promise((resolve) => {
                        video.addEventListener('loadedmetadata', resolve, { once: true });
                        setTimeout(resolve, 1500);
                    });
                }
                try {
                    video.pause();
                } catch (error) {}
                const duration = Number.isFinite(video.duration) ? video.duration : NaN;
                const target = Number.isFinite(duration)
                    ? Math.min(Math.max(0, seconds), Math.max(0, duration - 0.05))
                    : Math.max(0, seconds);
                try {
                    video.currentTime = target;
                } catch (error) {
                    return;
                }
                await new Promise((resolve) => {
                    const timeout = setTimeout(resolve, 1200);
                    const done = () => {
                        clearTimeout(timeout);
                        resolve();
                    };
                    video.addEventListener('seeked', done, { once: true });
                });
            }""",
            seconds,
        )

    def _screenshot_video_base64(self) -> str:
        video = self.page.locator(SELECTORS["video"]).first
        image_bytes = video.screenshot(type="jpeg", quality=70)
        return base64.b64encode(image_bytes).decode("utf-8")

    def capture_segment_frames(
        self,
        start_seconds: float,
        segment_duration: float = 3.0,
        interval_seconds: float = 1.0,
    ) -> list[tuple[float, str]]:
        """Seeks the in-page player and screenshots one frame per interval."""
        frames: list[tuple[float, str]] = []
        offset = 0.0
        while offset < segment_duration:
            timestamp = start_seconds + offset
            self._seek_video(timestamp)
            frames.append((timestamp, self._screenshot_video_base64()))
            offset += interval_seconds
        return frames

    def capture_live_frames(
        self,
        interval_seconds: float = 1.0,
        until_seconds: float | None = None,
    ) -> list[tuple[float, str]]:
        """Screenshots the in-page video every interval_seconds through playback."""
        duration = self.page.evaluate(
            """() => {
                const video = document.querySelector('video');
                return video && Number.isFinite(video.duration) ? video.duration : 0;
            }"""
        )
        end_time = until_seconds if until_seconds is not None else duration
        if not end_time:
            print("[Browser Bot]: Video duration unavailable; capturing 0 frames.")
            return []

        frames: list[tuple[float, str]] = []
        timestamp = 0.0
        while timestamp < end_time:
            self._seek_video(timestamp)
            frames.append((timestamp, self._screenshot_video_base64()))
            timestamp += interval_seconds
        print(f"[Browser Bot]: Captured {len(frames)} live keyframes from the player.")
        return frames

    def fill_segment_label(
        self,
        segment_number: int,
        label: str,
        start_seconds: float | None = None,
    ):
        """Types a generated action label into the matching Atlas segment input."""
        cleaned = (label or "No Action")[:MAX_LABEL_LENGTH]
        locator = self.page.locator(
            f'input[aria-label="Segment {segment_number} label"]'
        )
        if locator.count() == 0 and start_seconds is not None:
            locator = self.page.locator(
                f'input[data-segment-start-seconds="{int(start_seconds)}"]'
            )
        if locator.count() == 0:
            locator = self.page.locator(SELECTORS["label_input"]).nth(
                max(0, segment_number - 1)
            )

        target = locator.first
        target.scroll_into_view_if_needed()
        target.fill(cleaned)
        print(
            f"[Browser Bot]: Filled Segment {segment_number} "
            f"({start_seconds if start_seconds is not None else '?'}s) -> '{cleaned}'"
        )

    def add_timestamp_and_label(self, start_time: str, end_time: str, label: str):
        """Maps MM:SS times onto the pre-rendered Atlas segment row and fills it."""
        start_seconds = _timestamp_to_seconds(start_time)
        segment_number = int(start_seconds // 3) + 1
        print(f"[Browser Bot]: Entering [{start_time} - {end_time}] -> '{label}'")
        try:
            self.fill_segment_label(
                segment_number, label, start_seconds=start_seconds
            )
            time.sleep(0.3)
        except Exception as e:
            print(f"[Browser Bot Error]: Failed to inject data - {e}")

    def submit_final_task(self):
        """Triggers Submit/Next if visible. Exact button HTML still pending if this misses."""
        try:
            submit_btn = self.page.locator(SELECTORS["submit_btn"]).first
            if submit_btn.count() > 0 and submit_btn.is_visible():
                submit_btn.click()
                print("[Browser Bot]: Task submitted successfully.")
            else:
                print(
                    "[Browser Bot]: Submit/Next button not accessible. "
                    "Paste that button's HTML to wire an exact selector. "
                    "Leaving the form filled for manual submit."
                )
        except Exception as e:
            print(f"[Browser Bot Error]: Submission failed - {e}")

    def stop(self):
        """Safely terminates browser resources."""
        if self.browser_context:
            self.browser_context.close()
        if self.playwright:
            self.playwright.stop()
        print("[Browser Bot]: Session closed.")


def _timestamp_to_seconds(value: str) -> float:
    text = str(value).strip()
    if ":" not in text:
        return float(text)
    parts = [int(part) for part in text.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds
    return 0.0
