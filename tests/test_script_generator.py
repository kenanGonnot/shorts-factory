from __future__ import annotations

import pytest
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from app.chains.script_chain import build_script_chain
from app.chains.script_generator import ScriptGenerator
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_script_generator_uses_deterministic_fallback_without_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")

    generator = ScriptGenerator()

    first = generator.generate_script("Why coffee makes you focus")
    second = generator.generate_script("Why coffee makes you focus")

    assert first == second
    assert first["title"]
    assert len(first["tags"]) == 5
    assert first["cta"] == "Follow for more quick explainers."


def test_script_generator_matches_topic_language_in_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")

    script = ScriptGenerator().generate_script("Pourquoi le cafe aide a se concentrer")

    assert script["cta"] == "Abonne-toi pour plus d'explications rapides."
    assert "Pourquoi le cafe aide a se concentrer" in script["body"]


def test_script_generator_returns_valid_structured_output(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    generator = ScriptGenerator(
        structured_output_factory=lambda: RunnableLambda(
            lambda _: {
                "title": "Coffee timing for better focus",
                "hook": "Coffee sharpens focus because it blocks the tired signal.",
                "body": (
                    "Coffee blocks adenosine so your brain feels less sleepy. "
                    "That is why focus can improve quickly after a cup. "
                    "The effect feels smoother when you drink it after waking up. "
                    "Too much too late can still wreck your sleep."
                ),
                "cta": "Follow for more quick explainers.",
                "tags": ["Coffee", "Focus Tips", "Brain", "Science", "Shorts"],
            }
        )
    )

    script = generator.generate_script("Why coffee makes you focus")

    assert script["title"] == "Coffee timing for better focus"
    assert script["tags"] == ["coffee", "focus-tips", "brain", "science", "shorts"]


def test_script_generator_raises_for_invalid_structured_output(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    generator = ScriptGenerator(
        structured_output_factory=lambda: RunnableLambda(
            lambda _: {
                "title": "Coffee focus myth",
                "hook": "Coffee flips a switch in your brain.",
                "body": "It blocks tiredness. Then you feel more alert.",
                "cta": "Follow for more.",
                "tags": ["coffee", "focus", "brain"],
            }
        )
    )

    with pytest.raises(ValidationError):
        generator.generate_script("Why coffee makes you focus")


def test_build_script_chain_enriches_state_without_mutating_input(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")

    state = {"job_id": "job-1", "topic": "Why coffee makes you focus"}
    original = dict(state)

    out = build_script_chain().invoke(state)

    assert state == original
    assert out is not state
    assert out["script"]["title"]
