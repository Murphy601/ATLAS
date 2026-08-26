"""Attach to an already-open IX Browser profile and drive Chat Home Base claimed chat.

Never launches a browser. Never clicks Send.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from .chathomebase import (
    CLAIMED_URL,
    EXTRACT_MESSAGES_JS,
    READ_PAGE_JS,
    SCROLL_HISTORY_JS,
    SHOW_PANEL_JS,
    PageSnapshot,
    claim_became_live,
    is_forbidden_click,
    locality_from_profile_location,
    logbook_comment,
)
from .engine import handle_claimed_chat
from .ix_cdp import (
    describe_open_ix,
    discover_cdp_http_urls,
    is_claimed_chat_url,
    is_site_url,
    probe_devtools,
    should_fallback_to_desktop,
)
from .logbook import Logbook


class SendGuardError(RuntimeError):
    """Raised if anything tries to click Send."""


def _say(msg: str) -> None:
    print(msg, flush=True)


def attach_playwright(cdp_url: str | None = None, timeout_s: float = 8.0):
    """Connect over CDP to the IX window the operator already opened.

    Most IX profiles do not expose DevTools. One empty scan is enough; the
    caller then drives SensorFusionLab from the desktop like the lidar bot.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required to attach to IX Browser. "
            "From offline-chat-copilot run: python -m pip install playwright psutil && python -m playwright install chromium"
        ) from exc

    for line in describe_open_ix():
        _say(line)

    playwright = sync_playwright().start()
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    empty_rounds = 0
    printed_scan = False
    while time.monotonic() < deadline:
        urls: list[str] = []
        if cdp_url:
            urls.append(cdp_url)
        try:
            urls.extend(discover_cdp_http_urls())
        except Exception as exc:
            last_error = exc
            _say(f"Process scan error: {exc}")
        seen: set[str] = set()
        unique = [url for url in urls if not (url in seen or seen.add(url))]
        for url in unique:
            try:
                if not probe_devtools(url):
                    continue
                browser = playwright.chromium.connect_over_cdp(url)
                _say(f"Attached to your open IX window via {url}")
                return playwright, browser
            except Exception as exc:
                last_error = exc
                continue
        empty_rounds += 1
        if not printed_scan:
            _say("No live DevTools on the open IX process. Debug port 9222 is optional.")
            printed_scan = True
        if should_fallback_to_desktop(empty_rounds):
            playwright.stop()
            raise RuntimeError("No live DevTools on the open IX process")
        time.sleep(2.0)
    playwright.stop()
    raise RuntimeError(
        "Could not reach the IX window that is already open. "
        "Click Open on the IX profile, leave SensorFusionLab visible, "
        f"open {CLAIMED_URL}, then run this again. Last error: {last_error}"
    )


def iter_pages(browser) -> list:
    pages = []
    for ctx in browser.contexts:
        pages.extend(ctx.pages)
    return pages


def find_site_page(browser):
    claimed = None
    site = None
    for page in iter_pages(browser):
        try:
            url = page.url
        except Exception:
            continue
        if is_claimed_chat_url(url):
            claimed = page
            break
        if is_site_url(url) and site is None:
            site = page
    return claimed or site


def ensure_claimed_tab(browser, target_url: str = CLAIMED_URL):
    page = find_site_page(browser)
    if page is None:
        pages = iter_pages(browser)
        if not pages:
            raise RuntimeError("IX is attached but has no tabs. Open the claimed chat URL in that profile.")
        page = pages[0]
        _say(f"No Chat Home Base tab yet. Opening {target_url} in the existing IX tab.")
        page.goto(target_url, wait_until="domcontentloaded")
        return page
    if not is_claimed_chat_url(page.url):
        _say(f"IX is on {page.url}. Moving that tab to {target_url}.")
        page.goto(target_url, wait_until="domcontentloaded")
    return page


def read_snapshot(page) -> PageSnapshot:
    raw = page.evaluate(READ_PAGE_JS)
    loc = locality_from_profile_location(str(raw.get("profile_location") or ""))
    return PageSnapshot(
        url=str(raw.get("url") or page.url),
        waiting=bool(raw.get("waiting")),
        live=bool(raw.get("live")),
        chat_id=str(raw.get("chat_id") or "").strip(),
        customer_name=str(raw.get("customer_name") or "").strip(),
        profile_name=str(raw.get("profile_name") or "").strip(),
        profile_location=loc,
        title=str(raw.get("title") or ""),
    )


def scroll_history(page) -> int:
    try:
        return int(page.evaluate(SCROLL_HISTORY_JS) or 0)
    except Exception:
        return 0


def extract_history(page) -> list[dict[str, str]]:
    rows = page.evaluate(EXTRACT_MESSAGES_JS) or []
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        sender = str(row.get("sender") or "client").strip() or "client"
        if text:
            out.append({"sender": sender, "text": text})
    return out


def _assert_safe_click(testid: str) -> None:
    if is_forbidden_click(testid=testid):
        raise SendGuardError(f"Refusing to click {testid}")


