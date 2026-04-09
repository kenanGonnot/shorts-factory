"""Unit tests for the voice domain (providers, renderer, VoiceTool)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.chains.state import PipelineState, Script
from app.services.storage import LocalStorage
from app.tools.voice_tool import VoiceTool
from app.voice.models import RenderedAudio
from app.voice.providers import (
    ElevenLabsProvider,
    SilentFallbackProvider,
    get_voice_provider,
)
from app.voice.renderer import ScriptVoiceRenderer


# ----- helpers --------------------------------------------------------------


class FakeProvider:
    """Test double matching the VoiceProvider interface."""

    name = "fake"

    def __init__(self, voice_id: str = "fake-voice", duration_ms: int | None = 250) -> None:
        from app.voice.models import VoiceConfig

        self.config = VoiceConfig(provider=self.name, voice_id=voice_id, model_id="fake-model")
        self._duration = duration_ms
        self.calls: list[str] = []

    def synthesize(self, text: str) -> RenderedAudio:
        self.calls.append(text)
        return RenderedAudio(
            audio=f"<{text}>".encode("utf-8"),
            mime_type="audio/mpeg",
            duration_ms=self._duration,
        )


def _script(body: str = "Body sentence one. Body sentence two.") -> Script:
    return {
        "title": "Title",
        "hook": "  Hook!!!  Catchy.  ",
        "body": body,
        "cta": "Subscribe now.",
        "tags": ["a"],
    }


# ----- normalization & chunking --------------------------------------------


def test_normalize_collapses_whitespace_and_punct_runs():
    assert ScriptVoiceRenderer.normalize("Hi!!!   World??.") == "Hi! World?."


def test_chunk_text_under_cap_returns_single_chunk():
    renderer = ScriptVoiceRenderer(FakeProvider(), max_chunk_chars=200)
    assert renderer.chunk_text("One sentence.") == ["One sentence."]


def test_chunk_text_splits_on_sentence_boundaries():
    renderer = ScriptVoiceRenderer(FakeProvider(), max_chunk_chars=20)
    out = renderer.chunk_text("First short. Second short. Third short.")
    assert all(len(c) <= 20 for c in out)
    assert "".join(out).replace(" ", "") == "Firstshort.Secondshort.Thirdshort."


def test_chunk_text_hard_wraps_long_sentence():
    renderer = ScriptVoiceRenderer(FakeProvider(), max_chunk_chars=15)
    out = renderer.chunk_text("alpha beta gamma delta epsilon zeta")
    assert all(len(c) <= 15 for c in out)
    assert " ".join(out).split() == "alpha beta gamma delta epsilon zeta".split()


# ----- renderer ------------------------------------------------------------


def test_renderer_emits_one_segment_per_section_when_short():
    provider = FakeProvider()
    renderer = ScriptVoiceRenderer(provider)
    result = renderer.render(_script())

    assert [s.section for s in result.segments] == ["hook", "body", "cta"]
    assert result.voice_provider == "fake"
    assert result.voice_id == "fake-voice"
    assert result.duration_ms == 750  # 3 chunks * 250ms
    assert result.audio == b"<Hook! Catchy.><Body sentence one. Body sentence two.><Subscribe now.>"


def test_renderer_chunks_long_body_and_preserves_section_traceability():
    provider = FakeProvider()
    renderer = ScriptVoiceRenderer(provider, max_chunk_chars=25)
    long_body = "Sentence one here. Sentence two here. Sentence three here."
    result = renderer.render(_script(body=long_body))

    body_segments = [s for s in result.segments if s.section == "body"]
    assert len(body_segments) >= 2
    assert [s.chunk_index for s in body_segments] == list(range(len(body_segments)))
    # Hook + CTA still present exactly once.
    assert sum(1 for s in result.segments if s.section == "hook") == 1
    assert sum(1 for s in result.segments if s.section == "cta") == 1


def test_renderer_skips_empty_sections():
    provider = FakeProvider()
    renderer = ScriptVoiceRenderer(provider)
    script: Script = {"title": "t", "hook": "Hi.", "body": "  ", "cta": "Bye.", "tags": []}
    result = renderer.render(script)
    assert [s.section for s in result.segments] == ["hook", "cta"]


# ----- provider selection ---------------------------------------------------


def test_get_voice_provider_auto_falls_back_when_no_key(monkeypatch):
    from app.core import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")
    monkeypatch.setenv("VOICE_PROVIDER", "auto")
    provider = get_voice_provider(config_module.Settings())
    assert isinstance(provider, SilentFallbackProvider)


def test_get_voice_provider_auto_picks_elevenlabs_with_key():
    from app.core.config import Settings

    provider = get_voice_provider(Settings(elevenlabs_api_key="sk-test", voice_provider="auto"))
    assert isinstance(provider, ElevenLabsProvider)
    assert provider.config.voice_id == "21m00Tcm4TlvDq8ikWAM"  # resolved from "Rachel"


def test_get_voice_provider_unknown_value_raises():
    from app.core.config import Settings

    with pytest.raises(ValueError):
        get_voice_provider(Settings(voice_provider="bogus"))


def test_elevenlabs_provider_uses_injected_client():
    captured: dict = {}

    class FakeResponse:
        content = b"AUDIO"

        def raise_for_status(self) -> None:  # pragma: no cover - no failure path tested
            return None

    class FakeClient:
        def post(self, url, headers, json):  # noqa: A002 - matches httpx signature
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    provider = ElevenLabsProvider(api_key="sk-test", voice_id="VID", client=FakeClient())
    out = provider.synthesize("hello world")
    assert out.audio == b"AUDIO"
    assert captured["url"].endswith("/VID")
    assert captured["headers"]["xi-api-key"] == "sk-test"
    assert captured["json"]["text"] == "hello world"
    assert captured["json"]["model_id"] == "eleven_turbo_v2"


def test_elevenlabs_provider_requires_api_key():
    with pytest.raises(ValueError):
        ElevenLabsProvider(api_key="", voice_id="x")


# ----- VoiceTool ------------------------------------------------------------


def test_voice_tool_persists_audio_and_segments(tmp_path: Path):
    storage = LocalStorage(str(tmp_path))
    provider = FakeProvider()
    tool = VoiceTool(provider=provider, storage=storage)

    state: PipelineState = {"job_id": "job-1", "topic": "x", "script": _script()}
    out = tool.run(state)

    # Required outputs.
    assert out["audio_path"] == str(tmp_path / "job-1" / "voice.mp3")
    assert (tmp_path / "job-1" / "voice.mp3").read_bytes().startswith(b"<Hook")

    # Optional metadata fields.
    assert out["voice_provider"] == "fake"
    assert out["voice_id"] == "fake-voice"
    assert out["audio_duration_ms"] == 750
    assert [s["section"] for s in out["audio_segments"]] == ["hook", "body", "cta"]

    # Persisted segment artifact.
    payload = json.loads((tmp_path / "job-1" / "voice.segments.json").read_text())
    assert payload["job_id"] == "job-1"
    assert payload["voice_provider"] == "fake"
    assert len(payload["segments"]) == 3


def test_voice_tool_does_not_mutate_input_state(tmp_path: Path):
    storage = LocalStorage(str(tmp_path))
    tool = VoiceTool(provider=FakeProvider(), storage=storage)

    state: PipelineState = {"job_id": "j2", "topic": "x", "script": _script()}
    snapshot = dict(state)
    tool.run(state)
    assert state == snapshot
    assert "audio_path" not in state


def test_voice_tool_storage_keys_are_deterministic_by_job_id(tmp_path: Path):
    storage = LocalStorage(str(tmp_path))
    tool = VoiceTool(provider=FakeProvider(), storage=storage)
    out1 = tool.run({"job_id": "same", "topic": "x", "script": _script()})
    out2 = tool.run({"job_id": "same", "topic": "x", "script": _script()})
    assert out1["audio_path"] == out2["audio_path"]
    assert out1["audio_segments_path"] == out2["audio_segments_path"]


def test_voice_tool_omits_duration_when_provider_does_not_report_it(tmp_path: Path):
    tool = VoiceTool(
        provider=FakeProvider(duration_ms=None),
        storage=LocalStorage(str(tmp_path)),
    )
    out = tool.run({"job_id": "j3", "topic": "x", "script": _script()})
    assert "audio_duration_ms" not in out
