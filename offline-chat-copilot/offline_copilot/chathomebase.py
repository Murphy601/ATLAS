"""Chat Home Base claimed-chat DOM. Selectors from the live Vue bundle. Never sends."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

CLAIMED_URL = "https://chathomebase.com/chat/claimed"

# Stable data-testid values from ChatBoxWindow / ClaimedChat / LogbookDialog.
SELECTORS = {
    "claimLoader": '[data-testid="claimLoaderContainer"]',
    "claimedNotice": '[data-testid="claimedNotification"]',
    "chatWindow": ".smart-chat-window-container",
    "messagesList": '[data-testid="messagesList"]',
    "messageItem": '[data-testid="messageItem"]',
    "messageContent": ".message-content",
    "customerBlob": ".message-customer",
    "profileBlob": ".message-profile",
    "loadMore": ".trigger-zone",
    "chatId": '[data-testid="chat-id"]',
    "customerName": '[data-testid="logbookCustomerName"]',
    "profileName": '[data-testid="logbookProfileName"]',
    "profileLocation": '[data-testid="profileLocation"]',
    "addCustomerLog": '[data-testid="addNewLogbookButton-customer"]',
    "logbookForm": '[data-testid="newLogbookForm"]',
    "logbookCategory": '[data-testid="logbookCategorySelect"]',
    "logbookComment": '[data-testid="logbookComment"]',
    "logbookSave": '[data-testid="logbookSaveButton"]',
    "draftBox": '[data-testid="messageTextArea"]',
    "sendButton": '[data-testid="sendChatMessageButton"]',
    "sendOptions": '[data-testid="sendChatMessageoptions"]',
}

FORBIDDEN_CLICK_TESTIDS = frozenset(
    {
        "sendChatMessageButton",
        "sendChatMessageoptions",
        "submitReportMessage",
    }
)
FORBIDDEN_CLICK_TEXT = ("send & end shift", "send message")

CUSTOMER_CLASS = "message-customer"
PROFILE_CLASS = "message-profile"


@dataclass
class PageSnapshot:
    url: str = ""
    waiting: bool = False
    live: bool = False
    chat_id: str = ""
    customer_name: str = ""
    profile_name: str = ""
    profile_location: str = ""
    title: str = ""

    @property
    def claimed(self) -> bool:
        """A live claimed conversation is on screen. The /chat/claimed URL alone is not enough."""
        return self.live and not self.waiting


def is_forbidden_click(testid: str = "", label: str = "") -> bool:
    tid = (testid or "").strip()
    if tid in FORBIDDEN_CLICK_TESTIDS:
        return True
    lowered = (label or "").casefold()
    if lowered in {"send", "send & end shift"}:
        return True
    return any(token in lowered for token in FORBIDDEN_CLICK_TEXT)


def snapshot_from_flags(
    *,
    url: str = "",
    has_loader: bool = False,
    has_draft: bool = False,
    chat_id: str = "",
    customer_name: str = "",
    title: str = "",
) -> PageSnapshot:
    waiting = has_loader and not has_draft
    live = has_draft
    return PageSnapshot(
        url=url,
        waiting=waiting,
        live=live,
        chat_id=chat_id.strip(),
        customer_name=customer_name.strip(),
        title=title,
    )


def claim_became_live(previous: PageSnapshot, current: PageSnapshot) -> bool:
    """Rising edge: waiting/empty -> live claimed chat, or a new chat-id."""
    if not current.claimed:
        return False
    if not previous.claimed:
        return True
    if current.chat_id and current.chat_id != previous.chat_id:
        return True
    return False


class _MessageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[dict[str, str]] = []
        self._item_depth = 0
        self._content_depth = 0
        self._is_customer = False
        self._buf: list[str] = []
        self._depth = 0
        self._item_start_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._depth += 1
        data = {key: (value or "") for key, value in attrs}
        testid = data.get("data-testid", "")
        classes = data.get("class", "")
        if testid == "messageItem":
            self._item_depth += 1
            self._item_start_depth = self._depth
            self._is_customer = False
            self._buf = []
        if self._item_depth:
            if CUSTOMER_CLASS in classes.split():
                self._is_customer = True
            if "message-content" in classes.split():
                self._content_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._content_depth:
            self._content_depth -= 1
        if self._item_depth and self._depth == self._item_start_depth:
            text = " ".join(" ".join(self._buf).split())
            if text:
                self.messages.append(
                    {
                        "sender": "client" if self._is_customer else "operator",
                        "text": text,
                    }
                )
            self._item_depth -= 1
            self._buf = []
        self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if self._item_depth and self._content_depth:
            self._buf.append(data)


def parse_messages(html: str) -> list[dict[str, str]]:
    parser = _MessageParser()
    parser.feed(html or "")
    return parser.messages


def parse_testid_text(html: str, testid: str) -> str:
    match = re.search(
        rf'data-testid="{re.escape(testid)}"[^>]*>([^<]*)',
        html or "",
        flags=re.I,
    )
    return " ".join((match.group(1) if match else "").split())


def logbook_comment(fields: dict[str, str]) -> str:
    parts: list[str] = []
    city = (fields.get("clientCity") or "").strip()
    interests = (fields.get("clientInterests") or "").strip()
    name = (fields.get("clientName") or "").strip()
    if name:
        parts.append(f"Name: {name}")
    if city:
        parts.append(f"City: {city}")
    if interests:
        parts.append(f"Interests: {interests}")
    return ". ".join(parts)


def locality_from_profile_location(text: str) -> str:
    blob = " ".join((text or "").split())
    match = re.search(r"locality:\s*([^,\n]+)", blob, flags=re.I)
    if match:
        return match.group(1).strip()
    return blob.replace("locality:", "").strip()


READ_PAGE_JS = """
() => {
  const textOf = (sel) => {
    const el = document.querySelector(sel);
    return (el && (el.innerText || el.textContent) || "").trim();
  };
  const has = (sel) => !!document.querySelector(sel);
  return {
    url: location.href,
    title: document.title || "",
    waiting: has('[data-testid="claimLoaderContainer"]') && !has('[data-testid="messageTextArea"]'),
    live: has('[data-testid="messageTextArea"]') || has('.smart-chat-window-container [data-testid="messagesList"]'),
    chat_id: textOf('[data-testid="chat-id"]'),
    customer_name: textOf('[data-testid="logbookCustomerName"]'),
    profile_name: textOf('[data-testid="logbookProfileName"]'),
    profile_location: textOf('[data-testid="profileLocation"]') + " " +
      ((document.querySelector('[data-testid="profileLocation"]') || {}).parentElement
        ? document.querySelector('[data-testid="profileLocation"]').parentElement.innerText
        : ""),
  };
}
"""

SCROLL_HISTORY_JS = """
async () => {
  const list = document.querySelector('[data-testid="messagesList"]');
  if (!list) return 0;
  let root = list;
  let hops = 0;
  while (root && hops < 8 && root.scrollHeight <= root.clientHeight + 4) {
    root = root.parentElement;
    hops += 1;
  }
  if (!root) root = list;
  let lastCount = list.querySelectorAll('[data-testid="messageItem"]').length;
  for (let i = 0; i < 12; i += 1) {
    root.scrollTop = 0;
    const zone = document.querySelector('.trigger-zone');
    if (zone && zone.scrollIntoView) zone.scrollIntoView({ block: "start" });
    await new Promise((r) => setTimeout(r, 450));
    const count = list.querySelectorAll('[data-testid="messageItem"]').length;
    if (count === lastCount && root.scrollTop === 0) break;
    lastCount = count;
  }
  return lastCount;
}
"""

EXTRACT_MESSAGES_JS = """
() => {
  const items = [...document.querySelectorAll('[data-testid="messageItem"]')];
  return items.map((el) => {
    const blob = el.querySelector('[data-testid^="messageBulb-"]') || el.querySelector('.message-blob');
    const isCustomer = !!(blob && blob.classList.contains('message-customer'));
    const text = ((el.querySelector('.message-content') || el).innerText || "").trim();
    return { sender: isCustomer ? "client" : "operator", text };
  }).filter((row) => row.text);
}
"""

SET_NATIVE_VALUE_JS = """
(value) => {
  const root = document.querySelector('[data-testid="messageTextArea"]');
  if (!root) return false;
  const el = root.tagName === "TEXTAREA" ? root : root.querySelector("textarea");
  if (!el) return false;
  const proto = HTMLTextAreaElement.prototype;
  const desc = Object.getOwnPropertyDescriptor(proto, "value");
  if (desc && desc.set) desc.set.call(el, value);
  else el.value = value;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return true;
}
"""

SHOW_PANEL_JS = """
(payload) => {
  let panel = document.getElementById("ocp-panel");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "ocp-panel";
    panel.style.cssText = "position:fixed;right:12px;bottom:12px;z-index:2147483647;max-width:380px;background:#111;color:#eee;border:1px solid #444;border-radius:10px;padding:12px;font:13px/1.4 sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.4)";
    document.body.appendChild(panel);
  }
  const options = payload.options || [];
  const blocked = payload.blocked ? `<div style="color:#f66">${payload.reason || "blocked"}</div>` : "";
  panel.innerHTML = `<strong>Offline copilot</strong> · never sends
    ${blocked}
    ${options.map((opt, i) => `<div style="margin-top:8px"><em>Option ${i + 1}</em><div>${opt}</div></div>`).join("")}`;
}
"""
