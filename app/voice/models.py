"""Typed structures used by the voice generation domain."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ScriptSection = Literal["hook", "body", "cta"]


@dataclass(frozen=True, slots=True)
class VoiceConfig:
    """Provider-agnostic voice configuration."""

    provider: str
    voice_id: str
    model_id: str | None = None


@dataclass(frozen=True, slots=True)
class RenderedAudio:
    """Raw audio bytes returned by a provider for a single chunk."""

    audio: bytes
    mime_type: str = "audio/mpeg"
    duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class AudioSegment:
    """Metadata describing one rendered chunk of the script.

    Segments stay traceable to their original ``hook`` / ``body`` / ``cta``
    section even after chunking.
    """

    section: ScriptSection
    chunk_index: int
    text: str
    duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class VoiceRenderResult:
    """Final renderer output: merged audio bytes and segment metadata."""

    audio: bytes
    mime_type: str
    segments: list[AudioSegment]
    voice_provider: str
    voice_id: str
    duration_ms: int | None = None

    def segments_as_dicts(self) -> list[dict]:
        return [
            {
                "section": s.section,
                "chunk_index": s.chunk_index,
                "text": s.text,
                "duration_ms": s.duration_ms,
            }
            for s in self.segments
        ]


@dataclass(slots=True)
class _MutableSegmentBuilder:
    """Internal helper used by the renderer while assembling chunks."""

    segments: list[AudioSegment] = field(default_factory=list)

    def add(self, section: ScriptSection, text: str, duration_ms: int | None = None) -> None:
        chunk_index = sum(1 for s in self.segments if s.section == section)
        self.segments.append(
            AudioSegment(
                section=section,
                chunk_index=chunk_index,
                text=text,
                duration_ms=duration_ms,
            )
        )
