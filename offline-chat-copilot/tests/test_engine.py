from datetime import date
import re

from offline_copilot.assembler import MEETUP_DEFLECTS
from offline_copilot.cta import CTA_BANK
from offline_copilot.engine import draft_replies, handle_claimed_chat
from offline_copilot.logbook import Logbook
from offline_copilot.parser import parse_message


def test_cta_bank_is_large_and_single_question() -> None:
    assert len(CTA_BANK) >= 500
    for item in CTA_BANK:
        assert item.endswith("?")
        assert item.count("?") == 1
        lowered = item.casefold()
        assert "come over" not in lowered
        assert "my dick" not in lowered
        assert "@" not in item


def test_parser_answers_both_location_and_sports() -> None:
    parsed = parse_message("Hey! Where are you located? Are you watching any games today?")
    assert parsed.asked_location
    assert parsed.asked_sports
    assert len(parsed.questions) == 2


def test_location_plus_sports_drafts_are_compliant(tmp_path) -> None:
    book = Logbook(tmp_path / "logbook.json")
    result = draft_replies(
        "Nthabiseng",
        "Atlanta",
        "Hey! Where are you located? Are you watching any games today?",
        client_id="USETN4695969",
        logbook=book,
        remember=True,
        today=date(2026, 8, 24),
    )
    assert not result.blocked, result.reason
    assert len(result.options) == 3
    assert len(set(result.options)) == 3
    for option in result.options:
        assert "Atlanta" in option
        assert "minutes" in option.casefold()
        assert option.count("?") == 1
        body = option.rsplit("?", 1)[0]
        assert re.search(r"\b(?:i(?:'m|'d|'ve|'ll)?|me|my)\b", body, flags=re.I)
        assert "come over" not in option.casefold()
        assert "my dick" not in option.casefold()
        assert "UFC" in option or "MLB" in option or "NFL" in option
        assert len(option) >= 75


def test_logbook_does_not_reuse_the_same_cta(tmp_path) -> None:
    book = Logbook(tmp_path / "logbook.json")
    first = draft_replies(
        "Alex",
        "Dallas",
        "What are you up to?",
        client_id="US-1",
        logbook=book,
        remember=True,
    )
    second = draft_replies(
        "Alex",
        "Dallas",
        "What are you up to?",
        client_id="US-1",
        logbook=book,
        remember=True,
    )
    assert not first.blocked and not second.blocked
    assert set(first.options).isdisjoint(set(second.options))


def test_three_options_are_not_the_same_template(tmp_path) -> None:
    result = draft_replies(
        "Alex",
        "Dallas",
        "I had a pretty good day at work and then I walked the dog.",
        client_id="US-opt",
        logbook=Logbook(tmp_path / "lb.json"),
        remember=False,
    )
    assert not result.blocked, result.reason
    assert len(set(result.options)) == 3
    stems = [option.split(".")[0] for option in result.options]
    assert len(set(stems)) == 3
    bridges = sum(1 for option in result.options if "thinking back to what you said" in option.casefold())
    assert bridges <= 1


def test_drafts_answer_the_latest_client_message(tmp_path) -> None:
    result = handle_claimed_chat(
        [
            {"sender": "client", "text": "I am here is because of sex, but we can build a friendship"},
            {"sender": "operator", "text": "That is great to know."},
            {
                "sender": "client",
                "text": "My fave place is Florence, Italy. Really old and its a great walking city.",
            },
        ],
        client_id="latest-msg",
        logbook_dir=tmp_path,
        remember=False,
    )
    assert not result.blocked, result.reason
    blob = " ".join(result.options).casefold()
    assert "florence" in blob or "italy" in blob
    assert "i am here is because" not in blob
    assert "thinking back to what you said" not in blob
    assert "trying," not in blob
    for option in result.options:
        assert option.count("?") == 1
        assert "favourite" not in option.casefold()
        assert "colour" not in option.casefold()


def test_drafts_answer_intimate_latest_not_small_talk(tmp_path) -> None:
    result = handle_claimed_chat(
        [
            {
                "sender": "client",
                "text": "I would like you to start being on top of me, you kissing me working your way down to put my cock in your mouth, sucking my balls from time to time",
            },
        ],
        client_id="bruce-latest",
        client_name="Bruce8111",
        logbook_dir=tmp_path,
        remember=False,
    )
    assert not result.blocked, result.reason
    blob = " ".join(result.options).casefold()
    assert "kiss" in blob or "on top" in blob or "mouth" in blob
    assert "weekday morning" not in blob
    assert "playlist" not in blob
    assert "hobby you'd pick back up" not in blob
    for option in result.options:
        assert option.count("?") == 1
        assert "my dick" not in option.casefold()
        assert "come over" not in option.casefold()
        assert len(option) >= 75