def fill_draft(page, text: str) -> bool:
    """Type into the reply box. Chat Home Base rejects paste / set-value."""
    if not text:
        return False
    _assert_safe_click("messageTextArea")
    root = page.locator('[data-testid="messageTextArea"]')
    if root.count() == 0:
        return False
    box = root.locator("textarea")
    target = box.first if box.count() else root.first
    target.click()
    for _ in range(20):
        page.keyboard.press("Backspace")
    target.press_sequentially(text, delay=130)
    return True


def fill_customer_log(page, fields: dict[str, str]) -> bool:
    comment = logbook_comment(fields)
    if not comment:
        return False
    _assert_safe_click("addNewLogbookButton-customer")
    add = page.locator('[data-testid="addNewLogbookButton-customer"]')
    if add.count() == 0:
        return False
    add.first.click()
    page.wait_for_timeout(250)
    category = page.locator('[data-testid="logbookCategorySelect"]')
    if category.count():
        category.first.click()
        page.wait_for_timeout(200)
        other = page.get_by_text("Other", exact=True)
        if other.count():
            other.first.click()
        page.wait_for_timeout(150)
    comment_root = page.locator('[data-testid="logbookComment"]')
    if comment_root.count():
        box = comment_root.locator("textarea")
        target = box.first if box.count() else comment_root.first
        target.click()
        target.press_sequentially(comment, delay=15)
    save = page.locator('[data-testid="logbookSaveButton"]')
    send = page.locator('[data-testid="sendChatMessageButton"]')
    if save.count() and (send.count() == 0 or save.first.element_handle() != send.first.element_handle()):
        _assert_safe_click("logbookSaveButton")
        save.first.click()
        return True
    return False


def show_panel(page, payload: dict[str, Any]) -> None:
    try:
        page.evaluate(SHOW_PANEL_JS, payload)
    except Exception:
        pass


def process_live_chat(page, snapshot: PageSnapshot, logbook: Logbook) -> None:
    _say(f"[Copilot] Working claim {snapshot.chat_id or 'no chat-id'} / {snapshot.customer_name or 'this client'}")
    _say("[Copilot] Scrolling history so older messages can load...")
    scroll_history(page)
    history = extract_history(page)
    _say(f"[Copilot] Parsed {len(history)} messages (client vs operator).")
    result = handle_claimed_chat(
        history,
        client_id=snapshot.chat_id or snapshot.customer_name or "claimed",
        client_name=snapshot.customer_name,
        persona_city=snapshot.profile_location,
        logbook=logbook,
        remember=False,
    )
    payload = {
        "blocked": result.blocked,
        "reason": result.reason,
        "options": list(result.options),
        "never_send": True,
        "save_logbook": False,
        "logbook_fields": dict(result.logbook_fields),
        "fill_draft": result.fill_draft,
    }
    show_panel(page, payload)
    if result.fill_draft:
        fill_draft(page, result.fill_draft)
        _say("[Copilot] Typed the draft. Operator still sends — Send was not clicked.")
    elif result.blocked:
        _say(f"[Copilot] BLOCKED: {result.reason}. Draft box left empty.")


def run_attach(
    *,
    cdp_url: str | None = None,
    target_url: str = CLAIMED_URL,
    logbook_path: str | Path = "logbook.json",
    once: bool = False,
    poll_s: float = 1.5,
) -> int:
    _say("Scanning your already-open IX/Chrome window. No Local API needed.")
    _say(f"Target: {target_url}")
    try:
        playwright, browser = attach_playwright(cdp_url)
    except Exception as exc:
        _say(f"DevTools attach skipped: {exc}")
        if sys.platform == "win32":
            from .win_ui import run_uia_attach

            _say("Using the SensorFusionLab window you already opened (desktop control, no debug port).")
            return run_uia_attach(
                target_url=target_url,
                logbook_path=logbook_path,
                once=once,
                poll_s=poll_s,
            )
        _say(
            "This IX profile has no debug port. On Windows the copilot uses that open window anyway. "
            "Or add --remote-debugging-port=9222 to the IX profile extra launch args, Open the profile, and retry."
        )
        return 1
    logbook = Logbook(logbook_path)
    previous = PageSnapshot()
    try:
        page = ensure_claimed_tab(browser, target_url)
        _say("Waiting for a live claimed conversation (loader is not a claim)...")
        while True:
            try:
                if page.is_closed():
                    page = ensure_claimed_tab(browser, target_url)
                current = read_snapshot(page)
            except Exception as exc:
                _say(f"[Copilot] Tab read failed, retrying: {exc}")
                time.sleep(poll_s)
                continue
            if current.waiting:
                if previous.live or previous.waiting is False:
                    _say("[Copilot] Waiting for next claim...")
            if claim_became_live(previous, current):
                process_live_chat(page, current, logbook)
                if once:
                    return 0
            previous = current
            time.sleep(poll_s)
    except KeyboardInterrupt:
        _say("\n[copilot] stopped (IX window left open)")
        return 0
    finally:
        try:
            playwright.stop()
        except Exception:
            pass
        _say("Disconnected from IX Browser (window left open)")
    return 0
