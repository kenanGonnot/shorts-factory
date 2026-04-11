"""Video assembly helpers: validation, concat-list writing, ffmpeg rendering.

All ffmpeg invocations use ``subprocess.run(check=True, capture_output=True)``
and never ``shell=True``, per ``AGENTS.md`` rules.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from app.chains.state import PipelineState
from app.core.logging import log
from app.video.plan import AssemblyClip, AssemblyPlan

# ---------------------------------------------------------------------------
# Duration-drift tolerance (ms).  When visual vs. audio drift exceeds this
# threshold, the last clip is adjusted and a warning is logged.
# ---------------------------------------------------------------------------
DRIFT_TOLERANCE_MS: int = 500


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class AssemblyValidationError(ValueError):
    """Raised when assembly inputs are invalid."""


def validate_state(state: PipelineState) -> None:
    """Reject unusable inputs *before* any ffmpeg work."""
    assets = state.get("visual_assets")
    if not assets:
        raise AssemblyValidationError(
            "visual_assets is empty or missing"
        )
    audio = state.get("audio_path")
    if not audio:
        raise AssemblyValidationError("audio_path is missing")
    if not os.path.isfile(audio):
        raise AssemblyValidationError(
            f"audio_path does not exist: {audio}"
        )
    for i, a in enumerate(assets):
        for key in ("path", "section", "chunk_index", "start_ms", "end_ms", "duration_ms"):
            if key not in a:
                raise AssemblyValidationError(
                    f"visual_assets[{i}] missing required key '{key}'"
                )
        p = a["path"]
        if not os.path.isfile(p):
            raise AssemblyValidationError(
                f"visual_assets[{i}].path does not exist: {p}"
            )


# ---------------------------------------------------------------------------
# Plan building
# ---------------------------------------------------------------------------

def build_plan(state: PipelineState) -> AssemblyPlan:
    """Build an ``AssemblyPlan`` from validated ``PipelineState``."""
    assets = state["visual_assets"]
    clips = sorted(
        (
            AssemblyClip(
                path=a["path"],
                section=a["section"],
                chunk_index=a["chunk_index"],
                start_ms=a["start_ms"],
                end_ms=a["end_ms"],
                duration_ms=a["duration_ms"],
            )
            for a in assets
        ),
        key=lambda c: (c.start_ms, c.chunk_index),
    )
    return AssemblyPlan(
        clips=clips,
        audio_path=state["audio_path"],
        output_key=f"{state['job_id']}/video.mp4",
        audio_duration_ms=state.get("audio_duration_ms"),
    )


# ---------------------------------------------------------------------------
# Duration probing helper
# ---------------------------------------------------------------------------

def probe_duration_ms(path: str) -> int | None:
    """Return media duration in ms using ffprobe, or ``None`` on failure."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return int(float(result.stdout.strip()) * 1000)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Concat-list writer
# ---------------------------------------------------------------------------

def write_concat_list(clips: list[AssemblyClip], dest: Path) -> None:
    """Write an ffconcat-format list file to *dest*."""
    lines = ["ffconcat version 1.0"]
    for clip in clips:
        escaped = os.path.abspath(clip.path).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
        lines.append(f"duration {clip.duration_s:.3f}")
    dest.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Visual concat
# ---------------------------------------------------------------------------

def concat_clips(clips: list[AssemblyClip], output: Path) -> None:
    """Concatenate normalized clips into a single video (no audio)."""
    with tempfile.TemporaryDirectory() as tmp:
        list_path = Path(tmp) / "concat.txt"
        write_concat_list(clips, list_path)
        log.info(
            "video.concat.start",
            clip_count=len(clips),
            list_path=str(list_path),
        )
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(list_path),
                "-c", "copy",
                "-an",
                str(output),
            ],
            check=True,
            capture_output=True,
        )
        log.info("video.concat.end", output=str(output))


# ---------------------------------------------------------------------------
# Audio mux
# ---------------------------------------------------------------------------

def mux_audio(video: Path, audio_path: str, output: Path) -> None:
    """Combine *video* with narration *audio_path* into *output*."""
    log.info("video.mux.start", video=str(video), audio=audio_path)
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(video),
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            str(output),
        ],
        check=True,
        capture_output=True,
    )
    log.info("video.mux.end", output=str(output))


# ---------------------------------------------------------------------------
# Duration drift check
# ---------------------------------------------------------------------------

def check_duration_drift(plan: AssemblyPlan) -> None:
    """Log a warning when visual and audio durations diverge."""
    if plan.audio_duration_ms is None:
        return
    visual_ms = plan.total_visual_duration_ms
    drift = abs(visual_ms - plan.audio_duration_ms)
    if drift > DRIFT_TOLERANCE_MS:
        log.warning(
            "video.duration_drift",
            visual_ms=visual_ms,
            audio_ms=plan.audio_duration_ms,
            drift_ms=drift,
            policy="audio_wins",
        )


# ---------------------------------------------------------------------------
# Full render orchestrator (used by VideoAssemblyTool)
# ---------------------------------------------------------------------------

def render(plan: AssemblyPlan) -> str:
    """Execute the full render pipeline and return the path to the final MP4.

    Steps:
    1. Check duration drift and log if needed.
    2. Concat all visual clips.
    3. Mux narration audio.
    4. Return the path to the muxed output file.
    """
    check_duration_drift(plan)

    tmpdir = tempfile.mkdtemp(prefix="shorts_video_")
    tmp = Path(tmpdir)
    concat_out = tmp / "concat.mp4"
    mux_out = tmp / "muxed.mp4"

    concat_clips(plan.clips, concat_out)
    mux_audio(concat_out, plan.audio_path, mux_out)

    return str(mux_out)