def test_drafts_answer_trust_message_not_small_talk(tmp_path) -> None:
    result = handle_claimed_chat(
        [
            {
                "sender": "client",
                "text": (
                    "I really felt the need to tell you that the way you use words makes me feel "
                    "that you are guy whom I can trust. You make me feel secure and feel a sense of "
                    "clarity. Am I making sense by saying this?"
                ),
            },
        ],
        client_id="trust-latest",
        logbook_dir=tmp_path,
        remember=False,
    )
    assert not result.blocked, result.reason
    blob = " ".join(result.options).casefold()
    assert "making sense" in blob or "trust" in blob or "secure" in blob
    assert "recharge after a long day" not in blob
    assert "playlist" not in blob
    for option in result.options:
        assert option.count("?") == 1
        assert len(option) >= 75


def test_timestamp_after_trust_message_is_not_answered(tmp_path) -> None:
    result = handle_claimed_chat(
        [
            {
                "sender": "client",
                "text": (
                    "I really felt the need to tell you that the way you use words makes me feel "
                    "that you are guy whom I can trust. You make me feel secure and feel a sense of "
                    "clarity. Am I making sense by saying this?"
                ),
            },
            {"sender": "client", "text": "Tue, Aug 25, 2026 — a few seconds ago"},
        ],
        client_id="trust-stamp",
        logbook_dir=tmp_path,
        remember=False,
    )
    assert not result.blocked, result.reason
    blob = " ".join(result.options).casefold()
    assert "making sense" in blob or "trust" in blob or "secure" in blob
    assert "recharge after a long day" not in blob


def test_illegal_incoming_returns_no_options(tmp_path) -> None:
    result = draft_replies(
        "Alex",
        "Dallas",
        "Let's talk about raping someone",
        client_id="US-2",
        logbook=Logbook(tmp_path / "lb.json"),
        remember=False,
    )
    assert result.blocked
    assert result.options == []


def _assert_tricky_chat_deflect(option: str) -> None:
    lowered = option.casefold()
    assert any(line.casefold() in lowered for line in MEETUP_DEFLECTS)
    assert "come over" not in lowered
    assert "meet up" not in lowered
    assert "let's meet" not in lowered
    assert "first-date" not in lowered
    assert "go on a date" not in lowered
    assert option.count("?") == 1


def test_meetup_ask_is_deflected_not_accepted(tmp_path) -> None:
    result = draft_replies(
        "Alex",
        "Dallas",
        "You should come over tonight",
        client_id="US-3",
        logbook=Logbook(tmp_path / "lb.json"),
        remember=False,
    )
    assert not result.blocked, result.reason
    assert len(result.options) == 3
    used_openers = set()
    for option in result.options:
        _assert_tricky_chat_deflect(option)
        for line in MEETUP_DEFLECTS:
            if line.casefold() in option.casefold():
                used_openers.add(line)
    assert len(used_openers) >= 2


def test_when_can_we_meet_uses_tricky_chat_redirects(tmp_path) -> None:
    parsed = parse_message("When can we meet?")
    assert parsed.meetup_request
    result = draft_replies(
        "Alex",
        "Dallas",
        "When can we meet?",
        client_id="US-3b",
        logbook=Logbook(tmp_path / "lb.json"),
        remember=False,
    )
    assert not result.blocked, result.reason
    for option in result.options:
        _assert_tricky_chat_deflect(option)


def test_bad_city_blocks_when_location_is_asked(tmp_path) -> None:
    result = draft_replies(
        "Alex",
        "Central Park",
        "Where do you live?",
        client_id="US-5",
        logbook=Logbook(tmp_path / "lb.json"),
        remember=False,
    )
    assert result.blocked
    assert result.options == []


def test_story_is_referenced(tmp_path) -> None:
    result = draft_replies(
        "Alex",
        "Dallas",
        "I love restoring old Chevys in my garage.",
        client_id="US-4",
        logbook=Logbook(tmp_path / "lb.json"),
        remember=False,
    )
    assert not result.blocked, result.reason
    blob = " ".join(result.options).casefold()
    assert "chevy" in blob or "restoring" in blob


def test_address_meetup_is_deflected_not_accepted(tmp_path) -> None:
    result = draft_replies(
        "Alex",
        "Dallas",
        "Yes. Are you home. If you are give me your address. I want to see you tonight. I want a hug and a kiss from you. Anything else is up to you",
        client_id="US-addr",
        logbook=Logbook(tmp_path / "lb.json"),
        remember=False,
    )
    assert not result.blocked, result.reason
    blob = " ".join(result.options).casefold()
    assert any(line.casefold() in blob for line in MEETUP_DEFLECTS)
    assert "give me your address" not in blob
    assert "see you tonight" not in blob
    assert not re.search(r"\b\d{1,6}\s+\w+\s+(?:st|street|ave|road)\b", blob)
    for option in result.options:
        assert option.count("?") == 1
        assert "recharge after a long day" not in option.casefold()
        assert "i heard your question" not in option.casefold()


