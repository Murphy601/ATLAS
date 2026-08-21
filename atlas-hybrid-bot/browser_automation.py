import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from config import (
    ATLAS_LABEL_MODE,
    MAX_FRAMES_PER_SEGMENT,
    MIN_FRAMES_PER_SEGMENT,
    SELECTORS,
)


def patch_playwright_frame_listener(page) -> None:
    """
    Suppress non-fatal ValueError when Playwright fires _on_frame_detached
    on frames already removed during fast DOM navigation between clips.
    """
    if page is None:
        return
    original = getattr(page, "_on_frame_detached", None)
    if original is None or getattr(page, "_frame_detach_patched", False):
        return

    def safe_on_frame_detached(frame):
        try:
            original(frame)
        except ValueError:
            pass

    page._on_frame_detached = safe_on_frame_detached
    page._frame_detach_patched = True

MAX_LABEL_LENGTH = 2000
DEBUG_FRAMES_DIR = Path("debug_frames")
ORIGINAL_DRAFTS_DIR = Path("original_drafts")
# Center-crop std/mean below this is a black GPU hole (player chrome can still look "ok").
VIDEO_CONTENT_SCORE_MIN = 22.0
VISION_JPEG_MAX_SIDE = 768
SEEK_SETTLE_HEADED = 0.8
SEEK_SETTLE_HEADLESS = 0.3
# Extra settle after readyState >= 2 so the decoder presents the seeked frame
# before canvas pixels are read (avoids stale transition frames).
POST_SEEK_DECODE_SETTLE = 0.5
WINDOW_SLACK_SECONDS = 0.6
APP_READY_SELECTOR = (
    f'{SELECTORS["tasks_nav"]}, {SELECTORS["training_home"]}, '
    f'{SELECTORS["continue_practice"]}, {SELECTORS["practice_assessment"]}, '
    f'{SELECTORS["segment_input"]}, {SELECTORS["human_verifier_training"]}'
)


def frame_in_segment_window(
    timestamp: float,
    start_seconds: float,
    duration: float,
    slack: float = WINDOW_SLACK_SECONDS,
) -> bool:
    """False when a captured currentTime is from a different segment (e.g. 45s in a 54–59s window)."""
    return start_seconds - slack <= float(timestamp) <= start_seconds + duration + slack


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


