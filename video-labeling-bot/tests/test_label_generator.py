from types import SimpleNamespace

from config import DEFAULT_MODELS, OPENROUTER_MAX_ROUTE_FALLBACKS, VISION_MODELS
from label_generator import generate_label_from_frames

DISH_GOLD = (
    "hold glass plate with left hand, wipe glass plate with cloth in right hand"
)


def test_default_models_use_live_openrouter_vision_slugs():
    assert DEFAULT_MODELS == [
        "qwen/qwen2.5-vl-72b-instruct",
        "google/gemini-2.5-pro",
        "google/gemini-2.5-flash",
        "openai/gpt-4o",
    ]
    assert "anthropic/claude-3.5-sonnet" not in DEFAULT_MODELS
    assert "anthropic/claude-3.7-sonnet" not in DEFAULT_MODELS
    assert "google/gemini-1.5-pro" not in DEFAULT_MODELS
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
    assert generate_label_from_frames(["aaa"]) == "pick up fork with right hand"
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
    assert generate_label_from_frames(["aaa"]) == "pick up fork with right hand"
    assert len(seen[0]) == min(OPENROUTER_MAX_ROUTE_FALLBACKS, max(0, len(VISION_MODELS) - 1))
    assert seen[0] == VISION_MODELS[1 : 1 + OPENROUTER_MAX_ROUTE_FALLBACKS]
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
    assert generate_label_from_frames(["aaa"]) == "pick up two spoons with right hand"


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


def test_no_action_draft_is_ignored_and_tries_next_model(monkeypatch):
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
                    message=SimpleNamespace(
                        content=(
                            "hold stuffed animal with left hand, "
                            "trim stuffed animal with scissors in right hand"
                        )
                    )
                )
            ]
        )

    monkeypatch.setattr("label_generator.client.chat.completions.create", fake_create)
    assert generate_label_from_frames(
        ["aaa"],
        draft_label="No Action",
        previous_label="No Action",
    ) == (
        "hold stuffed animal with left hand, trim stuffed animal with scissors in right hand"
    )
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
    ) == "hold animal with left hand, trim animal with scissors in right hand"
    prompt = seen[0]
    assert draft not in prompt
    assert "Do NOT copy:" not in prompt
    assert "FRESH Atlas label" in prompt
    assert "bare animal" in prompt.lower() or 'NEVER write generic "animal"' in prompt
    assert "A toy is stuffed animal." not in prompt
    assert "If you see scissors, write trim" not in prompt


def test_real_frames_use_action_prompt_that_forbids_no_action(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    seen = []

    def fake_create(**kwargs):
        seen.append(_prompt_text(kwargs["messages"]))
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="wipe glass plate with cloth in right hand"
                    )
                )
            ]
        )

    monkeypatch.setattr("label_generator.client.chat.completions.create", fake_create)
    assert generate_label_from_frames(
        ["aaa"], frames_have_video=True
    ) == DISH_GOLD
    prompt = seen[0]
    assert "five seconds" in prompt
    assert 'or "No Action"' not in prompt
    assert "START — both hands" not in prompt
    assert "shoulder origin" in prompt.lower() or "LEFT hand appears on the RIGHT" in prompt


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
    ) == "hold animal with left hand, trim animal with scissors in right hand"
    assert calls[0] == VISION_MODELS[0]
    assert calls[1] == VISION_MODELS[1]


def test_retries_no_action_with_hand_work_prompt(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs["model"])
        texts = []
        for message in kwargs["messages"]:
            content = message.get("content")
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        texts.append(part.get("text") or "")
        prompt = "\n".join(texts)
        if "five seconds" in prompt or "task-relevant hold" in prompt:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                "hold stuffed animal with left hand, "
                                "trim stuffed animal with scissors in right hand"
                            )
                        )
                    )
                ]
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="No Action"))]
        )

    monkeypatch.setattr("label_generator.client.chat.completions.create", fake_create)
    assert generate_label_from_frames(
        ["aaa"],
        draft_label="hold animal with left hand, trim animal with scissors in right hand",
        frames_have_video=True,
    ) == (
        "hold animal with left hand, trim animal with scissors in right hand"
    )
    assert len(calls) == 1


def test_keeps_glass_plate_draft_when_model_repeats_stuffed_animal(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    draft = "rotate glass plate with both hands"

    def fake_create(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            "hold stuffed animal with left hand, "
                            "trim stuffed animal with scissors in right hand"
                        )
                    )
                )
            ]
        )

    monkeypatch.setattr("label_generator.client.chat.completions.create", fake_create)
    assert generate_label_from_frames(["aaa"], draft_label=draft) == draft


def test_uses_model_when_frames_show_a_different_scene(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    leftover = (
        "hold stuffed animal with left hand, trim stuffed animal with scissors in right hand"
    )

    def fake_create(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="wipe glass plate with cloth in right hand"
                    )
                )
            ]
        )

    monkeypatch.setattr("label_generator.client.chat.completions.create", fake_create)
    assert generate_label_from_frames(
        ["aaa"],
        draft_label=leftover,
        frames_have_video=True,
    ) == DISH_GOLD


def test_retries_when_flash_hallucinates_against_specific_draft(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    calls = []
    draft = "hold cap with left hand, insert needle into patch with right hand"

    def fake_create(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == VISION_MODELS[0]:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                "hold hat with left hand, write on hat with pen in right hand"
                            )
                        )
                    )
                ]
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            "hold cap with left hand, insert needle into patch with right hand"
                        )
                    )
                )
            ]
        )

    monkeypatch.setattr("label_generator.client.chat.completions.create", fake_create)
    gold = (
        "hold cap with both hands, insert sewing needle into cap with right hand"
    )
    assert generate_label_from_frames(
        ["aaa"],
        draft_label=draft,
        frames_have_video=True,
    ) == gold
    assert calls[0] == VISION_MODELS[0]


def test_skips_copied_prompt_example(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == VISION_MODELS[0]:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="work dough with both hands")
                    )
                ]
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="wipe glass plate with cloth in right hand"
                    )
                )
            ]
        )

    monkeypatch.setattr("label_generator.client.chat.completions.create", fake_create)
    assert generate_label_from_frames(
        ["aaa"],
        frames_have_video=True,
    ) == DISH_GOLD
    assert calls[0] == VISION_MODELS[0]
    assert calls[1] == VISION_MODELS[1]
