"""Detect the open EGO task UI, play the video, read timeline clips, apply captions.

The operator opens IX Browser and the task. This module never launches a window
and never clicks Submit or Hand Tracking Error controls.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

from playwright.sync_api import Page

import guidelines
from caption_engine import LintResult, lint_clips

logger = logging.getLogger("ego.task")

DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*s\b", re.I)
PENDING_RE = re.compile(r"\bpending\b", re.I)
CREATE_HINT = "click or press K to create"

PLAY_SELECTORS = (
    '[aria-label="Play"]',
    '[title="Play"]',
    'button[aria-label="Play"]',
    'button:has-text("Play")',
)

DESCRIPTION_SELECTORS = (
    'textarea',
    '[contenteditable="true"]',
    'input[placeholder*="description" i]',
    'input[placeholder*="caption" i]',
    'input[aria-label*="description" i]',
    'input[aria-label*="caption" i]',
    '[data-testid*="caption"]',
    '[data-testid*="description"]',
)

HTE_SELECTORS = (
    "text=Hand Tracking Error",
    "text=Hand tracking errors",
    '[class*="hand-tracking"]',
)


@dataclass
class TimelineClip:
    index: int
    caption: str
    duration_s: float | None
    pending: bool
    kind: str = "subgoal"
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_ego_task_page(page: Page) -> bool:
    try:
        body = page.inner_text("body")
    except Exception:
        return False
    return is_ego_task_text(body)


def is_ego_task_text(text: str) -> bool:
    if not text:
        return False
    hits = sum(1 for marker in guidelines.TASK_READY_MARKERS if marker.lower() in text.lower())
    return hits >= 2


def parse_clips_from_text(text: str) -> list[TimelineClip]:
    """Parse Focused Timeline cards from visible text (screenshot layout)."""
    clips: list[TimelineClip] = []
    if not text:
        return clips
    cleaned = text.replace("\u00a0", " ")
    # Split around the empty-create slot so we do not treat it as a clip.
    focused = cleaned
    if "Focused Timeline" in cleaned:
        focused = cleaned.split("Focused Timeline", 1)[1]
    if CREATE_HINT.lower() in focused.lower():
        idx = focused.lower().find(CREATE_HINT.lower())
        focused = focused[:idx]
    pattern = re.compile(
        r"(pending)?\s*\|\s*(\d+(?:\.\d+)?)s\s*[:\-]?\s*(.+?)(?=(?:pending\s*\|\s*\d)|(?:\|\s*\d+(?:\.\d+)?s)|$)",
        re.I | re.S,
    )
    for match in pattern.finditer(focused):
        caption = re.sub(r"\s+", " ", match.group(3)).strip(" :-")
        if not caption or CREATE_HINT.lower() in caption.lower():
            continue
        clips.append(
            TimelineClip(
                index=len(clips),
                caption=caption,
                duration_s=float(match.group(2)),
                pending=bool(match.group(1)),
                raw=match.group(0).strip(),
            )
        )
    if clips:
        return clips
    # Looser fallback: duration then following sentence
    loose = re.compile(r"(pending\s*)?(\d+(?:\.\d+)?)s\s+([A-Z][^|\n]{8,200})")
    for match in loose.finditer(focused):
        caption = re.sub(r"\s+", " ", match.group(3)).strip()
        clips.append(
            TimelineClip(
                index=len(clips),
                caption=caption,
                duration_s=float(match.group(2)),
                pending=bool(match.group(1)),
                raw=match.group(0).strip(),
            )
        )
    if clips:
        return clips
    # SensorFusionLab OCR: "3.3s" on its own line, caption on the next.
    card = re.compile(
        r"(pending\s+)?(\d+(?:\.\d+)?)s\s*\n+\s*([A-Z][^\n]{8,180})",
        re.M,
    )
    for match in card.finditer(focused):
        caption = re.sub(r"\s+", " ", match.group(3)).strip()
        clips.append(
            TimelineClip(
                index=len(clips),
                caption=caption,
                duration_s=float(match.group(2)),
                pending=bool(match.group(1)),
                raw=match.group(0).strip(),
            )
        )
    if clips:
        return clips
    stacked = re.compile(
        r"([A-Z][^\n]{8,180})\s*\n\s*(pending\s+)?(\d+(?:\.\d+)?)s\b",
        re.M,
    )
    for match in stacked.finditer(focused):
        caption = re.sub(r"\s+", " ", match.group(1)).strip()
        clips.append(
            TimelineClip(
                index=len(clips),
                caption=caption,
                duration_s=float(match.group(3)),
                pending=bool(match.group(2)),
                raw=match.group(0).strip(),
            )
        )
    return clips


def read_clips(page: Page) -> list[TimelineClip]:
    text = page.inner_text("body")
    clips = parse_clips_from_text(text)
    logger.info("Read %d timeline clip(s) from the open task", len(clips))
    return clips


def play_open_video(page: Page, timeout_s: float = 600.0) -> dict[str, Any]:
    """Watch the entire video first (spec). Uses the on-page player; never opens a new window."""
    logger.info("Playing the open task video at 1x (watch-entire-video-first)")
    _rewind(page)
    _set_speed_1x(page)
    clicked = _click_play(page)
    started = _ensure_playing(page)
    state = _video_state(page)
    duration = float(state.get("duration") or 0.0)
    wait_s = duration if duration and duration == duration else 8.0
    wait_s = min(max(wait_s, 1.0), timeout_s)
    deadline = time.monotonic() + wait_s + 8.0
    while time.monotonic() < deadline:
        state = _video_state(page)
        cur = float(state.get("currentTime") or 0.0)
        dur = float(state.get("duration") or 0.0)
        paused = bool(state.get("paused"))
        if dur and dur == dur and cur >= max(dur - 0.2, 0):
            break
        if paused and cur > 0.4 and dur and cur >= dur * 0.95:
            break
        time.sleep(0.35)
    final = _video_state(page)
    logger.info(
        "Video watch complete clicked_play=%s playing=%s duration=%s",
        clicked,
        started,
        final.get("duration"),
    )
    return {"clicked_play": clicked, "started": started, **final}


def apply_caption_fixes(page: Page, clips: list[dict], write: bool = True) -> list[dict]:
    """Fill rewritten captions for non-HTE clips. Never submits. Never touches HTE."""
    reports = []
    for item in lint_clips(clips):
        lint: LintResult = item["lint"]
        report = {
            "index": item.get("index"),
            "kind": item.get("kind"),
            "original": lint.original,
            "rewritten": lint.rewritten,
            "pending": item.get("pending"),
            "duration_s": item.get("duration_s"),
            "issues": [issue.__dict__ for issue in lint.issues],
            "wrote": False,
            "skipped": bool(item.get("skip_edit")),
        }
        if item.get("skip_edit"):
            logger.info("Skipping HTE clip %s (do not touch autoflags)", item.get("index"))
            reports.append(report)
            continue
        should_write = write and lint.changed and (item.get("pending") or not lint.ok)
        if should_write:
            report["wrote"] = _fill_clip_caption(page, lint.original, lint.rewritten)
        reports.append(report)
    return reports


def run_quality_assistant(page: Page) -> bool:
    """Click Quality Assistant → Run Now if those controls exist. Never Submit."""
    for label in ("Quality Assistant", "Run the linters", "Run Now", "Run linters"):
        loc = page.get_by_text(label, exact=False)
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=3000)
                logger.info("Clicked %s", label)
                if label != "Run Now":
                    run = page.get_by_text("Run Now", exact=False)
                    if run.count() and run.first.is_visible():
                        run.first.click(timeout=3000)
                return True
        except Exception:
            logger.debug("Quality assistant control %s not clickable", label)
    logger.info("Quality Assistant controls not found; skipping linter click")
    return False


def _rewind(page: Page) -> None:
    try:
        page.evaluate(
            """() => {
                const v = document.querySelector('video');
                if (v) { v.currentTime = 0; v.playbackRate = 1; }
            }"""
        )
    except Exception:
        logger.debug("No HTML video element to rewind; will use UI play")


def _set_speed_1x(page: Page) -> None:
    try:
        loc = page.get_by_text("1x", exact=True)
        if loc.count():
            loc.first.click(timeout=1500)
    except Exception:
        pass


def _click_play(page: Page) -> bool:
    for sel in PLAY_SELECTORS:
        loc = page.locator(sel)
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=2500)
                logger.info("Clicked play control %s", sel)
                return True
        except Exception:
            continue
    # Triangle button next to the Sub-goal dropdown (screenshot layout).
    try:
        sub = page.get_by_text("Sub-goal", exact=False)
        if sub.count():
            btn = sub.first.locator("xpath=following::button[1]")
            if btn.count():
                btn.first.click(timeout=2500)
                logger.info("Clicked play button after Sub-goal")
                return True
    except Exception:
        logger.debug("Sub-goal neighbor play click failed")
    return False


def _ensure_playing(page: Page) -> bool:
    try:
        return bool(
            page.evaluate(
                """() => {
                    const v = document.querySelector('video');
                    if (!v) return false;
                    v.muted = true;
                    v.playbackRate = 1;
                    const p = v.play();
                    return p !== undefined;
                }"""
            )
        )
    except Exception:
        return False


def _video_state(page: Page) -> dict[str, Any]:
    try:
        state = page.evaluate(
            """() => {
                const v = document.querySelector('video');
                if (!v) return {};
                return {paused: v.paused, currentTime: v.currentTime, duration: v.duration};
            }"""
        )
        return state or {}
    except Exception:
        return {}


def _fill_clip_caption(page: Page, original: str, rewritten: str) -> bool:
    snippet = original[:48] if original else ""
    try:
        if snippet:
            loc = page.get_by_text(snippet, exact=False)
            if loc.count():
                loc.first.click(timeout=2500)
        for sel in DESCRIPTION_SELECTORS:
            field = page.locator(sel)
            if field.count() and field.first.is_visible():
                field.first.fill(rewritten)
                logger.info("Wrote caption (%d chars)", len(rewritten))
                return True
    except Exception:
        logger.exception("Failed to write caption for %r", snippet)
    logger.warning("Could not find a description field for clip %r", snippet)
    return False
