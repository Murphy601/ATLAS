from __future__ import annotations

from pathlib import Path

from offline_copilot.chathomebase import logbook_comment
from offline_copilot.cities import extract_city_from_text
from offline_copilot.engine import handle_claimed_chat
from offline_copilot.ingest import (
    claim_rising_edge,
    extract_cities,
    extract_interests,
    extract_likes,
    extract_name,
    extract_places_for_log,
    ingest_history,
)
from offline_copilot.location import validate_city
from offline_copilot.logbook import Logbook


def test_extract_city_rejects_days_states_and_parks() -> None:
    assert extract_city_from_text("I'm from Monday") is None
    assert extract_city_from_text("I live in Texas") is None
    assert extract_city_from_text("meet me at Central Park") is None
    assert extract_city_from_text("I'm in Atlanta") == "Atlanta"
    assert extract_city_from_text("Dallas here") == "Dallas"
    assert validate_city("Monday")[0] is False
    assert validate_city("Texas")[0] is False
    assert validate_city("Central Park")[0] is False


def test_extract_cities_from_history_only_uses_client_turns() -> None:
    history = [
        {"sender": "operator", "text": "I'm in Houston"},
        {"sender": "client", "text": "I'm from Dallas"},
    ]
    cities = extract_cities(history)
    assert cities[0] == "Dallas"
    assert "Houston" not in cities


def test_extract_name_from_hi_im() -> None:
    assert extract_name("Hi I'm Nthabiseng") == "Nthabiseng"
    assert extract_name("I'm from Monday") is None


def test_interests_from_client_only() -> None:
    history = [
        {"sender": "operator", "text": "I watch NFL all day"},
        {"sender": "client", "text": "I like baseball and music"},
    ]
    interests = extract_interests(history)
    assert "Sports" in interests
    assert "Music" in interests


def test_claim_rising_edge() -> None:
    assert claim_rising_edge("", "Claimed") is True
    assert claim_rising_edge("Claimed", "Claimed") is False
    assert claim_rising_edge("", "Open") is False
    assert claim_rising_edge("", "Unclaimed") is False
    assert claim_rising_edge("Unclaimed", "Claimed") is True


def test_handle_claimed_chat_fills_logbook_and_never_sends(tmp_path: Path) -> None:
    result = handle_claimed_chat(
        [
            {"sender": "client", "text": "Hi I'm Nthabiseng from Atlanta"},
            {"sender": "operator", "text": "Hey, how's your day going?"},
            {"sender": "client", "text": "Where are you located? Are you watching any games today?"},
        ],
        client_id="USETN4695969",
        client_name="Nthabiseng",
        persona_city="Atlanta",
        logbook_dir=tmp_path,
    )
    assert result.never_send is True
    assert result.save_logbook is True
    assert result.logbook_fields["clientCity"] == "Atlanta"
    assert result.logbook_fields["clientName"] == "Nthabiseng"
    assert result.fill_draft
    assert len(result.options) == 3
    assert all("minutes outside of Atlanta" in opt for opt in result.options)


def test_ingest_skips_timestamp_when_picking_last_client_line() -> None:
    result = ingest_history(
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
        ]
    )
    assert "making sense" in result.last_client_message.casefold()
    assert "a few seconds ago" not in result.last_client_message.casefold()


def test_handle_claimed_chat_deflects_meetup_history(tmp_path: Path) -> None:
    result = handle_claimed_chat(
        [
            {"sender": "client", "text": "I'm from Dallas"},
            {"sender": "client", "text": "Come over tonight"},
        ],
        client_id="block-meet",
        persona_city="Dallas",
        logbook_dir=tmp_path,
    )
    assert result.blocked is False
    assert result.never_send is True
    assert result.options
    for option in result.options:
        assert "come over" not in option.casefold()
        assert "meet up" not in option.casefold()
        lowered = option.casefold()
        assert (
            "won't be able to fit that into my schedule" in lowered
            or "sweet of you to ask" in lowered
            or "a lot to process" in lowered
            or "flattered by your offer" in lowered
        )


def test_illegal_anywhere_in_history_hard_blocks(tmp_path: Path) -> None:
    result = handle_claimed_chat(
        [
            {"sender": "client", "text": "Let's talk about raping someone"},
            {"sender": "client", "text": "Where are you located?"},
        ],
        client_id="illegal-hist",
        logbook_dir=tmp_path,
    )
    assert result.blocked is True
    assert result.options == []
    assert result.fill_draft is None


def test_operator_questions_recorded_as_used_ctas(tmp_path: Path) -> None:
    book = Logbook(tmp_path / "logbook.json")
    handle_claimed_chat(
        [
            {"sender": "operator", "text": "What's been the highlight of your week so far?"},
            {"sender": "client", "text": "I'm from Atlanta. Just chilling."},
        ],
        client_id="cta-reuse",
        header_name="Alex",
        persona_city="Atlanta",
        logbook=book,
        remember=False,
    )
    used = book.used_cta_set("cta-reuse")
    assert any("highlight of your week" in item for item in used)


def test_ingest_history_skips_save_on_weak_facts() -> None:
    ingest = ingest_history([{"sender": "client", "text": "hey what's up"}])
    assert ingest.save_logbook is False
    assert ingest.city == ""
    assert ingest.client_name == ""


def test_ingest_captures_likes_places_and_important_details() -> None:
    ingest = ingest_history(
        [
            {
                "sender": "client",
                "text": "I have had a lot of experiences in life and solo travel had a lot to do with that.",
            },
            {
                "sender": "client",
                "text": "My fave place is Florence, Italy. Really old and its a great walking city.",
            },
            {
                "sender": "client",
                "text": "Most of my workdays were in SE Asia and I often traveled to Germany and countries like Thailand and China.",
            },
            {
                "sender": "client",
                "text": "I can move around by myself and have a cane and walker that I once used.",
            },
        ]
    )
    assert ingest.save_logbook is True
    assert any("Florence" in place for place in ingest.places)
    assert any("Italy" in place for place in ingest.places)
    assert "Germany" in ingest.places or any("Germany" in place for place in ingest.places)
    assert any("solo travel" in like.casefold() for like in ingest.likes)
    assert any("cane" in note.casefold() for note in ingest.notes)
    comment = logbook_comment(ingest.to_fields())
    assert "Places:" in comment
    assert "Florence" in comment
    assert "solo travel" in comment.casefold()
    assert "cane" in comment.casefold()
    assert extract_places_for_log("My fave place is Florence, Italy.")[0].startswith("Florence")
    assert "solo travel" in extract_likes("solo travel had a lot to do with that.")


def test_last_client_message_is_the_newest_not_old_history() -> None:
    ingest = ingest_history(
        [
            {"sender": "client", "text": "I am here is because of sex, but we can build a friendship"},
            {
                "sender": "client",
                "text": "My fave place is Florence, Italy. Really old and its a great walking city.",
            },
        ]
    )
    assert "Florence" in ingest.last_client_message
    assert "i am here is because" not in ingest.last_client_message.casefold()


def test_apply_ingest_does_not_overwrite_existing_city(tmp_path: Path) -> None:
    book = Logbook(tmp_path / "logbook.json")
    book.get("c1", name="Alex", city="Dallas")
    book.save()
    ingest = ingest_history([{"sender": "client", "text": "I'm from Atlanta"}])
    record = book.apply_ingest("c1", ingest)
    assert record.city == "Dallas"
    assert record.name == "Alex"
