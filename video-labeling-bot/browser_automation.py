import base64
import re
import time
from dataclasses import dataclass, replace

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from config import SELECTORS

MAX_FRAMES_PER_SEGMENT = 6
MAX_LABEL_LENGTH = 2000
APP_READY_SELECTOR = (
    f'{SELECTORS["tasks_nav"]}, {SELECTORS["continue_practice"]}, '
    f'{SELECTORS["segment_input"]}'
)


@dataclass(frozen=True)
class SegmentRow:
    number: int
    start_seconds: float
    locator_index: int
    aria_label: str = ""
    end_seconds: float | None = None
    draft_label: str = ""

    @property
    def duration_seconds(self) -> float:
        if self.end_seconds is None:
            return 3.0
        return max(0.2, self.end_seconds - self.start_seconds)


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
        """Launches the user's real Google Chrome with a persistent login profile.

        Playwright's bundled Chromium is flagged by Cloudflare Turnstile and shows
        a captcha that normal Chrome does not. Headed runs therefore use channel
        "chrome". Tests stay on bundled Chromium (headless).
        """
        self.playwright = sync_playwright().start()
        launch_args = {
            "user_data_dir": self.user_data_dir,
            "headless": self.headless,
            "viewport": None,
            "args": ["--start-maximized"],
        }
        if self.headless:
            launch_args["args"] = [
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ]
            launch_args["viewport"] = {"width": 1280, "height": 720}
        else:
            launch_args["channel"] = "chrome"
            launch_args["ignore_default_args"] = ["--enable-automation"]
            launch_args["args"] = [
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ]

        try:
            self.browser_context = self.playwright.chromium.launch_persistent_context(
                **launch_args
            )
        except Exception as exc:
            if launch_args.get("channel") == "chrome":
                print(
                    "[Browser Bot]: Google Chrome was not found. "
                    "Install Chrome from https://www.google.com/chrome/ then retry. "
                    f"Details: {exc}"
                )
                launch_args.pop("channel", None)
                self.browser_context = (
                    self.playwright.chromium.launch_persistent_context(**launch_args)
                )
            else:
                raise

        if not self.headless:
            self.browser_context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )

        self.page = (
            self.browser_context.pages[0]
            if self.browser_context.pages
            else self.browser_context.new_page()
        )
        print(f"[Browser Bot]: Navigating to {url}...")
        # Do not wait for networkidle: Cloudflare challenges keep the network busy.
        self.page.goto(url, wait_until="domcontentloaded")

    def wait_for_manual_login(
        self, check_selector: str = APP_READY_SELECTOR, timeout: int = 300
    ):
        """Waits for login, then opens Tasks → practice or a listed episode."""
        print(
            "[Browser Bot]: Log in if needed. After login I will open Tasks "
            "and either Continue Assessment Practice or a listed task."
        )
        try:
            self.page.wait_for_selector(check_selector, timeout=timeout * 1000)
            print("[Browser Bot]: Atlas app is ready.")
        except PlaywrightTimeoutError:
            print("[Browser Bot]: Still on login or unknown page. Continuing...")
        self.open_work_queue()
        try:
            self.page.wait_for_selector(
                SELECTORS["segment_input"], timeout=timeout * 1000
            )
            print("[Browser Bot]: Segment editor is open.")
        except PlaywrightTimeoutError:
            print(
                "[Browser Bot]: Segment inputs not found yet. "
                "Open a practice clip or episode if it is not already visible."
            )

    def _has_visible_segments(self) -> bool:
        locator = self.page.locator(SELECTORS["segment_input"])
        for index in range(locator.count()):
            try:
                if locator.nth(index).is_visible():
                    return True
            except Exception:
                continue
        return False

    def _click_first_visible(self, selector: str, timeout_ms: int = 2500) -> bool:
        locator = self.page.locator(selector).first
        try:
            if locator.count() == 0:
                return False
            if not locator.is_visible():
                return False
            locator.click(timeout=timeout_ms)
            return True
        except Exception:
            return False

    def go_to_tasks(self):
        """Clicks the sidebar Tasks item, or opens /tasks."""
        if self._click_first_visible(SELECTORS["tasks_nav"]):
            print("[Browser Bot]: Opened Tasks.")
            time.sleep(0.8)
            return
        if "atlascapture.io" in (self.page.url or ""):
            from urllib.parse import urljoin

            tasks_url = urljoin(self.page.url, "/tasks")
            if "/tasks" not in self.page.url:
                print(f"[Browser Bot]: Navigating to {tasks_url}")
                self.page.goto(tasks_url, wait_until="domcontentloaded")
                time.sleep(0.8)

    def open_work_queue(self) -> str:
        """After login: Tasks → assessment practice, or first listed live task."""
        if self._has_visible_segments():
            print("[Browser Bot]: Segment editor already open.")
            return "editor"

        self.go_to_tasks()

        if self._click_first_visible(SELECTORS["continue_practice"]):
            print("[Browser Bot]: Clicked Continue Assessment Practice.")
            time.sleep(1.2)
            return "practice"

        for key in ("review_task", "start_task"):
            if self._click_first_visible(SELECTORS[key]):
                print(f"[Browser Bot]: Opened listed task via {key}.")
                time.sleep(1.2)
                return "live"

        print(
            "[Browser Bot]: No practice button or listed task found. "
            "Click Continue Assessment Practice or Review on a task if you see it."
        )
        return "manual"

    def play_segment_clip(self, segment_number: int):
        """Clicks 'Play segment N' so the player jumps to that clip."""
        exact = self.page.locator(
            f'button:has-text("Play segment {segment_number}")'
        ).first
        try:
            if exact.count() > 0 and exact.is_visible():
                exact.click(timeout=2000)
                time.sleep(0.3)
                self.page.evaluate(
                    """() => {
                        const video = document.querySelector('video');
                        if (video) video.pause();
                    }"""
                )
                print(f"[Browser Bot]: Played then paused segment {segment_number}.")
                return
        except Exception:
            pass

    def discover_segments(self) -> list[SegmentRow]:
        """Reads pre-rendered Atlas segment rows, including AI drafts and time ranges."""
        rows = self.page.evaluate(
            """() => {
                const inputs = Array.from(
                    document.querySelectorAll(
                        'input[data-segment-start-seconds], input[aria-label*="Segment"][aria-label*="label"]'
                    )
                );
                return inputs.map((input) => {
                    const container =
                        input.closest('li, article, section, [data-segment]') ||
                        input.parentElement;
                    const text = (container && container.innerText) || '';
                    const range = text.match(
                        /(\\d+:\\d+(?:\\.\\d+)?)\\s*[\\u2014\\u2013\\-]\\s*(\\d+:\\d+(?:\\.\\d+)?)/
                    );
                    return {
                        aria: input.getAttribute('aria-label') || '',
                        startAttr: input.getAttribute('data-segment-start-seconds'),
                        endAttr: input.getAttribute('data-segment-end-seconds'),
                        value: input.value || '',
                        rangeStart: range ? range[1] : null,
                        rangeEnd: range ? range[2] : null,
                    };
                });
            }"""
        )
        segments: list[SegmentRow] = []
        for index, row in enumerate(rows or []):
            aria = row.get("aria") or ""
            match = re.search(r"Segment\s+(\d+)", aria, re.IGNORECASE)
            number = int(match.group(1)) if match else index + 1
            start_seconds = _parse_seconds(
                row.get("startAttr") or row.get("rangeStart"),
                fallback=float(index * 3),
            )
            end_seconds = _parse_seconds(row.get("endAttr") or row.get("rangeEnd"))
            segments.append(
                SegmentRow(
                    number=number,
                    start_seconds=start_seconds,
                    locator_index=index,
                    aria_label=aria,
                    end_seconds=end_seconds,
                    draft_label=(row.get("value") or "").strip(),
                )
            )
        resolved: list[SegmentRow] = []
        for index, segment in enumerate(segments):
            end_seconds = segment.end_seconds
            if end_seconds is None and index + 1 < len(segments):
                end_seconds = segments[index + 1].start_seconds
            resolved.append(replace(segment, end_seconds=end_seconds))
        resolved.sort(key=lambda item: (item.start_seconds, item.number))
        print(f"[Browser Bot]: Found {len(resolved)} pre-rendered segment row(s).")
        return resolved

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
        """Seeks the in-page player and screenshots frames across the real segment window."""
        frames: list[tuple[float, str]] = []
        if segment_duration <= 0:
            segment_duration = 0.5
        step = interval_seconds
        estimated = max(1, int(segment_duration / step))
        if estimated > MAX_FRAMES_PER_SEGMENT:
            step = segment_duration / MAX_FRAMES_PER_SEGMENT
        offset = 0.0
        while offset < segment_duration - 1e-6:
            timestamp = start_seconds + offset
            self._seek_video(timestamp)
            frames.append((timestamp, self._screenshot_video_base64()))
            offset += step
        if not frames:
            self._seek_video(start_seconds)
            frames.append((start_seconds, self._screenshot_video_base64()))
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
        """Replaces the existing AI draft text in that segment row. Rows are not deleted."""
        cleaned = (label or "No Action")[:MAX_LABEL_LENGTH]
        locator = self.page.locator(
            f'input[aria-label="Segment {segment_number} label"]'
        )
        if locator.count() == 0 and start_seconds is not None:
            locator = self.page.locator(
                f'input[data-segment-start-seconds="{start_seconds}"]'
            )
        if locator.count() == 0:
            locator = self.page.locator(SELECTORS["label_input"]).nth(
                max(0, segment_number - 1)
            )

        target = locator.first
        target.scroll_into_view_if_needed()
        previous = ""
        try:
            previous = target.input_value()
        except Exception:
            previous = ""
        target.click()
        target.fill("")
        target.fill(cleaned)
        if previous and previous != cleaned:
            print(
                f"[Browser Bot]: Replaced AI draft on Segment {segment_number}: "
                f"'{previous}' -> '{cleaned}'"
            )
        else:
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
        """Clicks Atlas Submit practice clip, then generic Submit fallbacks."""
        selector_keys = ("submit_button", "submit_button_generic", "submit_btn")
        last_error = None
        for key in selector_keys:
            selector = SELECTORS.get(key)
            if not selector:
                continue
            try:
                submit_btn = self.page.locator(selector).first
                if submit_btn.count() == 0:
                    continue
                if not submit_btn.is_visible():
                    continue
                submit_btn.click()
                print(f"[Browser Bot]: Clicked submit via {key} ({selector}).")
                return
            except Exception as exc:
                last_error = exc
                continue
        if last_error:
            print(f"[Browser Bot Error]: Submission failed - {last_error}")
        else:
            print(
                "[Browser Bot]: Submit button not accessible. "
                "Leaving the form filled for manual submit."
            )

    def stop(self):
        """Safely terminates browser resources."""
        if self.browser_context:
            self.browser_context.close()
        if self.playwright:
            self.playwright.stop()
        print("[Browser Bot]: Session closed.")


def _parse_seconds(value, fallback: float | None = None) -> float | None:
    if value is None or value == "":
        return fallback
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    match = re.match(r"(\d+):(\d+)(?:\.(\d+))?", text)
    if not match:
        return fallback
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    fraction = match.group(3) or "0"
    return minutes * 60 + seconds + float(f"0.{fraction}")


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
