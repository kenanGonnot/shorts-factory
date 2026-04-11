"""ffmpeg subtitle burn-in.

The burn-in helper wraps one ``ffmpeg`` invocation using the ``subtitles``
filter. It is intentionally narrow: it owns the command shape, the
mobile-first ``force_style`` string, and the local-filesystem staging
required so ``ffmpeg`` can read inputs regardless of the storage
backend.

Audio is always stream-copied (``-c:a copy``). Subtitle burn-in does not
touch the audio track, which preserves the exact ``VoiceTool`` output on
the final MP4.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core.logging import log

# ---------------------------------------------------------------------------
# Default style. Centralized in one place per the plan's v1 decision:
# hardcode one mobile-first default and expose config later.
# ---------------------------------------------------------------------------

#: libass ``force_style`` string applied to every burned-in subtitle.
#:
#: - ``Fontsize=18`` is a libass ``Style`` unit, not pixels; at 1080x1920
#:   it renders at a readable short-form size.
#: - ``BorderStyle=3`` + ``Outline=1`` draws a boxed background so
#:   subtitles stay legible over bright footage.
#: - ``Alignment=2`` pins the card to bottom-center.
#: - ``MarginV=220`` lifts the card above TikTok/YouTube Shorts UI safe
#:   zones.
FORCE_STYLE: str = (
    "Fontname=DejaVu Sans,"
    "Fontsize=18,"
    "PrimaryColour=&H00FFFFFF&,"
    "OutlineColour=&H00000000&,"
    "BackColour=&H80000000&,"
    "BorderStyle=3,"
    "Outline=1,"
    "Shadow=0,"
    "Alignment=2,"
    "MarginV=220"
)


def burn_subtitles(video_path: str, subtitle_path: str, output_path: str) -> str:
    """Burn ``subtitle_path`` onto ``video_path`` and write ``output_path``.

    All inputs are staged into one :class:`tempfile.TemporaryDirectory`
    before the ``ffmpeg`` call so the filter graph can reference short,
    escape-safe filenames. This also keeps the helper compatible with
    non-local storage backends that materialize assets through
    :meth:`app.services.storage.Storage.stage_local`.

    Returns ``output_path`` on success. Raises
    :class:`subprocess.CalledProcessError` on failure with the ffmpeg
    stderr captured.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="shorts_subs_") as tmp:
        staged_video = Path(tmp) / "video.mp4"
        staged_subs = Path(tmp) / "subs.srt"
        shutil.copyfile(video_path, staged_video)
        shutil.copyfile(subtitle_path, staged_subs)

        vf = _build_subtitles_filter(staged_subs)
        log.info(
            "subtitle.burn.start",
            video=str(staged_video),
            subtitles=str(staged_subs),
            output=str(output),
        )
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(staged_video),
                "-vf", vf,
                "-c:a", "copy",
                str(output),
            ],
            check=True,
            capture_output=True,
        )
        log.info("subtitle.burn.end", output=str(output))
    return str(output)


def _build_subtitles_filter(subtitle_path: Path) -> str:
    """Return the ffmpeg ``-vf`` argument for the ``subtitles`` filter.

    libass parses this string, so single quotes and colons inside the
    subtitle path or the ``force_style`` value must be escaped. The
    staging directory keeps paths simple, but we still escape to stay
    defensive on macOS ``/private/var/...`` style paths.
    """
    escaped_path = _escape_filter_arg(os.fspath(subtitle_path))
    return f"subtitles={escaped_path}:force_style='{FORCE_STYLE}'"


def _escape_filter_arg(value: str) -> str:
    """Escape a value for use inside an ffmpeg filter argument.

    ffmpeg treats ``:``, ``\\`` and ``'`` as special inside filter
    expressions.
    """
    return (
        value.replace("\\", "\\\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
    )
