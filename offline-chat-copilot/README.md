# Offline Chat Copilot

Local, **non-AI** operator copilot for [Chat Home Base claimed chat](https://chathomebase.com/chat/claimed). No LLM API. It attaches to the **IX Browser profile you already opened**, waits until a conversation is actually claimed, scrolls history, updates the logbook, and fills a draft. The operator still sends.

Same attach model as the EGO / Clip Export bot: the engine never launches Chrome and does not use IX Local API.

## Why `/chat/claimed` is not the trigger by itself

That URL is the waiting room **and** the live chat. While you wait, the page shows `claimLoaderContainer`. A real claim is `messageTextArea` + `messagesList` appearing (title may flicker `-> CHAT IS CLAIMED`). The bot keys off that rising edge, not the word “claimed” in the path (and not `Unclaimed`).

Customer bubbles use `.message-customer`. Persona/operator bubbles use `.message-profile`. Send is `[data-testid="sendChatMessageButton"]` and is **never clicked**.

## Run on an open IX profile

1. Click **Open** on the IX profile so SensorFusionLab Chromium is visible (debug port **9222**, same as the lidar bot).
2. Leave **https://chathomebase.com/chat/claimed** on screen (login yourself).
3. In a second PowerShell window:

```powershell
cd $env:USERPROFILE\ATLAS
git pull origin cursor/offline-chat-copilot-7517
cd offline-chat-copilot
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Or:

```bash
cd offline-chat-copilot
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
python3 -m offline_copilot attach
```

The engine ignores Google Chrome. It drives the IX process (`...\IXBrowser\...\chrome.exe`). If there is no Chat Home Base tab yet, it navigates **that already-open IX tab** to `/chat/claimed`. It never starts a second browser and never closes yours.

When a chat is claimed it:

1. Scrolls `messagesList` up so `.trigger-zone` can lazy-load older messages
2. Parses client vs operator turns
3. Writes a customer logbook comment (`Other`: city / interests) if facts are high-confidence
4. Puts option 1 in `messageTextArea`
5. Overlays three compliant options

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

1. **Slot A** — answer every asked question first (location window, activity, sports). Meetup / come over is deflected, never accepted. Incoming illegal topics hard-block with an empty draft box.
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
