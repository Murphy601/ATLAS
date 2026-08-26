"""Playwright attach over CDP when the open IX/MoreLogin profile exposes DevTools."""

from __future__ import annotations

import time

from .captions import normalize_caption
from .guidelines import HAND_BUTTONS, is_forbidden_click
from .planner import EpisodePlan, L2Span, L3Span, seconds_to_timestamp
from .process_cdp import is_task_url


def say(msg: str) -> None:
    print(msg, flush=True)


def attach_page(cdp_url: str):
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    browser = playwright.chromium.connect_over_cdp(cdp_url)
    page = None
    for context in browser.contexts:
        for candidate in context.pages:
            url = candidate.url or ""
            if is_task_url(url) or "multimango.com" in url.lower():
                page = candidate
                break
        if page:
            break
    if page is None:
        for context in browser.contexts:
            if context.pages:
                page = context.pages[0]
                break
    if page is None:
        playwright.stop()
        raise RuntimeError("CDP connected but no page was open.")
    try:
        if "multimango.com" not in (page.url or "").lower():
            page.bring_to_front()
            say(f"Open tab is {page.url}. Leave the caption-labeling task in this profile.")
    except Exception:
        pass
    return playwright, browser, page


def _click_text(page, *labels: str) -> bool:
    for label in labels:
        if is_forbidden_click(label):
            continue
        loc = page.get_by_text(label, exact=False)
        try:
            if loc.count() == 0:
                continue
            loc.first.click(timeout=2500)
            return True
        except Exception:
            continue
    return False


def _fill_near(page, needle: str, value: str) -> bool:
    try:
        loc = page.get_by_text(needle, exact=False)
        if loc.count() == 0:
            return False
        box = loc.first.locator("xpath=following::input[1] | following::textarea[1]")
        if box.count() == 0:
            box = page.locator("textarea, input[type='text']").last
        box.first.click()
        box.first.fill("")
        box.first.press_sequentially(value, delay=40)
        return True
    except Exception:
        return False


def fill_l3(page, span: L3Span) -> None:
    _click_text(page, "+ Add", "Level 3")
    page.keyboard.press("3")
    time.sleep(0.25)
    if span.idle:
        _click_text(page, "Idle")
        say(f"[L3] Idle {seconds_to_timestamp(span.start_s)}–{seconds_to_timestamp(span.end_s)}")
        return
    _click_text(page, HAND_BUTTONS.get(span.hand, "Right hand only"))
    _fill_near(page, "Action", span.action)
    _click_text(page, span.action)
    obj = span.obj if not span.tool else f"{span.obj} with {span.tool}"
    _fill_near(page, "Object", obj)
    if span.target:
        _fill_near(page, "Target", span.target)
    else:
        _click_text(page, "no placement destination", "object not moving", "skip")
    _click_text(page, "Generate with AI")
    time.sleep(1.0)
    if span.caption:
        _fill_near(page, "Caption", normalize_caption(span.caption))
    say(f"[L3] {span.caption or 'idle'}")


def fill_l2(page, span: L2Span) -> None:
    page.keyboard.press("2")
    time.sleep(0.25)
    if span.idle:
        say("[L2] Idle inherited")
        return
    _click_text(page, "Success")
    _click_text(page, str(span.retries) if span.retries else "0")
    _click_text(page, "Generate with AI")
    time.sleep(1.0)
    if span.caption:
        _fill_near(page, "caption", normalize_caption(span.caption))
    say(f"[L2] {span.caption}")


def fill_l1(page, plan: EpisodePlan) -> None:
    _click_text(page, "Select where it takes place", "Choose environment")
    time.sleep(0.2)
    if not _click_text(page, plan.environment):
        _click_text(page, "Home")
    _click_text(page, "Generate with AI")
    time.sleep(1.2)
    _fill_near(page, "episode caption", plan.episode_caption)
    say(f"[L1] {plan.episode_caption} / {plan.environment}")


def maybe_submit(page, *, submit: bool) -> bool:
    body = ""
    try:
        body = page.inner_text("body")
    except Exception:
        pass
    if not submit:
        say("Submit skipped (--no-submit).")
        return False
    if "issue" in (body or "").casefold() and "fix before you can submit" in (body or "").casefold():
        say("Submit blocked: issues remain.")
        return False
    if _click_text(page, "Submit Captions"):
        say("Clicked Submit Captions.")
        return True
    return False


def drive_page(page, plan: EpisodePlan, *, submit: bool) -> dict:
    try:
        page.get_by_text("1x", exact=True).first.click(timeout=1500)
    except Exception:
        pass
    try:
        page.get_by_role("button", name="Play").click(timeout=1500)
    except Exception:
        try:
            page.keyboard.press("Space")
        except Exception:
            pass
    say(f"Watching ~{min(plan.duration_s, 90):.0f}s at 1x.")
    time.sleep(min(plan.duration_s + 1.0, 90.0))
    for action in plan.actions:
        fill_l3(page, action)
    for segment in plan.segments:
        fill_l2(page, segment)
    fill_l1(page, plan)
    submitted = maybe_submit(page, submit=submit)
    return {"submitted": submitted, "l3": len(plan.actions), "l2": len(plan.segments), "mode": "cdp"}


def read_blob(page) -> str:
    try:
        return page.inner_text("body")
    except Exception:
        return page.url or ""
