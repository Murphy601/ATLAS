# Offline Chat Copilot

Local, **non-AI** operator copilot for [Chat Home Base claimed chat](https://chathomebase.com/chat/claimed). No LLM API. It attaches to the **IX Browser profile you already opened**, waits until a conversation is actually claimed, reads the last customer bubble, and fills a draft. The operator still sends and still adds logbook entries.

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

The engine ignores Google Chrome. It drives the IX process (`...\IXBrowser\...\chrome.exe` or `...\ixBrowser-Resources\...\chrome.exe`). If DevTools is off, it focuses that same window and fills the reply box from the desktop. It never starts a second browser and never closes yours. The `/chat/claimed` waiting room shows **Waiting for conversation to be claimed...** That is not a claim. Performance / wish-list overlays are not a claim either. The copilot must not type into the Chromium address bar or the page search box. Clients rotate: each new chat-id / customer handle is a new claim (left column, not the persona under “you are”). On a real claim you should see the mouse scroll the thread, then **slow** characters appearing in **Type your reply here...**. Paste is never used. The operator adds logbook entries by hand.

The claim timer is about 3 minutes. The copilot should pick the last customer bubble and type a draft in **under 2 minutes**. It does not click PROFILE DETAILS or ADD NEW LOG.

When a chat is claimed it:

1. Scrolls the thread briefly so the newest customer bubble is visible
2. Picks that **customer bubble** (never a timestamp like `Tue, Aug 25, 2026 — a few seconds ago`, never Rental home)
3. Builds a first-person reply that answers **that** line
4. Types option 1 into `messageTextArea` with real keypresses (no paste, no Unicode dump)
5. Prints three compliant options (75+ characters)

The engine is a local rule matcher, not a cloud LLM. After it locks the last customer line, it matches that text (trust, location, intimate, and so on) and writes a reply to it. Older history is not the thing being answered.

The reply answers the **most recent client message**, in US English. Older bubbles are not the line being answered. It does not click Send, Send & End Shift, or report-submit. It does not press Enter after typing.

## CLI without the browser

```bash
python3 rule_engine.py
python3 -m offline_copilot draft --name Nthabiseng --city Atlanta --id USETN4695969 \
  --message "Hey! Where are you located? Are you watching any games today?"
python3 -m pytest
```

The Tampermonkey file `userscript/chat-copilot.user.js` is a fallback (`@match` is already `chathomebase.com`). Prefer `attach` on IX.

## Message formula

1. **Slot A** — warm first-person answer to the **latest** client message (location window, activity, sports when asked). Meetup / come over is deflected, never accepted. Incoming illegal topics anywhere in the thread hard-block with an empty draft box.
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
