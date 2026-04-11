"""Normalize resolved assets into assembly-ready vertical MP4 clips.

All resolved assets — whether stock clips, AI-generated stills, or
fallback markers — pass through :class:`VisualNormalizer` so
``VideoAssemblyTool`` only ever sees uniform 1080x1920 ``.mp4`` files.

Design notes:

- Still images are rendered into timed clips with a static frame via
  ``ffmpeg -loop 1``. Pan/zoom (Ken Burns) is intentionally deferred.
- Video clips are re-encoded to the target scale/crop/fps so the final
  concat works without re-normalization in ``VideoAssemblyTool``.
- Every invocation uses ``check=True``, ``capture_output=True``, and
  never ``shell=True`` per ``AGENTS.md``.
- Output files are persisted via :class:`Storage` using deterministic
  keys derived from ``job_id``, section, and chunk index so re-runs are
  idempotent.
"""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.services.storage import Storage
from app.visual.models import ResolvedAsset, VisualAsset, VisualRequest

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
TARGET_FPS = 30
_SCALE_VF = (
    f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
    f"crop={TARGET_WIDTH}:{TARGET_HEIGHT},setsar=1"
)


@dataclass(slots=True)
class VisualNormalizer:
    """Converts resolved assets into storage-backed normalized clips."""

    storage: Storage
    job_id: str

    def normalize(self, request: VisualRequest, resolved: ResolvedAsset) -> VisualAsset:
        duration_ms = max(request.duration_ms, 1)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            suffix = ".png" if resolved.asset_type == "image" else ".mp4"
            src = tmp_path / f"src{suffix}"
            src.write_bytes(resolved.data)
            out = tmp_path / "out.mp4"

            if resolved.asset_type == "image":
                _render_image_to_clip(src, out, duration_ms)
            else:
                _reencode_clip(src, out, duration_ms)

            key = self._key(request)
            persisted = self.storage.save(key, out.read_bytes())

        return VisualAsset(
            section=request.section,
            chunk_index=request.chunk_index,
            asset_type=resolved.asset_type,
            provider=resolved.provider,
            path=persisted,
            start_ms=request.start_ms,
            end_ms=request.end_ms,
            duration_ms=duration_ms,
            width=TARGET_WIDTH,
            height=TARGET_HEIGHT,
            prompt=request.prompt,
            source_url=resolved.source_url,
        )

    def _key(self, request: VisualRequest) -> str:
        return (
            f"{self.job_id}/visuals/"
            f"{request.section}_{request.chunk_index:02d}.mp4"
        )


def _render_image_to_clip(src: Path, out: Path, duration_ms: int) -> None:
    duration_s = duration_ms / 1000
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(src),
            "-t", f"{duration_s:.3f}",
            "-vf", _SCALE_VF,
            "-r", str(TARGET_FPS),
            "-pix_fmt", "yuv420p",
            "-an",
            str(out),
        ],
        check=True,
        capture_output=True,
    )


def _reencode_clip(src: Path, out: Path, duration_ms: int) -> None:
    duration_s = duration_ms / 1000
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(src),
            "-t", f"{duration_s:.3f}",
            "-vf", _SCALE_VF,
            "-r", str(TARGET_FPS),
            "-pix_fmt", "yuv420p",
            "-an",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
