from datetime import date

from offline_copilot.cta import CTA_BANK
from offline_copilot.engine import draft_replies
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
        assert "come over" not in option.casefold()
        assert "my dick" not in option.casefold()
        assert "UFC" in option or "MLB" in option or "NFL" in option


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
    for option in result.options:
        assert "keeping this in chat" in option.casefold()
        assert "come over" not in option.casefold()
        assert option.count("?") == 1


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
