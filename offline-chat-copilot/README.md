# Offline Chat Copilot

Local, **non-AI** operator copilot for [Chat Home Base claimed chat](https://chathomebase.com/chat/claimed). No LLM API. It attaches to the **IX Browser profile you already opened**, waits until a conversation is actually claimed, scrolls history, updates the logbook, and fills a draft. The operator still sends.

Same attach model as the EGO / Clip Export bot: the engine never launches Chrome and does not use IX Local API.

## Why `/chat/claimed` is not the trigger by itself

That URL is the waiting room **and** the live chat. While you wait, the page shows `claimLoaderContainer`. A real claim is `messageTextArea` + `messagesList` appearing (title may flicker `-> CHAT IS CLAIMED`). The bot keys off that rising edge, not the word “claimed” in the path (and not `Unclaimed`).

Customer bubbles use `.message-customer`. Persona/operator bubbles use `.message-profile`. Send is `[data-testid="sendChatMessageButton"]` and is **never clicked**.

## Run on an open IX profile

Most IX profiles do **not** expose DevTools. The copilot still uses the SensorFusionLab window you already opened (same desktop attach as the lidar bot). Port 9222 is optional.

1. Click **Open** on the IX profile so SensorFusionLab Chromium is visible. `ixBrowser | v2.9.20` is only the profile list.
2. Leave **https://chathomebase.com/chat/claimed** on screen (login yourself).
3. In a second PowerShell window:

```powershell
cd $env:USERPROFILE\ATLAS
git fetch origin
git checkout -B cursor/offline-chat-copilot-7517 origin/cursor/offline-chat-copilot-7517
cd offline-chat-copilot
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

`git pull origin cursor/offline-chat-copilot-7517` while you are still on another branch tries to merge and then asks for a git name/email. **Checkout** the copilot branch instead. You do not need `git config user.name` for that.

Or:

```bash
cd offline-chat-copilot
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
python3 -m offline_copilot attach
```

The engine ignores Google Chrome. It drives the IX process (`...\IXBrowser\...\chrome.exe` or `...\ixBrowser-Resources\...\chrome.exe`). If DevTools is off, it focuses that same window and fills the reply box from the desktop. It never starts a second browser and never closes yours. The `/chat/claimed` waiting room is not a claim; it waits until `messageTextArea` / messages are actually on screen. Clients rotate: each new chat-id / customer handle is a new claim (left column, not the persona under “you are”). You should see the mouse scroll the thread, click the customer logbook, then characters appearing in the reply box. Paste is never used.

Optional, for full DOM (scroll history + customer logbook): in the IX profile extra launch args add `--remote-debugging-port=9222`, click Open, then run again.

When a chat is claimed it:

1. Scrolls the thread so older messages can load
2. Opens customer **PROFILE DETAILS**, then **ADD NEW LOG** (left column, not the persona)
3. Types a customer logbook comment (`Other`) if facts are high-confidence — never paste
4. Types option 1 into `messageTextArea` (Chat Home Base rejects copy/paste)
5. Prints three compliant options (75+ characters; the site shows “too short” under 75)

It does not click Send, Send & End Shift, or report-submit. It does not press Enter after typing.

It does not click Send, Send & End Shift, or report-submit.

## CLI without the browser

```bash
python3 rule_engine.py
python3 -m offline_copilot draft --name Nthabiseng --city Atlanta --id USETN4695969 \
  --message "Hey! Where are you located? Are you watching any games today?"
python3 -m pytest
```

The Tampermonkey file `userscript/chat-copilot.user.js` is a fallback (`@match` is already `chathomebase.com`). Prefer `attach` on IX.

## Message formula

1. **Slot A** — first-person answer to every asked question (location window, activity, sports). Meetup / come over is deflected, never accepted. Incoming illegal topics hard-block with an empty draft box.
2. **Slot B** — optional sports/small-talk from the calendar.
3. **Slot C** — exactly one open-ended CTA.

## Tricky chats (when can we meet)

Never accept a meetup. Never propose a time or place. Never ask a dating follow-up like “first-date no-nos” — that still sounds like a date is on the table and it would add a second `?`.

Slot A uses one of four redirects, then Slot C is the only question:

1. **Acknowledge & redirect** — schedule does not work, then shift.
2. **Cool it down** — that’s sweet, not the right time, then shift.
3. **Humor** — a lot to process, deserve a drink, then shift (no “new spot” invite).
4. **Gratitude & shift** — flattered, thanks, different note.

The three draft options rotate those openers so they do not all sound like the same excuse.

## Operator still owns the send

The tool fills a draft and shows three options. Edit if needed, then send yourself.
