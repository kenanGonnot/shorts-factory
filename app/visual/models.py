"""Typed structures for the visual generation domain."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VisualSection = Literal["hook", "body", "cta"]
AssetType = Literal["clip", "image"]


@dataclass(frozen=True, slots=True)
class VisualRequest:
    """A planned visual slot derived from script + audio timing.

    One request maps 1:1 to a final visual asset in the manifest.
    """

    section: VisualSection
    chunk_index: int
    start_ms: int
    end_ms: int
    prompt: str
    query: str

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


@dataclass(frozen=True, slots=True)
class VisualAsset:
    """A resolved, normalized visual asset ready for video assembly.

    After normalization, every ``VisualAsset.path`` points to a uniform
    1080x1920 ``.mp4`` clip of exactly ``duration_ms`` length. Metadata
    fields keep traceability to the originating provider and section.
    """

    section: VisualSection
    chunk_index: int
    asset_type: AssetType
    provider: str
    path: str
    start_ms: int
    end_ms: int
    duration_ms: int
    width: int = 1080
    height: int = 1920
    prompt: str | None = None
    source_url: str | None = None

    def as_dict(self) -> dict:
        return {
            "section": self.section,
            "chunk_index": self.chunk_index,
            "asset_type": self.asset_type,
            "provider": self.provider,
            "path": self.path,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "duration_ms": self.duration_ms,
            "width": self.width,
            "height": self.height,
            "prompt": self.prompt,
            "source_url": self.source_url,
        }


@dataclass(frozen=True, slots=True)
class ResolvedAsset:
    """Intermediate provider output before normalization.

    Providers return either raw bytes (still image or clip) together with
    a MIME type; the normalizer decides how to persist and conform the
    asset to the assembly-ready contract.
    """

    asset_type: AssetType
    data: bytes
    mime_type: str
    provider: str
    source_url: str | None = None
