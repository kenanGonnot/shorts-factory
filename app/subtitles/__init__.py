"""Subtitle generation module.

The public pipeline node remains :class:`app.tools.subtitle_tool.SubtitleTool`.
Everything under ``app/subtitles`` is internal helper logic:

- :mod:`app.subtitles.cues` -- cue model + cue planning (timing priority).
- :mod:`app.subtitles.srt` -- ``.srt`` serialization.
- :mod:`app.subtitles.burn` -- ffmpeg ``subtitles=`` burn-in rendering.
- :mod:`app.subtitles.validate` -- input validation and deterministic keys.
"""
from app.subtitles.cues import (
    SubtitleCue,
    build_cues,
    plan_cues_from_segments,
    plan_cues_from_script_fallback,
)
from app.subtitles.srt import serialize_srt, format_timestamp
from app.subtitles.burn import burn_subtitles, FORCE_STYLE
from app.subtitles.validate import (
    SubtitleValidationError,
    SubtitlePlanContext,
    validate_state,
)

__all__ = [
    "SubtitleCue",
    "build_cues",
    "plan_cues_from_segments",
    "plan_cues_from_script_fallback",
    "serialize_srt",
    "format_timestamp",
    "burn_subtitles",
    "FORCE_STYLE",
    "SubtitleValidationError",
    "SubtitlePlanContext",
    "validate_state",
]