def test_intimate_dick_taste_is_not_generic_ack(tmp_path) -> None:
    result = draft_replies(
        "Alex",
        "Dallas",
        "That's a very sweet dick you got there. I really would love to have a taste of it. Do you think that's possible?",
        client_id="US-taste",
        logbook=Logbook(tmp_path / "lb.json"),
        remember=False,
    )
    assert not result.blocked, result.reason
    blob = " ".join(result.options).casefold()
    assert "taste" in blob or "mouth" in blob or "greedy" in blob
    assert "i heard your question" not in blob
    assert "keep things interesting after a long day" not in blob
    assert "that actually made me smile" not in blob
    for option in result.options:
        assert "my dick" not in option.casefold()
        assert option.count("?") == 1
        assert len(option) >= 75


def test_married_attachment_is_not_generic_question_ack(tmp_path) -> None:
    result = draft_replies(
        "Alex",
        "Dallas",
        "Yeah, sure, I think we will see how it goes along the way. What will we do if we get attached, and yet you are married?",
        client_id="US-married",
        logbook=Logbook(tmp_path / "lb.json"),
        remember=False,
    )
    assert not result.blocked, result.reason
    blob = " ".join(result.options).casefold()
    assert "attached" in blob or "honest" in blob or "worry" in blob
    assert "i heard your question" not in blob
    assert "that actually made me smile" not in blob


def test_help_offer_is_not_generic_because_of_really(tmp_path) -> None:
    result = draft_replies(
        "Alex",
        "Dallas",
        "Really? That sounds bad, but am sure we can figure something out. I can help you",
        client_id="US-help",
        logbook=Logbook(tmp_path / "lb.json"),
        remember=False,
    )
    assert not result.blocked, result.reason
    blob = " ".join(result.options).casefold()
    assert "help" in blob or "figure" in blob or "offering" in blob
    assert "i heard your question" not in blob


def test_romantic_dinners_are_answered(tmp_path) -> None:
    result = draft_replies(
        "Alex",
        "Dallas",
        "I am a fan of romantic dinners. Do you also like being romantic with your lady? I will be waiting on it.",
        client_id="US-romance",
        logbook=Logbook(tmp_path / "lb.json"),
        remember=False,
    )
    assert not result.blocked, result.reason
    blob = " ".join(result.options).casefold()
    assert "romantic" in blob
    assert "i heard your question" not in blob


def test_different_last_bubbles_do_not_share_one_template(tmp_path) -> None:
    taste = draft_replies(
        "Alex",
        "Dallas",
        "That's a very sweet dick you got there. I really would love to have a taste of it.",
        client_id="US-a",
        logbook=Logbook(tmp_path / "a.json"),
        remember=False,
    )
    tables = draft_replies(
        "Alex",
        "Dallas",
        "Waiting tables for a friend tonight.",
        client_id="US-b",
        logbook=Logbook(tmp_path / "b.json"),
        remember=False,
    )
    assert not taste.blocked and not tables.blocked
    assert taste.options[0] != tables.options[0]
    taste_blob = taste.options[0].casefold()
    assert "taste" in taste_blob or "greedy" in taste_blob or "mouth" in taste_blob or "teasing" in taste_blob
    assert "waiting tables" in tables.options[0].casefold() or "shift" in tables.options[0].casefold()


def test_leaked_cta_on_history_still_answers_intimate(tmp_path) -> None:
    result = handle_claimed_chat(
        [
            {
                "sender": "client",
                "text": "That's a very sweet dick you got there. I really would love to have a taste of itg after a long day?",
            },
            {"sender": "client", "text": "07\u2011Aug\u20112026 \u2014 20 days ago"},
        ],
        client_id="leak-stamp",
        logbook_dir=tmp_path,
        remember=False,
    )
    assert not result.blocked, result.reason
    blob = " ".join(result.options).casefold()
    assert "taste" in blob or "mouth" in blob or "greedy" in blob
    assert "that actually made me smile" not in blob


def test_tonight_agenda_is_not_a_generic_smile(tmp_path) -> None:
    result = draft_replies(
        "Alex",
        "Dallas",
        "It could have been tonite but it’s on the agenda for tomorrow now",
        client_id="US-agenda",
        logbook=Logbook(tmp_path / "lb.json"),
        remember=False,
    )
    assert not result.blocked, result.reason
    blob = " ".join(result.options).casefold()
    assert "tomorrow" in blob or "agenda" in blob or "tonight" in blob
    assert "that actually made me smile" not in blob
    assert "come over" not in blob
    assert "see you tonight" not in blob
