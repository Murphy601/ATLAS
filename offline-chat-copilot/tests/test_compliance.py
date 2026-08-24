"""Penalty-table checks for outgoing drafts and incoming hard blocks."""

from offline_copilot.compliance import validate_draft, validate_incoming
from offline_copilot.location import location_sentence, validate_city


def test_banned_body_phrases() -> None:
    ok, why = validate_draft("I miss you. Come over later?")
    assert not ok
    assert "come over" in why
    ok, why = validate_draft("My dick is all I think about. What's up?")
    assert not ok
    assert "my dick" in why


def test_meetup_and_contact_are_blocked() -> None:
    assert validate_draft("Let's meet up tomorrow. How was your day?")[0] is False
    assert validate_draft("Text me at 404-555-0182 and tell me more?")[0] is False
    assert validate_draft("Email me at test@example.com later?")[0] is False
    assert validate_draft("I'm a paid moderator, want to chat more?")[0] is False
    assert validate_draft("Venmo me if you want a longer chat?")[0] is False


def test_exactly_one_cta_at_the_end() -> None:
    assert validate_draft("I'm about 45 minutes outside of Atlanta.")[0] is False
    assert validate_draft("I'm about 45 minutes outside of Atlanta. One? Two?")[0] is False
    good = "I'm about 45 minutes outside of Atlanta. What's been the highlight of your week so far?"
    ok, why = validate_draft(good, client_city="Atlanta", location_required=True)
    assert ok, why


def test_location_window_and_city() -> None:
    ok, why = validate_city("Atlanta")
    assert ok, why
    assert validate_city("Central Park")[0] is False
    assert validate_city("EST")[0] is False
    assert validate_city("123 Peachtree Street")[0] is False
    sentence = location_sentence("Atlanta", 45)
    assert "45 minutes" in sentence
    assert "Atlanta" in sentence
    missing = "I live nearby. What's new?"
    assert validate_draft(missing, client_city="Atlanta", location_required=True)[0] is False
    timezone = "I'm on EST. What's new?"
    assert validate_draft(timezone, client_city="Atlanta", location_required=True)[0] is False


def test_incoming_illegal_is_a_hard_stop() -> None:
    ok, why = validate_incoming("she is 14 years old and cute")
    assert not ok
    assert "illegal" in why.casefold()
    ok, why = validate_incoming("Hey! Where are you located?")
    assert ok
