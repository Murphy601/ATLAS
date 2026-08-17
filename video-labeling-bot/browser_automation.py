import base64
import re
import time
from dataclasses import dataclass, replace

import cv2
import numpy as np
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from config import (
    MAX_FRAMES_PER_SEGMENT,
    MIN_FRAMES_PER_SEGMENT,
    SELECTORS,
)

MAX_LABEL_LENGTH = 2000
APP_READY_SELECTOR = (
    f'{SELECTORS["tasks_nav"]}, {SELECTORS["continue_practice"]}, '
    f'{SELECTORS["segment_input"]}'
)


def sample_segment_timestamps(
    start_seconds: float,
    duration: float,
    interval_seconds: float = 0.5,
    min_frames: int = MIN_FRAMES_PER_SEGMENT,
    max_frames: int = MAX_FRAMES_PER_SEGMENT,
) -> list[float]:
    """Evenly spaced times from START through END, 5–10 frames for a typical clip."""
    duration = max(float(duration), 0.2)
    interval = max(float(interval_seconds), 0.2)
    count = int(round(duration / interval)) + 1
    count = max(min_frames, count)
    count = min(max_frames, count)
    if count <= 1:
        return [round(start_seconds, 3)]
    times = [
        round(start_seconds + (duration * index / (count - 1)), 3)
        for index in range(count)
    ]
    deduped: list[float] = []
    for timestamp in times:
        if not deduped or abs(timestamp - deduped[-1]) > 0.04:
            deduped.append(timestamp)
    if abs(deduped[-1] - (start_seconds + duration)) > 0.04:
        deduped.append(round(start_seconds + duration, 3))
    return deduped[:max_frames]


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
        self._warned_blank_frames = False
        self._last_frame_blank = False

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
            "chromium_sandbox": True,
        }
        if self.headless:
            launch_args["chromium_sandbox"] = False
            launch_args["args"] = [
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ]
            launch_args["viewport"] = {"width": 1280, "height": 720}
        else:
            launch_args["channel"] = "chrome"
            launch_args["ignore_default_args"] = [
                "--enable-automation",
                "--no-sandbox",
            ]
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

    def has_open_episode(self) -> bool:
        """True when a practice clip or live episode editor is on screen."""
        return self._has_visible_segments()

    def _click_first_visible(self, selector: str, timeout_ms: int = 2500) -> bool:
        locator = self.page.locator(selector).first
        try:
            if locator.count() == 0:
                return False
            if not locator.is_visible():
                return False
            try:
                if not locator.is_enabled():
                    return False
            except Exception:
                pass
            locator.click(timeout=timeout_ms)
            return True
        except Exception:
            return False

    def episode_fingerprint(self) -> str:
        """Identity of the open clip, ignoring labels we may have typed."""
        try:
            data = self.page.evaluate(
                """() => {
                    const headingEl = document.getElementById('clip-heading');
                    let heading = headingEl ? headingEl.innerText.trim() : '';
                    if (!heading) {
                        const body = document.body ? document.body.innerText : '';
                        const match = body.match(/Practice clip\\s+\\d+\\s+of\\s+\\d+/i);
                        heading = match ? match[0] : '';
                    }
                    const video = document.querySelector('video');
                    const src = video
                        ? (video.currentSrc || video.getAttribute('src') || '')
                        : '';
                    const inputs = Array.from(
                        document.querySelectorAll(
                            'input[data-segment-start-seconds], input[aria-label^="Segment"][aria-label*="label"]'
                        )
                    );
                    const visible = inputs.filter((el) => {
                        if (!(el instanceof HTMLElement)) return false;
                        const style = window.getComputedStyle(el);
                        return style.display !== 'none' && style.visibility !== 'hidden';
                    });
                    const starts = visible.map(
                        (el) => el.getAttribute('data-segment-start-seconds') || ''
                    );
                    return {
                        heading,
                        src,
                        count: visible.length,
                        starts: starts.join(','),
                        url: (location.href || '').split('#')[0],
                    };
                }"""
            )
        except Exception:
            return ""
        return "|".join(
            [
                str((data or {}).get("heading") or ""),
                str((data or {}).get("count") or 0),
                str((data or {}).get("starts") or ""),
                str((data or {}).get("src") or "")[:160],
                str((data or {}).get("url") or ""),
            ]
        )

    def click_next_task(self) -> bool:
        """Clicks Next task / Next clip. Generic Next only if the editor is gone."""
        if self._click_first_visible(SELECTORS["next_task"]):
            print("[Browser Bot]: Clicked Next task.")
            time.sleep(1.2)
            return True
        if self._has_visible_segments():
            return False
        if self._click_first_visible(SELECTORS["next_generic"]):
            print("[Browser Bot]: Clicked Next.")
            time.sleep(1.2)
            return True
        return False

    def wait_for_new_episode(
        self, previous: str, timeout: float | None = 180
    ) -> bool:
        """Waits until a different clip is open. Clicks Next task if it appears."""
        print(
            "[Browser Bot]: Waiting for the next clip. "
            "Click Next task if you see it — I will also click it."
        )
        deadline = None if timeout is None else time.time() + timeout
        started = time.time()
        last_log = started
        queue_tried = False
        while True:
            if deadline is not None and time.time() >= deadline:
                print("[Browser Bot]: Timed out waiting for the next clip.")
                return False
            now = time.time()
            if now - last_log >= 12:
                print(
                    "[Browser Bot]: Still waiting for Next task / a new practice clip..."
                )
                last_log = now
            has_segments = self._has_visible_segments()
            current = self.episode_fingerprint()
            if has_segments and (not previous or current != previous):
                print("[Browser Bot]: Next clip is ready.")
                return True
            self.click_next_task()
            if (
                not has_segments
                and not queue_tried
                and now - started > 8
            ):
                print("[Browser Bot]: No clip yet. Checking the Tasks queue...")
                self.open_work_queue()
                queue_tried = True
            time.sleep(0.5)

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
        """Clicks 'Play segment N' and lets the clip run at normal speed."""
        exact = self.page.locator(
            f'button:has-text("Play segment {segment_number}")'
        ).first
        try:
            if exact.count() > 0 and exact.is_visible():
                exact.scroll_into_view_if_needed()
                exact.click(timeout=2000)
                print(f"[Browser Bot]: Playing segment {segment_number} at 1x.")
                return True
        except Exception:
            pass
        return False

    def _play_from(self, start_seconds: float):
        self.page.evaluate(
            """async (start) => {
                const video = document.querySelector('video');
                if (!video) return;
                video.muted = true;
                video.playsInline = true;
                video.playbackRate = 1;
                if (Number.isFinite(start) && Math.abs((video.currentTime || 0) - start) > 0.35) {
                    video.currentTime = Math.max(0, start);
                    await new Promise((resolve) => {
                        const timeout = setTimeout(resolve, 800);
                        video.addEventListener('seeked', () => {
                            clearTimeout(timeout);
                            resolve();
                        }, { once: true });
                    });
                }
                const play = video.play();
                if (play && typeof play.catch === 'function') {
                    play.catch(() => {});
                }
            }""",
            start_seconds,
        )

    def _video_time(self) -> float:
        try:
            value = self.page.evaluate(
                """() => {
                    const video = document.querySelector('video');
                    return video ? video.currentTime : 0;
                }"""
            )
            return float(value or 0)
        except Exception:
            return 0.0

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

    def _player_clip(self) -> dict | None:
        """CSS-pixel box of the painted player, not the GPU video bitmap."""
        box = self.page.evaluate(
            """() => {
                const video = document.querySelector('video');
                if (!video) return null;
                const host =
                    video.closest(
                        '[class*="player" i], [class*="Player"], [data-player], figure, [class*="media"]'
                    ) || video.parentElement || video;
                const target =
                    host && host.getBoundingClientRect && host.clientWidth >= Math.min(video.clientWidth || 0, 8)
                        ? host
                        : video;
                const rect = target.getBoundingClientRect();
                if (rect.width < 16 || rect.height < 16) return null;
                return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
            }"""
        )
        if not box:
            return None
        viewport = self.page.viewport_size
        x = max(0.0, float(box["x"]))
        y = max(0.0, float(box["y"]))
        width = float(box["width"])
        height = float(box["height"])
        if viewport:
            width = min(width, max(1.0, viewport["width"] - x))
            height = min(height, max(1.0, viewport["height"] - y))
        if width < 16 or height < 16:
            return None
        return {"x": x, "y": y, "width": width, "height": height}

    def _screenshot_video_base64(self) -> str:
        """Capture pixels the user sees. video.screenshot() is often a black GPU frame."""
        candidates: list[bytes] = []
        clip = self._player_clip()
        if clip:
            try:
                candidates.append(
                    self.page.screenshot(type="jpeg", quality=80, clip=clip)
                )
            except Exception:
                pass
        try:
            video = self.page.locator(SELECTORS["video"]).first
            candidates.append(video.screenshot(type="jpeg", quality=80))
        except Exception:
            pass
        if not candidates:
            raise RuntimeError("Could not screenshot the video player")
        image_bytes = next(
            (item for item in candidates if not jpeg_is_blank(item)),
            candidates[0],
        )
        self._last_frame_blank = jpeg_is_blank(image_bytes)
        if self._last_frame_blank and not self._warned_blank_frames:
            print(
                "[Browser Bot]: Captured frames look black/empty. "
                "The model cannot see the hands. Keep the Chrome window visible "
                "and the video playing."
            )
            self._warned_blank_frames = True
        return base64.b64encode(image_bytes).decode("utf-8")

    def capture_segment_frames(
        self,
        start_seconds: float,
        segment_duration: float = 3.0,
        interval_seconds: float = 1.0,
    ) -> list[tuple[float, str]]:
        """Watch the clip at 1x in headed Chrome; seek only in headless tests.

        Always includes the START and END of the window, targeting 5–10 frames.
        """
        if segment_duration <= 0:
            segment_duration = 0.5
        if not self.headless:
            return self._capture_realtime(start_seconds, segment_duration, interval_seconds)
        return self._capture_by_seek(start_seconds, segment_duration, interval_seconds)

    def _capture_realtime(
        self,
        start_seconds: float,
        segment_duration: float,
        interval_seconds: float,
    ) -> list[tuple[float, str]]:
        """Play the segment in real time and screenshot about twice per second."""
        end_seconds = start_seconds + segment_duration
        print(
            f"[Browser Bot]: Watching {start_seconds:.2f}s → {end_seconds:.2f}s at normal speed..."
        )
        self._play_from(start_seconds)
        frames: list[tuple[float, str]] = []
        try:
            frames.append((self._video_time() or start_seconds, self._screenshot_video_base64()))
        except Exception as exc:
            print(f"[Browser Bot]: Start screenshot skipped ({exc})")
        last_bucket = 0
        deadline = time.time() + segment_duration + 4.0
        while time.time() < deadline:
            current = self._video_time()
            if current >= end_seconds - 0.05 and frames:
                break
            bucket = int(max(0.0, current - start_seconds) / max(interval_seconds, 0.2))
            if current >= start_seconds - 0.15 and bucket != last_bucket:
                try:
                    frames.append((current, self._screenshot_video_base64()))
                    last_bucket = bucket
                except Exception as exc:
                    print(f"[Browser Bot]: Screenshot skipped ({exc})")
            if len(frames) >= MAX_FRAMES_PER_SEGMENT - 1:
                break
            time.sleep(min(0.15, max(interval_seconds / 2, 0.08)))
        self.page.evaluate(
            """() => {
                const video = document.querySelector('video');
                if (video) video.pause();
            }"""
        )
        if not frames or frames[-1][0] < end_seconds - 0.2:
            try:
                self._seek_video(end_seconds)
                frames.append((end_seconds, self._screenshot_video_base64()))
            except Exception:
                pass
        if not frames:
            frames = self._capture_by_seek(start_seconds, segment_duration, interval_seconds)
        print(f"[Browser Bot]: Captured {len(frames)} realtime frame(s).")
        if self._last_frame_blank:
            print(
                "[Browser Bot]: WARNING: those frames look black. "
                "Labels will be No Action unless a real draft is kept."
            )
        return frames[:MAX_FRAMES_PER_SEGMENT]

    def _capture_by_seek(
        self,
        start_seconds: float,
        segment_duration: float,
        interval_seconds: float,
    ) -> list[tuple[float, str]]:
        frames: list[tuple[float, str]] = []
        for timestamp in sample_segment_timestamps(
            start_seconds,
            segment_duration,
            interval_seconds,
        ):
            self._seek_video(timestamp)
            frames.append((timestamp, self._screenshot_video_base64()))
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
        if previous and previous == cleaned:
            print(
                f"[Browser Bot]: Segment {segment_number} still matches the Atlas draft "
                f"(unchanged): '{cleaned}'"
            )
        elif previous and previous != cleaned:
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
                submit_btn.scroll_into_view_if_needed()
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
        try:
            if self.browser_context:
                self.browser_context.close()
        except Exception:
            pass
        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
        self.browser_context = None
        self.playwright = None
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


def jpeg_is_blank(image_bytes: bytes) -> bool:
    """True when a JPEG is missing, tiny, or almost uniformly black (GPU video bitmap)."""
    if not image_bytes or len(image_bytes) < 80:
        return True
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        return True
    if min(image.shape[0], image.shape[1]) < 16:
        return True
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(gray.mean()) < 18 and float(gray.std()) < 12


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
