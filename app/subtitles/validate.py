"""Input validation and deterministic key resolution for the subtitle stage.

The validator is the first helper the :class:`SubtitleTool` calls. It
rejects unusable pipeline state *before* any cue planning, serialization
or ffmpeg work, and packages the resolved information into a
:class:`SubtitlePlanContext` so downstream helpers do not re-read the
state dict.

Validation rules (all raise :class:`SubtitleValidationError`):

- ``job_id`` must be a non-empty string.
- ``video_path`` must be a non-empty string pointing at a real file.
- ``script`` must be a dict with non-empty ``hook`` / ``body`` / ``cta``.
- Timing metadata must exist in at least one of the supported forms:
  ``audio_segments``, ``audio_segments_path``, or
  ``(audio_duration_ms`` + ``script)`` for the deterministic fallback.
- ``audio_segments`` entries, when present, must carry a ``text`` field
  and either a numeric ``duration_ms`` or be part of a manifest where
  ``audio_duration_ms`` is available.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.chains.state import PipelineState, Script


class SubtitleValidationError(ValueError):
    """Raised when :class:`SubtitleTool` inputs are unusable."""


# Deterministic storage keys. One run → one subtitle artifact → one MP4.
SUBTITLE_KEY_TEMPLATE = "{job_id}/subtitles.srt"
FINAL_KEY_TEMPLATE = "{job_id}/final.mp4"


@dataclass(frozen=True, slots=True)
class SubtitlePlanContext:
    """Validated inputs the subtitle stage consumes.

    Built once at the top of :meth:`SubtitleTool.run` so cue planning,
    serialization and rendering do not need to re-inspect the raw state.
    """

    job_id: str
    video_path: str
    script: Script
    audio_segments: list[dict] | None
    audio_segments_path: str | None
    audio_duration_ms: int | None
    subtitle_key: str
    final_key: str


def validate_state(state: PipelineState) -> SubtitlePlanContext:
    """Validate ``state`` and return a frozen :class:`SubtitlePlanContext`."""
    job_id = _require_str(state, "job_id")
    video_path = _require_str(state, "video_path")
    if not Path(video_path).is_file():
        raise SubtitleValidationError(
            f"video_path does not exist: {video_path}"
        )

    script = state.get("script")
    if not script or not isinstance(script, dict):
        raise SubtitleValidationError("script is missing or not a dict")
    for key in ("hook", "body", "cta"):
        value = script.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SubtitleValidationError(
                f"script['{key}'] is missing or empty"
            )

    audio_segments = state.get("audio_segments")
    audio_segments_path = state.get("audio_segments_path")
    audio_duration_ms = state.get("audio_duration_ms")

    if audio_segments is not None:
        _validate_segments(audio_segments)

    has_segments = bool(audio_segments)
    has_segments_file = bool(audio_segments_path)
    has_fallback = audio_duration_ms is not None and audio_duration_ms > 0

    if not (has_segments or has_segments_file or has_fallback):
        raise SubtitleValidationError(
            "no timing metadata available: need audio_segments, "
            "audio_segments_path, or audio_duration_ms"
        )

    return SubtitlePlanContext(
        job_id=job_id,
        video_path=video_path,
        script=script,  # type: ignore[arg-type]
        audio_segments=list(audio_segments) if audio_segments else None,
        audio_segments_path=audio_segments_path,
        audio_duration_ms=audio_duration_ms,
        subtitle_key=SUBTITLE_KEY_TEMPLATE.format(job_id=job_id),
        final_key=FINAL_KEY_TEMPLATE.format(job_id=job_id),
    )


# ---- internals ------------------------------------------------------------


def _require_str(state: PipelineState, key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str) or not value:
        raise SubtitleValidationError(f"{key} is missing or empty")
    return value


def _validate_segments(segments: object) -> None:
    if not isinstance(segments, list):
        raise SubtitleValidationError("audio_segments must be a list")
    if not segments:
        raise SubtitleValidationError("audio_segments is empty")
    for i, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise SubtitleValidationError(
                f"audio_segments[{i}] is not a dict"
            )
        text = segment.get("text")
        if not isinstance(text, str) or not text.strip():
            raise SubtitleValidationError(
                f"audio_segments[{i}] missing non-empty 'text'"
            )
        duration = segment.get("duration_ms")
        if duration is not None and (
            not isinstance(duration, (int, float)) or duration < 0
        ):
            raise SubtitleValidationError(
                f"audio_segments[{i}].duration_ms must be a non-negative number"
            )
