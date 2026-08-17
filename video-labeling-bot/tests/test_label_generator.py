from types import SimpleNamespace

from config import DEFAULT_MODELS, OPENROUTER_MAX_ROUTE_FALLBACKS, VISION_MODELS
from label_generator import generate_label_from_frames


def test_default_models_are_cheapest_first():
    assert DEFAULT_MODELS[0] == "anthropic/claude-sonnet-5"
    assert "google/gemini-2.5-flash" in DEFAULT_MODELS
    assert "openai/gpt-4o-mini" in DEFAULT_MODELS
    assert "qwen/qwen2.5-vl-72b-instruct" in DEFAULT_MODELS
    assert VISION_MODELS[0] == DEFAULT_MODELS[0]
    assert ":free" not in "".join(DEFAULT_MODELS)


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


def test_generate_label_reconciles_trailing_hold_with_draft(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")

    def fake_create(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            "water plant in bucket with hose in left hand, "
                            "hold watering can with right hand"
                        )
                    )
                )
            ]
        )

    monkeypatch.setattr("label_generator.client.chat.completions.create", fake_create)
    assert generate_label_from_frames(
        ["aaa"],
        draft_label="water plant in bucket with hose in both hands",
        duration_seconds=5.0,
    ) == "water plant in bucket with hose in both hands"


def test_skips_no_action_when_draft_describes_work(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == VISION_MODELS[0]:
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="No Action"))]
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="dig soil with hoe in right hand")
                )
            ]
        )

    monkeypatch.setattr("label_generator.client.chat.completions.create", fake_create)
    assert generate_label_from_frames(
        ["aaa"],
        draft_label="dig soil with tool in right hand",
        previous_label="pick up hoe with right hand",
    ) == "dig soil with hoe in right hand"
    assert calls[0] == VISION_MODELS[0]
    assert calls[1] == VISION_MODELS[1]


def _prompt_text(messages) -> str:
    chunks = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    chunks.append(part.get("text") or "")
    return "\n".join(chunks)


def test_prompt_does_not_include_atlas_draft(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    seen = []
    draft = "hold animal with left hand, trim animal with scissors in right hand"

    def fake_create(**kwargs):
        seen.append(_prompt_text(kwargs["messages"]))
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="hold sheep with left hand, trim wool with scissors in right hand"
                    )
                )
            ]
        )

    monkeypatch.setattr("label_generator.client.chat.completions.create", fake_create)
    assert generate_label_from_frames(
        ["aaa"],
        draft_label=draft,
        previous_label=draft,
        duration_seconds=5.0,
    ) == "hold sheep with left hand, trim wool with scissors in right hand"
    prompt = seen[0]
    assert draft not in prompt
    assert "Do NOT copy:" not in prompt
    assert "FRESH Atlas label" in prompt
    assert "never animal" in prompt.lower()


def test_generic_animal_output_tries_next_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == VISION_MODELS[0]:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                "hold animal with left hand, "
                                "trim animal with scissors in right hand"
                            )
                        )
                    )
                ]
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="hold sheep with left hand, trim wool with scissors in right hand"
                    )
                )
            ]
        )

    monkeypatch.setattr("label_generator.client.chat.completions.create", fake_create)
    assert generate_label_from_frames(
        ["aaa"],
        draft_label="hold animal with left hand, trim animal with scissors in right hand",
    ) == "hold sheep with left hand, trim wool with scissors in right hand"
    assert calls[0] == VISION_MODELS[0]
    assert calls[1] == VISION_MODELS[1]
