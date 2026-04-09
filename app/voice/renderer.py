"""Script → audio renderer.

The renderer is the only place that knows how to:

- normalize text for speech (whitespace + punctuation cleanup, no rewriting),
- chunk long sections while preserving section traceability,
- call a :class:`VoiceProvider` once per chunk,
- merge chunks into one final audio asset, and
- emit segment metadata.
"""
from __future__ import annotations

import re
from typing import Iterable

from app.chains.state import Script
from app.voice.models import (
    ScriptSection,
    VoiceRenderResult,
    _MutableSegmentBuilder,
)
from app.voice.providers import VoiceProvider

# Sections in the order they should be spoken.
_SECTION_ORDER: tuple[ScriptSection, ...] = ("hook", "body", "cta")

# Soft cap per chunk. ElevenLabs handles much longer inputs, but chunking by
# sentence keeps retries cheap and lets us emit segment-level metadata.
DEFAULT_MAX_CHUNK_CHARS = 480

_WHITESPACE_RE = re.compile(r"\s+")
# Collapse runs of repeated punctuation like "!!!" or "??!" into one mark.
_PUNCT_RUN_RE = re.compile(r"([!?.,;:])\1+")
# Sentence boundary that keeps the trailing punctuation.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


class ScriptVoiceRenderer:
    """Render a structured :class:`Script` into one merged audio asset."""

    def __init__(
        self,
        provider: VoiceProvider,
        max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    ) -> None:
        self._provider = provider
        self._max_chunk_chars = max_chunk_chars

    # ---- public API ----------------------------------------------------

    def render(self, script: Script) -> VoiceRenderResult:
        builder = _MutableSegmentBuilder()
        audio_chunks: list[bytes] = []
        mime_type = "audio/mpeg"
        total_duration: int | None = 0
        any_duration_known = False

        for section in _SECTION_ORDER:
            raw = script.get(section, "") or ""
            normalized = self.normalize(raw)
            if not normalized:
                continue
            for chunk in self.chunk_text(normalized):
                rendered = self._provider.synthesize(chunk)
                audio_chunks.append(rendered.audio)
                mime_type = rendered.mime_type or mime_type
                builder.add(section, chunk, rendered.duration_ms)
                if rendered.duration_ms is not None:
                    total_duration = (total_duration or 0) + rendered.duration_ms
                    any_duration_known = True

        merged = self._merge(audio_chunks)
        return VoiceRenderResult(
            audio=merged,
            mime_type=mime_type,
            segments=builder.segments,
            voice_provider=self._provider.config.provider,
            voice_id=self._provider.config.voice_id,
            duration_ms=total_duration if any_duration_known else None,
        )

    # ---- normalization & chunking -------------------------------------

    @staticmethod
    def normalize(text: str) -> str:
        """Whitespace + punctuation cleanup. Never rewrites meaning."""
        if not text:
            return ""
        cleaned = _PUNCT_RUN_RE.sub(r"\1", text)
        cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
        return cleaned

    def chunk_text(self, text: str) -> list[str]:
        """Split ``text`` into chunks no longer than ``max_chunk_chars``.

        Splits on sentence boundaries first, then falls back to word
        boundaries for sentences that exceed the cap on their own.
        """
        if len(text) <= self._max_chunk_chars:
            return [text]

        sentences = _SENTENCE_SPLIT_RE.split(text)
        chunks: list[str] = []
        buffer = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) > self._max_chunk_chars:
                if buffer:
                    chunks.append(buffer)
                    buffer = ""
                chunks.extend(self._hard_wrap(sentence))
                continue
            candidate = f"{buffer} {sentence}".strip() if buffer else sentence
            if len(candidate) > self._max_chunk_chars:
                chunks.append(buffer)
                buffer = sentence
            else:
                buffer = candidate
        if buffer:
            chunks.append(buffer)
        return chunks

    def _hard_wrap(self, sentence: str) -> Iterable[str]:
        words = sentence.split(" ")
        buffer = ""
        for word in words:
            candidate = f"{buffer} {word}".strip() if buffer else word
            if len(candidate) > self._max_chunk_chars and buffer:
                yield buffer
                buffer = word
            else:
                buffer = candidate
        if buffer:
            yield buffer

    # ---- merging -------------------------------------------------------

    @staticmethod
    def _merge(chunks: list[bytes]) -> bytes:
        """Merge per-chunk audio buffers into one asset.

        For v1 we concatenate raw MP3 frames. This is acceptable for the
        ElevenLabs/silent providers used today and avoids pulling in heavy
        audio-processing dependencies. A future provider that needs proper
        muxing should expose its own merge strategy.
        """
        if not chunks:
            return b""
        if len(chunks) == 1:
            return chunks[0]
        return b"".join(chunks)
