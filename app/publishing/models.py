"""Typed publishing structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.chains.state import Script


PublishMode = Literal["dry_run", "uploaded"]


@dataclass(frozen=True, slots=True)
class PublishMetadata:
    """Validated metadata ready to be sent to YouTube."""

    title: str
    description: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    privacy_status: str = "private"
    category_id: str = "22"

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", tuple(self.tags))


@dataclass(frozen=True, slots=True)
class PublishContext:
    """Validated publish inputs resolved from ``PipelineState``."""

    job_id: str
    final_path: str
    script: Script

    @property
    def dry_run_youtube_id(self) -> str:
        return f"dryrun-{self.job_id}"


@dataclass(frozen=True, slots=True)
class PublishRequest:
    """Concrete local upload request consumed by the YouTube wrapper."""

    job_id: str
    video_path: str
    metadata: PublishMetadata


@dataclass(frozen=True, slots=True)
class PublishResult:
    """Normalized outcome of the publishing stage."""

    youtube_id: str
    mode: PublishMode
    requested_privacy_status: str
    effective_privacy_status: str
    dry_run_reason: str | None = None

    @property
    def is_dry_run(self) -> bool:
        return self.mode == "dry_run"
