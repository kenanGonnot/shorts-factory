"""Typed internal structures for the video assembly stage.

``AssemblyClip`` captures ordering and timing for a single visual asset;
``AssemblyPlan`` groups the full ordered clip list together with the audio
input and output storage key.  Both are immutable dataclasses -- the
assembler consumes them but never mutates them.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AssemblyClip:
    """A single clip entry in the assembly timeline."""

    path: str
    section: str
    chunk_index: int
    start_ms: int
    end_ms: int
    duration_ms: int

    @property
    def duration_s(self) -> float:
        return self.duration_ms / 1000


@dataclass(frozen=True, slots=True)
class AssemblyPlan:
    """Complete assembly plan consumed by the rendering helpers."""

    clips: list[AssemblyClip] = field(default_factory=list)
    audio_path: str = ""
    output_key: str = ""
    audio_duration_ms: int | None = None

    @property
    def total_visual_duration_ms(self) -> int:
        return sum(c.duration_ms for c in self.clips)