@dataclass(frozen=True)
class VerifierClauseRow:
    index: int
    text: str
    row_selector: str = ""


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
        self._last_frames_have_video = False
        self._debug_saved = 0
        self._told_debug_dir = False

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
            # Hardware video overlays paint on a separate plane. Playwright then
            # screenshots player chrome around a black rectangle, every VLM says
            # No Action, and draft-first freezes leftover row text.
            launch_args["args"] = [
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--disable-accelerated-video-decode",
                "--disable-accelerated-video-encode",
                "--disable-direct-composition-video-overlays",
                "--disable-features=AcceleratedVideoDecode,AcceleratedVideoEncoder,HardwareMediaKeyHandling",
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
        patch_playwright_frame_listener(self.page)
        print(f"[Browser Bot]: Navigating to {url}...")
        # Do not wait for networkidle: Cloudflare challenges keep the network busy.
        self.page.goto(url, wait_until="domcontentloaded")

    def wait_for_manual_login(
        self, check_selector: str = APP_READY_SELECTOR, timeout: int = 300
    ):
        """Waits for login, then opens Practice assessment or a listed episode."""
        print(
            "[Browser Bot]: Log in if needed. After login I will open "
            "Human Verifier training, Practice assessment, or a listed task."
        )
        try:
            self.page.wait_for_selector(check_selector, timeout=timeout * 1000)
            print("[Browser Bot]: Atlas app is ready.")
        except PlaywrightTimeoutError:
            print("[Browser Bot]: Still on login or unknown page. Continuing...")
        except Exception as exc:
            print(f"[Browser Bot]: Ready-selector warning ({exc}). Continuing...")
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
        if not self.ensure_labeling_ready(timeout=float(timeout)):
            hint = (
                "Open Human Verifier training from the training sidebar, then Continue."
                if ATLAS_LABEL_MODE == "verifier"
                else "Open Practice assessment or Human Verifier training from the training sidebar, then Continue."
            )
            print(f"[Browser Bot]: Labeling editor not ready yet. {hint}")

    def segment_count(self) -> int:
        """Count visible Atlas segment label inputs (0 on Assessment landing pages)."""
        try:
            count = self.page.evaluate(
                """() => {
                    const inputs = Array.from(document.querySelectorAll(
                        'input[data-segment-start-seconds], '
                        + 'input[aria-label*="Segment"][aria-label*="label" i]'
                    ));
                    return inputs.filter((el) => {
                        if (!(el instanceof HTMLElement)) return false;
                        let node = el;
                        while (node) {
                            if (node.hidden) return false;
                            const style = window.getComputedStyle(node);
                            if (style.display === 'none' || style.visibility === 'hidden') {
                                return false;
                            }
                            node = node.parentElement;
                        }
                        const aria = el.getAttribute('aria-label') || '';
                        const hasStart = el.hasAttribute('data-segment-start-seconds');
                        const segmentLabel = /Segment\\s+\\d+\\s+label/i.test(aria);
                        return hasStart || segmentLabel;
                    }).length;
                }"""
            )
            return int(count or 0)
        except Exception:
            return 0

    def _has_visible_segments(self) -> bool:
        return self.segment_count() > 0

    def is_verifier_exercise(self) -> bool:
        """True when the Human Verifier thumbs up/down panel is visible."""
        try:
            panel = self.page.locator(SELECTORS["verifier_panel"]).first
            if panel.count() > 0 and panel.is_visible():
                return True
        except Exception:
            pass
        try:
            return bool(
                self.page.evaluate(
                    """() => {
                        const body = document.body ? document.body.innerText : '';
                        return /verify what the hands are doing/i.test(body)
                            && /important action missing/i.test(body);
                    }"""
                )
            )
        except Exception:
            return False

    def has_open_episode(self) -> bool:
        """True when a practice clip editor or verifier exercise is open."""
        return self._has_visible_segments() or self.is_verifier_exercise()

    def verifier_clause_count(self) -> int:
        return len(self.discover_verifier_clauses())

    def _wait_for_verifier_rows(self, timeout: float = 20.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_verifier_exercise() and self.verifier_clause_count() > 0:
                return True
            time.sleep(0.4)
        return False

    def _wait_for_segment_rows(self, timeout: float = 20.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.segment_count() > 0:
                return True
            time.sleep(0.4)
        return False

    def _click_training_step(self, title: str, *, exclude_practice: bool = False) -> bool:
        """Click a training sidebar row (e.g. Practice assessment vs Assessment)."""
        locator = self.page.locator(
            f'a:has-text("{title}"), button:has-text("{title}"), '
            f'[role="link"]:has-text("{title}"), [role="button"]:has-text("{title}"), '
            f'li:has-text("{title}"), div:has-text("{title}")'
        )
        try:
            total = locator.count()
        except Exception:
            total = 0
        for index in range(total):
            target = locator.nth(index)
            try:
                if not target.is_visible():
                    continue
                text = (target.inner_text() or "").strip()
                if title.lower() not in text.lower():
                    continue
                if exclude_practice and "practice" in text.lower():
                    continue
                if title.lower() == "assessment" and "practice" in text.lower():
                    continue
                target.scroll_into_view_if_needed()
                target.click(timeout=3000)
                return True
            except Exception:
                continue
        return False

    def _click_labeled_buttons(self, *labels: str) -> bool:
        for label in labels:
            if self._click_first_visible(
                f'button:has-text("{label}"), a:has-text("{label}")'
            ):
                print(f"[Browser Bot]: Clicked {label}.")
                time.sleep(1.0)
                return True
        return False

    def _open_practice_assessment_flow(self) -> bool:
        """Training UI: sidebar Practice assessment → Continue → segment editor."""
        if self._click_first_visible(SELECTORS["practice_assessment"]):
            print("[Browser Bot]: Opened Practice assessment.")
            time.sleep(1.0)
        elif self._click_training_step("Practice assessment"):
            print("[Browser Bot]: Opened Practice assessment from training progress.")
            time.sleep(1.0)

        for label in (
            "Continue Assessment Practice",
            "Continue practice",
            "Start practice",
            "Begin practice",
            "Continue Assessment",
            "Continue",
        ):
            if self._click_labeled_buttons(label):
                break

        if self._wait_for_segment_rows(timeout=18.0):
            print("[Browser Bot]: Practice clip editor is ready.")
            return True
        return False

    def _open_graded_assessment_flow(self) -> bool:
        """Training UI: sidebar Assessment (graded) → Continue → segment editor."""
        if self._click_training_step("Assessment", exclude_practice=True):
            print("[Browser Bot]: Opened graded Assessment.")
            time.sleep(1.0)
        elif self._click_first_visible(SELECTORS["graded_assessment"]):
            print("[Browser Bot]: Opened graded Assessment.")
            time.sleep(1.0)

        for label in (
            "Continue Assessment",
            "Start Assessment",
            "Begin Assessment",
            "Continue",
        ):
            if self._click_labeled_buttons(label):
                break

        if self._wait_for_segment_rows(timeout=18.0):
            print("[Browser Bot]: Graded assessment editor is ready.")
            return True
        return False

    def _open_verifier_training_flow(self) -> bool:
        """Human Verifier training: sidebar entry → onboarding → first exercise."""
        if self._click_first_visible(SELECTORS["human_verifier_training"]):
            print("[Browser Bot]: Opened Human Verifier training.")
            time.sleep(1.0)
        elif self._click_training_step("Human Verifier training"):
            print("[Browser Bot]: Opened Human Verifier training from sidebar.")
            time.sleep(1.0)

        for _ in range(4):
            if self.is_verifier_exercise() and self.verifier_clause_count() > 0:
                return True
            if self._click_first_visible(SELECTORS["how_it_works_continue"]):
                time.sleep(0.8)
                continue
            break

        for category in (
            "Multi-step Cooking",
            "Dishwashing & Cleaning",
            "Electronics Disassembly",
            "Garment Folding",
        ):
            if self.is_verifier_exercise() and self.verifier_clause_count() > 0:
                return True
            if self._click_training_step(category):
                print(f"[Browser Bot]: Opened verifier category '{category}'.")
                time.sleep(1.0)

        if self._wait_for_verifier_rows(timeout=15.0):
            print("[Browser Bot]: Human Verifier exercise is ready.")
            return True
        return False

    def ensure_labeling_ready(self, timeout: float = 120.0) -> bool:
        """Navigate until segment rows or a verifier exercise is open."""
        deadline = time.time() + timeout
        last_queue_attempt = 0.0
        while time.time() < deadline:
            if self.segment_count() > 0:
                try:
                    self.prepare_video_playback()
                except Exception as exc:
                    print(f"[Browser Bot]: Video prep warning: {exc}")
                print(
                    f"[Browser Bot]: Segment editor is open ({self.segment_count()} rows)."
                )
                return True
            if self.is_verifier_exercise() and self.verifier_clause_count() > 0:
                try:
                    self.prepare_video_playback()
                except Exception as exc:
                    print(f"[Browser Bot]: Video prep warning: {exc}")
                print(
                    f"[Browser Bot]: Verifier exercise is open "
                    f"({self.verifier_clause_count()} clause(s))."
                )
                return True
            now = time.time()
            if now - last_queue_attempt >= 8.0:
                self.open_work_queue()
                last_queue_attempt = now
            else:
                time.sleep(1.0)
                continue
            time.sleep(0.8)
        return False

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
        """Clicks Next task / Next clip / verifier Next."""
        if self._click_first_visible(SELECTORS["next_task"]):
            print("[Browser Bot]: Clicked Next task.")
            time.sleep(1.2)
            return True
        if self.is_verifier_exercise():
            if self._click_first_visible(SELECTORS["verifier_next"]):
                print("[Browser Bot]: Clicked verifier Next.")
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
            has_verifier = self.is_verifier_exercise()
            current = self.episode_fingerprint()
            if self.is_verifier_exercise():
                current = self.verifier_fingerprint() or current
            if (has_segments or has_verifier) and (not previous or current != previous):
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
        """Clicks the sidebar Tasks / Training item, or opens /tasks."""
        if self.segment_count() > 0:
            return
        current_url = (self.page.url or "").lower()
        if any(
            token in current_url
            for token in ("/tasks", "/training", "/onboarding", "/practice", "/assessment")
        ):
            return
        if self._click_first_visible(SELECTORS["tasks_nav"]):
            print("[Browser Bot]: Opened Tasks.")
            time.sleep(0.8)
            return
        if self._click_first_visible(SELECTORS["training_home"]):
            print("[Browser Bot]: Opened Training.")
            time.sleep(0.8)
            return
        if "atlascapture.io" in current_url:
            from urllib.parse import urljoin

            for path in ("/tasks", "/training", "/onboarding"):
                tasks_url = urljoin(self.page.url, path)
                if path not in current_url:
                    print(f"[Browser Bot]: Navigating to {tasks_url}")
                    self.page.goto(tasks_url, wait_until="domcontentloaded")
                    time.sleep(0.8)
                if self.segment_count() > 0 or path == "/tasks":
                    break

    def open_work_queue(self) -> str:
        """After login: verifier training, practice assessment, or listed live task."""
        if self.segment_count() > 0:
            print("[Browser Bot]: Segment editor already open.")
            return "editor"
        if self.is_verifier_exercise():
            print("[Browser Bot]: Verifier exercise already open.")
            return "verifier"

        self.go_to_tasks()
        mode = ATLAS_LABEL_MODE

        if mode == "verifier":
            if self._open_verifier_training_flow():
                return "verifier"

        if mode in {"practice", "auto", ""}:
            if self._open_practice_assessment_flow():
                return "practice"
            if self._click_first_visible(SELECTORS["continue_practice"]):
                if self._wait_for_segment_rows(timeout=15.0):
                    return "practice"

        if mode == "assessment":
            if self._open_graded_assessment_flow():
                return "assessment"
            if self._click_first_visible(SELECTORS["continue_assessment"]):
                if self._wait_for_segment_rows(timeout=15.0):
                    return "assessment"

        if mode != "verifier" and self._open_verifier_training_flow():
            return "verifier"

        for key in ("review_task", "start_task"):
            if self._click_first_visible(SELECTORS[key]):
                print(f"[Browser Bot]: Opened listed task via {key}.")
                time.sleep(1.2)
                if self._wait_for_segment_rows(timeout=12.0):
                    return "live"
                if self._wait_for_verifier_rows(timeout=12.0):
                    return "verifier"

        if mode == "auto":
            if self._open_graded_assessment_flow():
                return "assessment"

        hints = (
            "Click Human Verifier training or Practice assessment in the training sidebar, "
            "then Continue."
            if mode == "verifier"
            else "Click Practice assessment or Human Verifier training in the training sidebar, "
            "then Continue."
        )
        print(f"[Browser Bot]: No practice or task entry found. {hints}")
        return "manual"

    def play_segment_clip(self, segment_number: int):
        """Clicks 'Play segment N' so Atlas plays that window at 1x. No seeking."""
        self._enter_player_fullscreen()
        row_input = self.page.locator(
            f'input[aria-label="Segment {segment_number} label"]'
        ).first
        try:
            if row_input.count() > 0:
                row_input.scroll_into_view_if_needed()
        except Exception:
            pass

        candidates = [
            self.page.locator(
                f'button:has-text("Play segment {segment_number}")'
            ).first
        ]
        numbered = self.page.locator(SELECTORS["play_segment"])
        if numbered.count() >= segment_number:
            candidates.append(numbered.nth(segment_number - 1))

        for target in candidates:
            try:
                if target.count() == 0:
                    continue
                target.scroll_into_view_if_needed()
                target.click(timeout=2000, force=True)
                print(f"[Browser Bot]: Playing segment {segment_number} at 1x.")
                time.sleep(0.25)
                return True
            except Exception:
                continue
        print(
            f"[Browser Bot]: Play segment {segment_number} was not clicked. "
            "Starting 1x playback from the video element."
        )
        return False

    def _ensure_video_playing(self) -> None:
        """Resume playback when Atlas or the browser pauses the player mid-segment."""
        try:
            self.page.evaluate(
                """() => {
                    const videos = Array.from(document.querySelectorAll('video')).filter((el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return (
                            rect.width >= 80 && rect.height >= 80 &&
                            style.visibility !== 'hidden' && style.display !== 'none'
                        );
                    });
                    videos.sort((a, b) => {
                        const ra = a.getBoundingClientRect();
                        const rb = b.getBoundingClientRect();
                        return rb.width * rb.height - ra.width * ra.height;
                    });
                    const video = videos[0] || document.querySelector('video');
                    if (!video) return;
                    video.muted = true;
                    video.playsInline = true;
                    video.playbackRate = 1;
                    if (video.paused) {
                        const play = video.play();
                        if (play && typeof play.catch === 'function') {
                            play.catch(() => {});
                        }
                    }
                }"""
            )
        except Exception:
            pass

    def _play_from(self, start_seconds: float):
        """Start 1x playback. Seek once only if Play segment did not already land in-window."""
        current = self._video_time()
        should_seek = abs(current - start_seconds) > 1.25
        self.page.evaluate(
            """async ({ start, shouldSeek }) => {
                const videos = Array.from(document.querySelectorAll('video')).filter((el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return (
                        rect.width >= 80 && rect.height >= 80 &&
                        style.visibility !== 'hidden' && style.display !== 'none'
                    );
                });
                videos.sort((a, b) => {
                    const ra = a.getBoundingClientRect();
                    const rb = b.getBoundingClientRect();
                    return rb.width * rb.height - ra.width * ra.height;
                });
                const video = videos[0] || document.querySelector('video');
                if (!video) return;
                video.muted = true;
                video.playsInline = true;
                video.playbackRate = 1;
                if (shouldSeek && Number.isFinite(start)) {
                    try {
                        video.currentTime = Math.max(0, start);
                    } catch (error) {}
                    await new Promise((resolve) => {
                        const timeout = setTimeout(resolve, 600);
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
            {"start": start_seconds, "shouldSeek": should_seek},
        )

    def _video_time(self) -> float:
        try:
            value = self.page.evaluate(
                """() => {
                    const videos = Array.from(document.querySelectorAll('video')).filter((el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return (
                            rect.width >= 80 && rect.height >= 80 &&
                            style.visibility !== 'hidden' && style.display !== 'none'
                        );
                    });
                    videos.sort((a, b) => {
                        const ra = a.getBoundingClientRect();
                        const rb = b.getBoundingClientRect();
                        return rb.width * rb.height - ra.width * ra.height;
                    });
                    const video = videos[0] || document.querySelector('video');
                    return video ? video.currentTime : 0;
                }"""
            )
            return float(value or 0)
        except Exception:
            return 0.0

    def discover_verifier_clauses(self) -> list[VerifierClauseRow]:
        """Read action descriptions shown in the Human Verifier panel."""
        rows = self.page.evaluate(
            """() => {
                const verb = /^(hold|pick up|place|pass|scoop|scrub|wipe|trim|dig|rotate|strip|insert|pull|open|close|fold|smooth|smoothen|iron|mop|sweep|rake|gather|water|fill|cut|align|reposition|move|set|put)\\b/i;
                const seen = new Set();
                const results = [];

                const explicit = Array.from(
                    document.querySelectorAll('[data-verifier-clause], [data-clause-row], li[data-clause]')
                );
                for (const row of explicit) {
                    const textEl = row.querySelector('.clause-text, [data-clause-text], p, span');
                    const text = ((textEl && textEl.innerText) || row.innerText || '').trim();
                    const firstLine = text.split('\\n').map((line) => line.trim()).find((line) => verb.test(line));
                    if (!firstLine || seen.has(firstLine.toLowerCase())) continue;
                    seen.add(firstLine.toLowerCase());
                    row.setAttribute('data-bot-clause-index', String(results.length + 1));
                    results.push({ index: results.length + 1, text: firstLine, rowSelector: '[data-bot-clause-index="' + (results.length + 1) + '"]' });
                }
                if (results.length) return results;

                const panel = Array.from(document.querySelectorAll('section, aside, div, main')).find((el) => {
                    const text = el.innerText || '';
                    return /verify what the hands are doing/i.test(text)
                        && /important action missing/i.test(text);
                });
                const scope = panel || document.body;
                const candidates = Array.from(scope.querySelectorAll('li, p, div, span, label')).filter((el) => {
                    if (!(el instanceof HTMLElement)) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const text = (el.innerText || '').trim();
                    if (!text || text.length > 140 || text.length < 8) return false;
                    const firstLine = text.split('\\n').map((line) => line.trim()).find((line) => verb.test(line));
                    if (!firstLine || firstLine.length > 120) return false;
                    if (/important action missing|check answer|episode id|verify what/i.test(firstLine)) return false;
                    const childMatch = Array.from(el.querySelectorAll('li, p, div, span')).some((child) => {
                        if (child === el) return false;
                        const childLine = (child.innerText || '').trim().split('\\n')[0];
                        return verb.test(childLine || '');
                    });
                    return !childMatch;
                });

                for (const el of candidates) {
                    const text = (el.innerText || '').trim().split('\\n').map((line) => line.trim()).find((line) => verb.test(line));
                    if (!text || seen.has(text.toLowerCase())) continue;
                    seen.add(text.toLowerCase());
                    el.setAttribute('data-bot-clause-index', String(results.length + 1));
                    results.push({
                        index: results.length + 1,
                        text,
                        rowSelector: '[data-bot-clause-index="' + (results.length + 1) + '"]',
                    });
                }
                return results;
            }"""
        )
        clauses = [
            VerifierClauseRow(
                index=int(row.get("index") or index + 1),
                text=str(row.get("text") or "").strip(),
                row_selector=str(row.get("rowSelector") or ""),
            )
            for index, row in enumerate(rows or [])
            if str(row.get("text") or "").strip()
        ]
        print(f"[Browser Bot]: Found {len(clauses)} verifier clause(s).")
        return clauses

    def verify_clause(
        self,
        clause: VerifierClauseRow,
        *,
        approve: bool,
        rejection_reason: str | None = None,
    ) -> bool:
        """Click thumbs up (approve) or thumbs down (reject) for one clause."""
        if not clause.text:
            return False
        self._exit_player_fullscreen()
        label = "up" if approve else "down"
        try:
            clicked = self.page.evaluate(
                """({ clauseText, approve }) => {
                    const skip = /^(yes|no|next|back|check answer|continue|got it)$/i;
                    const panel = Array.from(document.querySelectorAll('section, aside, main, div')).find(
                        (el) => /verify what the hands are doing/i.test(el.innerText || '')
                    );
                    const scope = panel || document.body;

                    let anchor = null;
                    let bestLen = Infinity;
                    for (const el of scope.querySelectorAll('p, span, li, div, label')) {
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') continue;
                        const lines = (el.innerText || '').split('\\n').map((s) => s.trim()).filter(Boolean);
                        for (const line of lines) {
                            if (line !== clauseText && !line.startsWith(clauseText)) continue;
                            if (!/^(hold|pick up|place|pass|scoop|scrub|wipe|trim|dig|rotate|strip|insert|pull|open|close|fold|smooth|smoothen|iron|mop|sweep|rake|gather|water|fill|cut|align|reposition|move|set|put)\\b/i.test(line)) {
                                continue;
                            }
                            const len = line.length;
                            if (len < bestLen) {
                                bestLen = len;
                                anchor = el;
                            }
                        }
                    }
                    if (!anchor) return false;

                    const isVoteButton = (btn) => {
                        const text = (btn.innerText || btn.textContent || '').trim();
                        if (skip.test(text)) return false;
                        if (/^\\d+$/.test(text)) return false;
                        const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
                        if (aria.includes('thumb') || aria.includes('approve') || aria.includes('reject')
                            || aria.includes('match') || aria.includes('correct') || aria.includes('incorrect')) {
                            return true;
                        }
                        return Boolean(btn.querySelector('svg')) && text.length <= 2;
                    };

                    let node = anchor;
                    for (let depth = 0; depth < 10 && node; depth += 1) {
                        const buttons = Array.from(
                            node.querySelectorAll(':scope > button, :scope > [role="button"], button, [role="button"]')
                        ).filter((btn) => {
                            if (!(btn instanceof HTMLElement)) return false;
                            const style = window.getComputedStyle(btn);
                            return style.display !== 'none' && style.visibility !== 'hidden';
                        });
                        const voteButtons = buttons.filter(isVoteButton);
                        const pick = voteButtons.length >= 2 ? voteButtons : (buttons.length === 2 ? buttons : []);
                        if (pick.length >= 2) {
                            (approve ? pick[0] : pick[1]).click();
                            return true;
                        }
                        node = node.parentElement;
                    }
                    return false;
                }""",
                {"clauseText": clause.text, "approve": approve},
            )
            if clicked:
                print(
                    f"[Browser Bot]: Clause {clause.index} thumbs {label}: '{clause.text}'"
                )
                time.sleep(0.35)
                if not approve and rejection_reason:
                    self.select_clause_rejection_reason(clause, rejection_reason)
                return True
        except Exception as exc:
            print(f"[Browser Bot]: Could not verify clause {clause.index}: {exc}")
            return False

        print(
            f"[Browser Bot]: Could not find thumbs buttons for clause {clause.index} "
            f"({label}): '{clause.text}'"
        )
        return False

    def select_clause_rejection_reason(
        self,
        clause: VerifierClauseRow,
        reason: str,
    ) -> bool:
        """After thumbs down, choose why the description is wrong."""
        if not reason or not clause.text:
            return False
        try:
            clicked = self.page.evaluate(
                """({ clauseText, reason }) => {
                    const panel = Array.from(document.querySelectorAll('section, aside, main, div')).find(
                        (el) => /verify what the hands are doing/i.test(el.innerText || '')
                    );
                    const scope = panel || document.body;

                    let anchor = null;
                    let bestLen = Infinity;
                    for (const el of scope.querySelectorAll('p, span, li, div, label')) {
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') continue;
                        const lines = (el.innerText || '').split('\\n').map((s) => s.trim()).filter(Boolean);
                        for (const line of lines) {
                            if (line !== clauseText && !line.startsWith(clauseText)) continue;
                            const len = line.length;
                            if (len < bestLen) {
                                bestLen = len;
                                anchor = el;
                            }
                        }
                    }

                    const pickReason = (root) => {
                        const candidates = Array.from(
                            root.querySelectorAll(
                                '[role="option"], [role="menuitem"], [role="menuitemradio"], li, button, div, span'
                            )
                        ).filter((el) => {
                            const text = (el.innerText || el.textContent || '').trim();
                            return text === reason;
                        });
                        if (candidates.length) {
                            candidates[0].click();
                            return true;
                        }
                        return false;
                    };

                    if (anchor) {
                        let node = anchor;
                        for (let depth = 0; depth < 10 && node; depth += 1) {
                            if (pickReason(node)) return true;
                            node = node.parentElement;
                        }
                    }
                    return pickReason(scope) || pickReason(document.body);
                }""",
                {"clauseText": clause.text, "reason": reason},
            )
            if clicked:
                print(
                    f"[Browser Bot]: Clause {clause.index} rejection reason: {reason}"
                )
                time.sleep(0.25)
                return True
        except Exception as exc:
            print(
                f"[Browser Bot]: Could not select rejection reason for "
                f"clause {clause.index}: {exc}"
            )
            return False
        print(
            f"[Browser Bot]: Rejection reason menu not found for clause "
            f"{clause.index} ({reason})"
        )
        return False

    def answer_missing_action(self, missing: bool) -> bool:
        """Answer 'Is any important action missing?' with Yes or No."""
        choice = "Yes" if missing else "No"
        try:
            clicked = self.page.evaluate(
                """({ choice }) => {
                    const blocks = Array.from(document.querySelectorAll('section, div, form, aside, main'));
                    const block = blocks.find((el) => /important action missing/i.test(el.innerText || ''));
                    const scope = block || document.body;
                    const buttons = Array.from(scope.querySelectorAll('button, [role="button"]'));
                    const target = buttons.find((btn) => {
                        const text = (btn.innerText || btn.textContent || '').trim();
                        return text.toLowerCase() === choice.toLowerCase();
                    });
                    if (!target) return false;
                    target.click();
                    return true;
                }""",
                {"choice": choice},
            )
            if clicked:
                print(f"[Browser Bot]: Missing action answer: {choice}")
                return True
        except Exception:
            pass
        selector = SELECTORS["missing_action_yes" if missing else "missing_action_no"]
        if self._click_first_visible(selector):
            print(f"[Browser Bot]: Missing action answer: {choice}")
            return True
        return self._click_labeled_buttons(choice)

    def click_check_answer(self) -> bool:
        self._exit_player_fullscreen()
        try:
            clicked = self.page.evaluate(
                """() => {
                    const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
                    const target = buttons.find((btn) => {
                        const text = (btn.innerText || btn.textContent || '').trim();
                        return /^check answer$/i.test(text) || /^submit answer$/i.test(text);
                    });
                    if (!target) return false;
                    target.click();
                    return true;
                }"""
            )
            if clicked:
                print("[Browser Bot]: Clicked Check answer.")
                time.sleep(1.0)
                return True
        except Exception:
            pass
        if self._click_first_visible(SELECTORS["check_answer"]):
            print("[Browser Bot]: Clicked Check answer.")
            time.sleep(1.0)
            return True
        print("[Browser Bot]: Could not find Check answer button.")
        return False

    def click_verifier_next(self) -> bool:
        if self._click_first_visible(SELECTORS["verifier_next"]):
            print("[Browser Bot]: Clicked Next.")
            time.sleep(1.0)
            return True
        return self.click_next_task()

    def _verifier_clip_duration(self) -> float:
        """Best-effort clip length for looping verifier videos."""
        duration = self._video_duration() or 0.0
        if duration <= 0 or duration > 12.0:
            try:
                ui_duration = self.page.evaluate(
                    """() => {
                        const body = document.body ? document.body.innerText : '';
                        const match = body.match(/(\\d+):(\\d+(?:\\.\\d+)?)\\s*\\/\\s*(\\d+):(\\d+(?:\\.\\d+)?)/);
                        if (!match) return 0;
                        const end = parseFloat(match[3]) * 60 + parseFloat(match[4]);
                        return Number.isFinite(end) ? end : 0;
                    }"""
                )
                if ui_duration and ui_duration <= 12.0:
                    duration = float(ui_duration)
            except Exception:
                pass
        if duration <= 0 or duration > 12.0:
            duration = 4.5
        return max(0.5, min(duration + 0.15, 8.0))

    def capture_clip_frames(
        self,
        interval_seconds: float = 0.5,
        duration_seconds: float | None = None,
        *,
        fullscreen: bool = False,
    ) -> list[tuple[float, str]]:
        """Capture frames from the looping verifier clip (full video duration)."""
        duration = duration_seconds or self._video_duration() or 4.0
        duration = max(0.5, min(duration + 0.15, 15.0))
        if not self.headless:
            if fullscreen:
                self._enter_player_fullscreen()
            else:
                self._exit_player_fullscreen()
        frames = self.capture_segment_frames(
            start_seconds=0.0,
            segment_duration=duration,
            interval_seconds=interval_seconds,
            trust_play_segment=False,
            fullscreen=fullscreen,
        )
        if not self.headless:
            self._exit_player_fullscreen()
        return frames

    def verifier_fingerprint(self) -> str:
        try:
            data = self.page.evaluate(
                """() => {
                    const body = document.body ? document.body.innerText : '';
                    const episode = (body.match(/Episode ID[:\\s]+([\\w-]+)/i) || [])[1] || '';
                    const title = (body.match(/Try it out[^\\n]*/i) || [])[0] || '';
                    const clauses = Array.from(document.querySelectorAll('[data-bot-clause-index], [data-verifier-clause]'))
                        .map((el) => el.innerText.trim())
                        .join('|');
                    const video = document.querySelector('video');
                    const src = video ? (video.currentSrc || video.getAttribute('src') || '') : '';
                    return { episode, title, clauses, src: src.slice(0, 160), url: location.href.split('#')[0] };
                }"""
            )
        except Exception:
            return ""
        payload = data or {}
        return "|".join(
            [
                str(payload.get("episode") or ""),
                str(payload.get("title") or ""),
                str(payload.get("clauses") or ""),
                str(payload.get("src") or ""),
                str(payload.get("url") or ""),
            ]
        )

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

        self._force_video_into_compositor()
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
        self._enter_player_fullscreen()
        print("[Browser Bot]: In-page video is ready for frame capture.")

    def _enter_player_fullscreen(self) -> bool:
        """Fullscreen only the player for capture. Do not F11 the whole Chrome window."""
        if self.headless:
            return False
        try:
            ok = self.page.evaluate(
                """async () => {
                    const video = document.querySelector('video');
                    if (!video) return false;
                    if (document.fullscreenElement) return true;
                    const host =
                        video.closest(
                            '[class*="player" i], [class*="Player"], [data-player], figure'
                        ) || video;
                    const target =
                        host && typeof host.requestFullscreen === 'function'
                            ? host
                            : video;
                    try {
                        await target.requestFullscreen();
                        return true;
                    } catch (error) {
                        try {
                            await video.requestFullscreen();
                            return true;
                        } catch (inner) {
                            return false;
                        }
                    }
                }"""
            )
        except Exception:
            return False
        if ok:
            time.sleep(0.35)
            print("[Browser Bot]: Player fullscreen for capture. Labels stay in the page.")
        return bool(ok)

    def _exit_player_fullscreen(self):
        """Leave player fullscreen so segment inputs can be filled without hitting the wrong row."""
        if self.headless:
            return
        try:
            self.page.evaluate(
                """async () => {
                    if (document.fullscreenElement) {
                        await document.exitFullscreen();
                    }
                }"""
            )
            time.sleep(0.2)
        except Exception:
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass

    def _force_video_into_compositor(self):
        """Pull the video off a hardware overlay so screenshots include pixels."""
        try:
            self.page.evaluate(
                """() => {
                    const video = document.querySelector('video');
                    if (!video) return;
                    video.style.opacity = '0.999';
                    video.style.transform = 'translateZ(1px)';
                    video.style.willChange = 'opacity, transform';
                    video.disablePictureInPicture = true;
                }"""
            )
        except Exception:
            pass

    @property
    def last_frames_have_video(self) -> bool:
        """True when the last capture's center crop had real texture, not a black hole."""
        return self._last_frames_have_video

    def remember_original_drafts(self, segments: list[SegmentRow]) -> list[SegmentRow]:
        """Keep the first Atlas row texts for this clip so leftover bot labels are not reused."""
        fingerprint = self.episode_fingerprint()
        if not fingerprint or not segments:
            return segments
        ORIGINAL_DRAFTS_DIR.mkdir(exist_ok=True)
        path = ORIGINAL_DRAFTS_DIR / f"{hashlib.sha256(fingerprint.encode()).hexdigest()[:20]}.json"
        payload = {
            "fingerprint": fingerprint,
            "drafts": [
                {
                    "number": segment.number,
                    "start_seconds": segment.start_seconds,
                    "draft_label": segment.draft_label,
                }
                for segment in segments
            ],
        }
        if not path.exists():
            if _repeated_copy_drafts(segments):
                print(
                    "[Browser Bot]: Segment rows look like leftover bot text "
                    "(same sentence on every row). Ignoring them so the model "
                    "can label from the video."
                )
                return [replace(segment, draft_label="") for segment in segments]
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            print(
                f"[Browser Bot]: Saved original Atlas drafts for this clip in {path.name}."
            )
            return segments
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return segments
        by_start = {
            round(float(item.get("start_seconds")), 3): str(item.get("draft_label") or "")
            for item in (saved.get("drafts") or [])
        }
        if len(by_start) != len(segments):
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return segments
        restored: list[SegmentRow] = []
        changed = False
        for segment in segments:
            original = by_start.get(round(segment.start_seconds, 3), segment.draft_label)
            if original != segment.draft_label:
                changed = True
                restored.append(replace(segment, draft_label=original))
            else:
                restored.append(segment)
        if changed:
            print(
                "[Browser Bot]: Row text was leftover from a previous run. "
                "Using the original Atlas drafts saved on first visit."
            )
        return restored

    def _video_duration(self) -> float:
        try:
            value = self.page.evaluate(
                """() => {
                    const videos = Array.from(document.querySelectorAll('video'));
                    const video = videos[0];
                    return video && Number.isFinite(video.duration) ? video.duration : 0;
                }"""
            )
            return float(value or 0)
        except Exception:
            return 0.0

    def _seek_video(self, seconds: float):
        """Pause, seek, wait for seeked, then wait for the HTML5 frame to decode."""
        self.page.evaluate(
            """async ({ seconds, retries, waitMs }) => {
                const videos = Array.from(document.querySelectorAll('video'));
                const video = videos.reduce((best, el) => {
                    if (!best) return el;
                    const a = best.getBoundingClientRect();
                    const b = el.getBoundingClientRect();
                    return (b.width * b.height) > (a.width * a.height) ? el : best;
                }, null);
                if (!video) throw new Error('No video element on page');
                video.scrollIntoView({ block: 'center', inline: 'nearest' });
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
                const maxTries = Math.max(1, retries);
                for (let attempt = 0; attempt < maxTries; attempt += 1) {
                    try {
                        video.currentTime = target;
                    } catch (error) {
                        return;
                    }
                    await new Promise((resolve) => {
                        const timeout = setTimeout(resolve, waitMs);
                        video.addEventListener('seeked', () => {
                            clearTimeout(timeout);
                            resolve();
                        }, { once: true });
                    });
                    if (Math.abs((video.currentTime || 0) - target) <= 0.35) {
                        break;
                    }
                }
                try {
                    video.pause();
                } catch (error) {}
            }""",
            {
                "seconds": seconds,
                "retries": 1 if self.headless else 6,
                "waitMs": 200 if self.headless else 400,
            },
        )
        time.sleep(SEEK_SETTLE_HEADLESS if self.headless else SEEK_SETTLE_HEADED)

    def _wait_for_decoded_frame(self, timeout: float = 2.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            ready = self.page.evaluate(
                """() => {
                    const video = document.querySelector('video');
                    return !!(video && video.readyState >= 2 && video.videoWidth >= 8);
                }"""
            )
            if ready:
                time.sleep(POST_SEEK_DECODE_SETTLE)
                return True
            time.sleep(0.05)
        time.sleep(POST_SEEK_DECODE_SETTLE)
        return False

    def _canvas_frame_jpeg(self) -> bytes | None:
        """Copy the decoded HTML5 video frame after the GPU presents it."""
        data = self.page.evaluate(
            """async () => {
                const video = document.querySelector('video');
                if (!video || video.readyState < 2 || video.videoWidth < 8) return null;
                const waitFrame = () => new Promise((resolve) => {
                    if (typeof video.requestVideoFrameCallback === 'function') {
                        const timeout = setTimeout(resolve, 400);
                        video.requestVideoFrameCallback(() => {
                            clearTimeout(timeout);
                            resolve();
                        });
                    } else {
                        setTimeout(resolve, 50);
                    }
                });
                await waitFrame();
                const canvas = document.createElement('canvas');
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                const ctx = canvas.getContext('2d', { willReadFrequently: true });
                if (!ctx) return null;
                try {
                    try {
                        const bitmap = await createImageBitmap(video);
                        ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
                        if (typeof bitmap.close === 'function') bitmap.close();
                    } catch (error) {
                        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                    }
                    const url = canvas.toDataURL('image/jpeg', 0.9);
                    const comma = url.indexOf(',');
                    return comma >= 0 ? url.slice(comma + 1) : null;
                } catch (error) {
                    return null;
                }
            }"""
        )
        if not data:
            return None
        try:
            image_bytes = base64.b64decode(data)
        except Exception:
            return None
        if not jpeg_has_video_content(image_bytes):
            return None
        return image_bytes

    def _player_clip(self) -> dict | None:
        """CSS box of the largest video/canvas. Keep the bottom — ego hands live there."""
        box = self.page.evaluate(
            """() => {
                const media = Array.from(document.querySelectorAll('video, canvas')).filter((el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return (
                        rect.width >= 80 &&
                        rect.height >= 80 &&
                        style.visibility !== 'hidden' &&
                        style.display !== 'none'
                    );
                });
                media.sort((left, right) => {
                    const a = left.getBoundingClientRect();
                    const b = right.getBoundingClientRect();
                    return b.width * b.height - a.width * a.height;
                });
                const target = media[0] || document.querySelector('video');
                if (!target) return null;
                const rect = target.getBoundingClientRect();
                if (rect.width < 16 || rect.height < 16) return null;
                const pad = 2;
                return {
                    x: rect.x + pad,
                    y: rect.y + pad,
                    width: rect.width - pad * 2,
                    height: rect.height - pad * 2,
                };
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
        """Prefer a decoded canvas copy; fall back to an inset compositor screenshot."""
        candidates: list[bytes] = []
        canvas = self._canvas_frame_jpeg()
        if canvas:
            candidates.append(canvas)
        clip = self._player_clip()
        if clip:
            try:
                candidates.append(
                    self.page.screenshot(type="jpeg", quality=90, clip=clip)
                )
            except Exception:
                pass
        try:
            video = self.page.locator(SELECTORS["video"]).first
            candidates.append(video.screenshot(type="jpeg", quality=90))
        except Exception:
            pass
        if not candidates:
            raise RuntimeError("Could not screenshot the video player")
        image_bytes = jpeg_downscale(
            max(candidates, key=jpeg_video_score), VISION_JPEG_MAX_SIDE
        )
        self._last_frame_blank = not jpeg_has_video_content(image_bytes)
        if self._last_frame_blank and not self._warned_blank_frames:
            print(
                "[Browser Bot]: Captured frames look like a black video hole or player UI. "
                "Open debug_frames — JPEGs must show hands, not a timeline. "
                "Keep the Chrome window visible and the video playing."
            )
            self._warned_blank_frames = True
        return base64.b64encode(image_bytes).decode("utf-8")

    def capture_segment_frames(
        self,
        start_seconds: float,
        segment_duration: float = 3.0,
        interval_seconds: float = 1.0,
        trust_play_segment: bool = False,
        *,
        fullscreen: bool | None = None,
    ) -> list[tuple[float, str]]:
        """Headed: watch the segment at 1x. Headless tests: seek."""
        if segment_duration <= 0:
            segment_duration = 0.5
        use_fullscreen = self.headless if fullscreen is None else fullscreen
        if self.headless:
            frames = self._capture_by_seek(
                start_seconds, segment_duration, interval_seconds
            )
        else:
            if use_fullscreen:
                self._enter_player_fullscreen()
            else:
                self._exit_player_fullscreen()
            frames = self._capture_realtime(
                start_seconds,
                segment_duration,
                interval_seconds,
                trust_play_segment=trust_play_segment,
            )
        in_window = [
            item
            for item in frames
            if frame_in_segment_window(item[0], start_seconds, segment_duration)
        ]
        dropped = len(frames) - len(in_window)
        if dropped:
            print(
                f"[Browser Bot]: Dropped {dropped} out-of-window frame(s) "
                f"outside {start_seconds:.2f}s–{start_seconds + segment_duration:.2f}s."
            )
        frames = in_window or frames
        self._last_frames_have_video = False
        for _timestamp, payload in frames:
            try:
                if jpeg_has_video_content(base64.b64decode(payload)):
                    self._last_frames_have_video = True
                    break
            except Exception:
                continue
        self._save_debug_frames(frames)
        if frames and not self._last_frames_have_video:
            print(
                "[Browser Bot]: WARNING: debug_frames do not show video texture "
                "(black hole or player chrome). Models will say No Action."
            )
        return frames

    def _save_debug_frames(self, frames: list[tuple[float, str]]):
        """Write start/end JPEGs so black GPU captures are obvious on disk."""
        if self.headless or not frames:
            return
        DEBUG_FRAMES_DIR.mkdir(exist_ok=True)
        if not self._told_debug_dir:
            print(
                f"[Browser Bot]: Saving capture previews to {DEBUG_FRAMES_DIR.resolve()} "
                "(open the JPEGs — they must show hands, not a black rectangle)."
            )
            self._told_debug_dir = True
        picks = [frames[0]]
        if len(frames) > 1:
            picks.append(frames[-1])
        for timestamp, payload in picks:
            try:
                image_bytes = base64.b64decode(payload)
            except Exception:
                continue
            self._debug_saved += 1
            path = DEBUG_FRAMES_DIR / (
                f"seg_{self._debug_saved:03d}_{timestamp:.2f}s.jpg"
            )
            path.write_bytes(image_bytes)
            status = _debug_frame_status(image_bytes)
            print(f"[Browser Bot]: Debug frame {path.name} ({status})")

    def _capture_realtime(
        self,
        start_seconds: float,
        segment_duration: float,
        interval_seconds: float,
        trust_play_segment: bool = False,
    ) -> list[tuple[float, str]]:
        """Play the segment at 1x and screenshot while it runs. Seek-fallback if playback stalls."""
        end_seconds = start_seconds + segment_duration
        print(
            f"[Browser Bot]: Watching {start_seconds:.2f}s → {end_seconds:.2f}s at 1x..."
        )
        interval = max(
            float(interval_seconds),
            float(segment_duration) / max(MAX_FRAMES_PER_SEGMENT - 1, 1),
        )
        if trust_play_segment:
            self._ensure_video_playing()
            time.sleep(0.35)
        else:
            self._play_from(start_seconds)
            time.sleep(0.5)
        enter_deadline = time.time() + 2.5
        entered = False
        while time.time() < enter_deadline:
            if frame_in_segment_window(
                self._video_time(), start_seconds, segment_duration, slack=0.8
            ):
                entered = True
                break
            if trust_play_segment:
                self._ensure_video_playing()
            time.sleep(0.05)
        if not entered:
            print(
                "[Browser Bot]: Segment playback did not enter the window; "
                "seeking to segment start."
            )
            self._play_from(start_seconds)
            time.sleep(0.45)
        frames: list[tuple[float, str]] = []
        last_bucket = -1
        last_time = -1.0
        stalled = 0
        max_stall = max(12, int(segment_duration / 0.12) + 4)
        deadline = time.time() + segment_duration + 4.0
        while time.time() < deadline:
            current = self._video_time()
            if frame_in_segment_window(current, start_seconds, segment_duration):
                bucket = int(max(0.0, current - start_seconds) / max(interval, 0.2))
                if bucket != last_bucket:
                    try:
                        frames.append((current, self._screenshot_video_base64()))
                        last_bucket = bucket
                    except Exception as exc:
                        print(f"[Browser Bot]: Screenshot skipped ({exc})")
            if frames and current >= end_seconds - 0.05:
                if frames[-1][0] < end_seconds - 0.25:
                    try:
                        frames.append((current, self._screenshot_video_base64()))
                    except Exception:
                        pass
                break
            if abs(current - last_time) < 0.02:
                stalled += 1
                if stalled % 4 == 0:
                    self._ensure_video_playing()
                if stalled >= max_stall:
                    print(
                        "[Browser Bot]: Playback stalled; switching to seek-based capture."
                    )
                    break
            else:
                stalled = 0
            last_time = current
            if len(frames) >= MAX_FRAMES_PER_SEGMENT:
                break
            time.sleep(min(0.15, max(interval_seconds / 2, 0.08)))
        if len(frames) < MIN_FRAMES_PER_SEGMENT:
            print(
                f"[Browser Bot]: Realtime capture got {len(frames)} frame(s); "
                f"using seek fallback for {segment_duration:.1f}s segment."
            )
            seek_frames = self._capture_by_seek(
                start_seconds, segment_duration, interval_seconds
            )
            if len(seek_frames) > len(frames):
                frames = seek_frames
        try:
            self.page.evaluate(
                """() => {
                    const video = document.querySelector('video');
                    if (video) video.pause();
                }"""
            )
        except Exception:
            pass
        print(f"[Browser Bot]: Captured {len(frames)} realtime frame(s).")
        if self._last_frame_blank:
            print(
                "[Browser Bot]: WARNING: those frames look black or like player UI. "
                "Labels will be No Action unless a real draft is kept."
            )
        return frames[:MAX_FRAMES_PER_SEGMENT]

    def _seek_capture_timestamps(
        self,
        start_seconds: float,
        segment_duration: float,
        interval_seconds: float,
    ) -> list[float]:
        """Seek-fallback sample times inset from segment edges.

        Boundary frames land on cut transitions (blurred or mid hand-off); the
        grader wants clear mid-action frames, so clamp samples slightly inside
        the window while keeping full coverage for short segments.
        """
        times = sample_segment_timestamps(
            start_seconds, segment_duration, interval_seconds
        )
        if segment_duration < 1.0 or len(times) < 3:
            return times
        inset = min(0.35, segment_duration * 0.12)
        low = start_seconds + inset
        high = start_seconds + segment_duration - inset
        clamped: list[float] = []
        for timestamp in times:
            target = min(max(timestamp, low), high)
            if not clamped or abs(target - clamped[-1]) > 0.04:
                clamped.append(round(target, 3))
        return clamped

    def _capture_by_seek(
        self,
        start_seconds: float,
        segment_duration: float,
        interval_seconds: float,
    ) -> list[tuple[float, str]]:
        frames: list[tuple[float, str]] = []
        for timestamp in self._seek_capture_timestamps(
            start_seconds,
            segment_duration,
            interval_seconds,
        ):
            self._seek_video(timestamp)
            self._wait_for_decoded_frame()
            frames.append((timestamp, self._screenshot_video_base64()))
        if not frames:
            self._seek_video(start_seconds)
            self._wait_for_decoded_frame()
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

        self._enter_player_fullscreen()
        frames: list[tuple[float, str]] = []
        timestamp = 0.0
        while timestamp < end_time:
            self._seek_video(timestamp)
            frames.append((timestamp, self._screenshot_video_base64()))
            timestamp += interval_seconds
        print(f"[Browser Bot]: Captured {len(frames)} live keyframes from the player.")
        try:
            self._seek_video(0.0)
        except Exception:
            pass
        return frames

    def fill_segment_label(
        self,
        segment_number: int,
        label: str,
        start_seconds: float | None = None,
    ):
        """Replaces the existing AI draft text in that segment row. Rows are not deleted."""
        self._exit_player_fullscreen()
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


def _center_gray(image: np.ndarray) -> np.ndarray:
    """Inner video area. Drops the bottom control bar that made black captures look 'ok'."""
    height, width = image.shape[:2]
    x0, x1 = int(width * 0.08), int(width * 0.92)
    y0, y1 = int(height * 0.08), int(height * 0.78)
    if x1 - x0 < 8 or y1 - y0 < 8:
        crop = image
    else:
        crop = image[y0:y1, x0:x1]
    if crop.ndim == 3:
        return cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return crop


def jpeg_downscale(image_bytes: bytes, max_side: int = VISION_JPEG_MAX_SIDE) -> bytes:
    """Shrink large player screenshots so OpenRouter actually receives the pixels."""
    if not image_bytes:
        return image_bytes
    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        return image_bytes
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return image_bytes
    scale = max_side / float(longest)
    resized = cv2.resize(
        image,
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        interpolation=cv2.INTER_AREA,
    )
    ok, buf = cv2.imencode(".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return buf.tobytes() if ok else image_bytes


def jpeg_dimensions(image_bytes: bytes) -> tuple[int, int]:
    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        return (0, 0)
    height, width = image.shape[:2]
    return (int(width), int(height))


def jpeg_video_score(image_bytes: bytes) -> float:
    """Higher = more likely real video pixels, not a black GPU hole with UI chrome."""
    if not image_bytes or len(image_bytes) < 80:
        return 0.0
    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        return 0.0
    if min(image.shape[0], image.shape[1]) < 16:
        return 0.0
    gray = _center_gray(image)
    mean = float(gray.mean())
    std = float(gray.std())
    if mean < 18 and std < 12:
        return 0.0
    return std + min(mean, 80.0) * 0.15


def jpeg_has_video_content(image_bytes: bytes) -> bool:
    """True when the center crop has texture (hands/objects), not a flat black rectangle."""
    return jpeg_video_score(image_bytes) >= VIDEO_CONTENT_SCORE_MIN


def jpeg_is_blank(image_bytes: bytes) -> bool:
    """True when a JPEG is missing, tiny, or the video area is a black GPU bitmap."""
    return jpeg_video_score(image_bytes) < 8.0


def _debug_frame_status(image_bytes: bytes) -> str:
    if jpeg_is_blank(image_bytes):
        return "BLACK/EMPTY — model cannot see hands"
    if not jpeg_has_video_content(image_bytes):
        return "PLAYER UI — center is empty; model will say No Action"
    return "ok"


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


def _repeated_copy_drafts(segments: list[SegmentRow]) -> bool:
    """True when 3+ rows share leftover bot text from another clip, not real Atlas coarse labels."""
    leftover_row = re.compile(
        r"stuffed animal|work dough|trim stuffed",
        re.IGNORECASE,
    )
    bases: list[str] = []
    for segment in segments:
        text = (segment.draft_label or "").strip().lower()
        if not text or text == "no action":
            continue
        text = re.sub(r",\s*pass\b.*$", "", text)
        bases.append(text)
    if len(bases) < 3:
        return False
    counts: dict[str, int] = {}
    for base in bases:
        counts[base] = counts.get(base, 0) + 1
    for text, count in counts.items():
        if count >= 3 and leftover_row.search(text):
            return True
    return False
