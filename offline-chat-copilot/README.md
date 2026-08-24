# Offline Chat Copilot

Local, **non-AI** operator copilot. No LLM API, no token bill. A Tampermonkey userscript watches the dashboard for a **Claimed** edge, scrolls chat history, and POSTs it to a localhost Python controller. The controller parses entities, updates a JSON logbook, fills logbook fields via the userscript, and puts one compliant draft in the reply box. The operator still sends.

## Why the pasted userscript is not shipped as-is

| Risk | Sample script | This tree |
| --- | --- | --- |
| `@match https://*/*` | Runs on every HTTPS site | Placeholder match; set it to **one** dashboard |
| `from Monday` / `from Texas` as a city | `\b(?:in\|from\|near)\s+([A-Z][a-z]+)\b` | US city list; states, weekdays, parks rejected |
| React/controlled inputs | `el.value =` | `setNativeValue` + `input`/`change` |
| Observer spam | `document.body`, no debounce, claimed flag flicker | 200ms debounce; rising edge only; `Unclaimed` is not claimed |
| Lazy history | `scrollTop = 0` three times | Incremental scroll-up until height stops growing |
| Engine | None; regex in the page | `POST http://127.0.0.1:8765/claim` to the stdlib controller |
| Send | Easy to wire a send click later | `autoSend` locked false; send button is never clicked |
| Bind | n/a | Controller refuses anything except localhost |

Meetup / `come over` in history is **deflected**, not accepted. Incoming illegal topics (minors, rape, etc.) hard-block: zero drafts, nothing is filled in the reply box.

## Install / run

Stdlib only. From this folder:

```bash
# One-shot CLI (no browser)
python3 rule_engine.py
python3 -m offline_copilot draft --name Nthabiseng --city Atlanta --id USETN4695969 \
  --message "Hey! Where are you located? Are you watching any games today?"

# Local desktop controller for the userscript (127.0.0.1 only)
python3 -m offline_copilot serve --host 127.0.0.1 --port 8765
```

Then in Tampermonkey / Violentmonkey:

1. Create a new script and paste `userscript/chat-copilot.user.js`.
2. Change `@match` from `https://YOUR-OPERATOR-DASHBOARD.example/*` to the real dashboard origin.
3. Adjust `CONFIG.selectors` to that dashboard's classes. The defaults are placeholders.
4. Set `CONFIG.personaCity` if the logbook has a "my city" field.

The userscript POSTs:

```json
{
  "client_id": "...",
  "client_name": "...",
  "persona_city": "...",
  "history": [{"sender": "client|operator", "text": "..."}]
}
```

The controller always returns `"never_send": true`. Option 1 is copied into the draft box only. It never clicks Send / Submit.

Tests:

```bash
python3 -m pytest
```

## Message formula

1. **Slot A** — answer every asked question first (location window, activity, sports). If they asked to meet, deflect. If they told a story, reference it.
2. **Slot B** — optional sports/small-talk from the calendar (UFC Fight Night 22–23 Aug 2026, MLB regular season, NFL pre-season).
3. **Slot C** — exactly one open-ended CTA from the bank, never reused for that client if the logbook is on.

Then `validate_draft` must pass or the option is discarded.

## Operator still owns the send

The tool prints **three** options (and the userscript overlays them). It does not message the client. Edit if needed, then `check` the edited text before sending. Do not paste the same option to every client.
