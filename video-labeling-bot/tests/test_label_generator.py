import os

from label_generator import generate_label_from_frames


def test_generate_label_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert generate_label_from_frames(["aaa"]) == "No Action"


def test_generate_label_with_placeholder_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "your-actual-api-key-here")
    assert generate_label_from_frames(["aaa"]) == "No Action"
