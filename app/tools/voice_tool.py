"""Voice generation pipeline stage.

``VoiceTool`` is intentionally thin: it reads pipeline state, picks the
configured TTS provider, delegates rendering to
:class:`ScriptVoiceRenderer`, persists the audio + segment metadata, and
returns an enriched state dict.
"""
from __future__ import annotations

import json

from app.chains.state import PipelineState
from app.core.logging import log
from app.services.storage import Storage, get_storage
from app.tools.base import PipelineTool
from app.voice.providers import VoiceProvider, get_voice_provider
from app.voice.renderer import ScriptVoiceRenderer


class VoiceTool(PipelineTool):
    name = "VoiceTool"

    def __init__(
        self,
        provider: VoiceProvider | None = None,
        storage: Storage | None = None,
        renderer: ScriptVoiceRenderer | None = None,
    ) -> None:
        # All dependencies are lazily resolved at run() time so tests can
        # instantiate VoiceTool() with no network or storage side effects.
        self._provider = provider
        self._storage = storage
        self._renderer = renderer

    def run(self, state: PipelineState) -> PipelineState:
        job_id = state["job_id"]
        script = state["script"]

        provider = self._provider or get_voice_provider()
        renderer = self._renderer or ScriptVoiceRenderer(provider)
        storage = self._storage or get_storage()

        result = renderer.render(script)

        audio_key = f"{job_id}/voice.mp3"
        segments_key = f"{job_id}/voice.segments.json"

        audio_path = storage.save(audio_key, result.audio)
        segments_payload = {
            "job_id": job_id,
            "voice_provider": result.voice_provider,
            "voice_id": result.voice_id,
            "duration_ms": result.duration_ms,
            "segments": result.segments_as_dicts(),
        }
        segments_path = storage.save(
            segments_key,
            json.dumps(segments_payload, ensure_ascii=False, indent=2).encode("utf-8"),
        )

        log.info(
            "voice.rendered",
            job_id=job_id,
            provider=result.voice_provider,
            voice_id=result.voice_id,
            segments=len(result.segments),
            duration_ms=result.duration_ms,
        )

        enriched: PipelineState = {
            **state,
            "audio_path": audio_path,
            "audio_segments_path": segments_path,
            "audio_segments": result.segments_as_dicts(),
            "voice_provider": result.voice_provider,
            "voice_id": result.voice_id,
        }
        if result.duration_ms is not None:
            enriched["audio_duration_ms"] = result.duration_ms
        return enriched
