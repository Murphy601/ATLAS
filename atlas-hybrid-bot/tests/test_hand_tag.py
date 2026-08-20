"""Tests for draft hand tag parsing."""

from hybrid_annotator import _hand_tag_from_draft


def test_hand_tag_from_draft_both_hands():
    assert _hand_tag_from_draft("sweep ground with hand broom in both hands") == "with both hands"


def test_hand_tag_from_draft_right():
    assert _hand_tag_from_draft("pick up fork with right hand") == "with right hand"
