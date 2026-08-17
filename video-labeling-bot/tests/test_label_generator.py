from types import SimpleNamespace

from config import OPENROUTER_MAX_ROUTE_FALLBACKS, VISION_MODELS
from label_generator import generate_label_from_frames


def test_generate_label_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert generate_label_from_frames(["aaa"]) == "No Action"


def test_generate_label_with_placeholder_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "your-actual-api-key-here")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert generate_label_from_frames(["aaa"]) == "No Action"


def test_falls_back_to_next_openrouter_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs["model"])
        fallbacks = (kwargs.get("extra_body") or {}).get("models", [])
        assert len(fallbacks) <= OPENROUTER_MAX_ROUTE_FALLBACKS
        if kwargs["model"] == VISION_MODELS[0]:
            raise RuntimeError("rate limit")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="pick up fork"))]
        )

    monkeypatch.setattr("label_generator.client.chat.completions.create", fake_create)
    assert generate_label_from_frames(["aaa"]) == "pick up fork"
    assert calls[0] == VISION_MODELS[0]
    assert calls[1] == VISION_MODELS[1]


def test_openrouter_route_fallbacks_are_capped_at_three(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    seen = []

    def fake_create(**kwargs):
        seen.append((kwargs.get("extra_body") or {}).get("models", []))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="pick up fork"))]
        )

    monkeypatch.setattr("label_generator.client.chat.completions.create", fake_create)
    assert generate_label_from_frames(["aaa"]) == "pick up fork"
    assert len(seen[0]) == OPENROUTER_MAX_ROUTE_FALLBACKS
    assert seen[0] == VISION_MODELS[1:4]
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")

    def fake_create(**kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr("label_generator.client.chat.completions.create", fake_create)
    assert generate_label_from_frames(["aaa"]) == "No Action"


def test_sanitize_still_runs_on_model_output(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")

    def fake_create(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="picking up 2 spoons and inspect handle.")
                )
            ]
        )

    monkeypatch.setattr("label_generator.client.chat.completions.create", fake_create)
    assert generate_label_from_frames(["aaa"]) == "pick up two spoons"
