# Offline Chat Copilot

Local, **non-AI** operator copilot. No LLM API, no token bill. It parses an incoming message with regex, fills a 3-slot template, then runs a hard-coded compliance filter. The operator still sends the message.

## Why this is not the sample `rule_engine.py` pasted as-is

The sketch in the request would fail real penalties:

| Policy | Sample engine | This engine |
| --- | --- | --- |
| Answer **every** question | First regex match wins (`where` beats sports) | Location and sports (and activity) can all land in Slot A |
| Location is a **city + 30–60 min** | `"right outside {city}"` is too close; `"neighborhood"` is not a city | `I'm about 45 minutes outside of Atlanta.` Minutes are 30–60 only |
| No parks / streets / time zones | No city validator | Rejects `Central Park`, `123 Peachtree St`, `EST` |
| Incoming illegal topics | Still drafts a flirty reply | Hard block, zero options |
| Meetup / `come over` | Only scans the outgoing string | Incoming meetup is **deflected**, never accepted |
| Unique messages | `random.choice` can emit the same CTA three times | Logbook remembers CTAs/drafts per client |
| Exactly one CTA | Count of `?` only | Assembly always ends with one question, then the filter checks it |
| 500+ CTAs | 10 canned questions | Generated bank of 500+ single questions, none of them meetup/contact asks |

## Install / run

Stdlib only. From this folder:

```bash
python3 rule_engine.py
python3 -m offline_copilot draft --name Nthabiseng --city Atlanta --id USETN4695969 \
  --message "Hey! Where are you located? Are you watching any games today?"
python3 -m offline_copilot check --text "I'm about 45 minutes outside of Atlanta. What's been the highlight of your week so far?" --city Atlanta --location-required
python3 -m offline_copilot note --id USETN4695969 --fact "Restores old Chevys"
```

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

The tool prints **three** options. It does not message the client. Edit if needed, then `check` the edited text before sending. Do not paste the same option to every client.
