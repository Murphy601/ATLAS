"""Orchestrate attach → watch → L3 → L2 → L1 for one MultiMango caption task."""

from __future__ import annotations

import sys
from typing import Any

from .guidelines import TASK_URL
from .planner import plan_episode, parse_clock_blob
from .process_cdp import describe_open_browsers, discover_cdp_http_urls
from .scenes import parse_video_id, pick_scene


def say(msg: str) -> None:
    print(msg, flush=True)


def run_labeling(family: str, *, submit: bool = True, cdp_url: str | None = None) -> dict[str, Any]:
    family = "morelogin" if family.casefold().startswith("more") else "ix"
    say(f"Target: {TASK_URL}")
    say(f"Browser family: {family} (already-open profile only; nothing is launched).")
    for line in describe_open_browsers(family):
        say(line)

    live = [cdp_url] if cdp_url else discover_cdp_http_urls(family)
    if live:
        say(f"DevTools candidate: {live[0]}")
        try:
            from .cdp_drive import attach_page, drive_page, read_blob

            playwright, browser, page = attach_page(live[0])
            try:
                blob = read_blob(page)
                clock = parse_clock_blob(blob)
                duration = clock[1] if clock else 73.5
                frames = clock[3] if clock else 0
                plan = plan_episode(duration_s=duration, frame_count=frames, video_blob=blob)
                plan.video_id = parse_video_id(blob)
                scene = pick_scene(blob, duration_s=duration, frame_count=frames)
                plan.environment = scene.environment
                say(f"Scene pack: {scene.key}; video id: {plan.video_id or 'unknown'}")
                return drive_page(page, plan, submit=submit)
            finally:
                try:
                    playwright.stop()
                except Exception:
                    pass
        except Exception as exc:
            say(f"DevTools attach skipped: {exc}")

    if sys.platform != "win32":
        raise RuntimeError(
            f"No live DevTools on the open {family} process, and desktop UIA only runs on Windows."
        )
    say("No live DevTools. Driving the window you already opened (desktop control).")
    from .win_ui import run_desktop

    return run_desktop(family, submit=submit)
