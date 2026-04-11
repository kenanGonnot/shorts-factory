#!/usr/bin/env python
"""Subtitle tool demo -- generates stub media on the fly and burns subtitles.

Run from the project root::

    python examples/subtitle_tool_example.py

Requirements:
    - ffmpeg available on PATH
    - No API keys needed (fully offline)

The script:
    1. Generates an assembled-looking demo video (solid colors + silent audio)
    2. Builds a minimal PipelineState with deterministic ``audio_segments``
    3. Invokes ``SubtitleTool``
    4. Prints the persisted ``subtitle_path`` + ``final_path``
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Ensure the project root is on sys.path so ``app`` can be imported when
# running the script directly.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

os.environ.setdefault("STORAGE_BACKEND", "local")


# ---------------------------------------------------------------------------
# Stub media generator
# ---------------------------------------------------------------------------


def _generate_demo_video(path: Path, duration_s: float) -> str:
    """Render a short 1080x1920 clip with a silent stereo AAC track."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=navy:s=1080x1920:r=30:d={duration_s:.3f}",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-t", f"{duration_s:.3f}",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return str(path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    out_dir = Path("examples/output/subtitle_tool_demo")
    out_dir.mkdir(parents=True, exist_ok=True)
    os.environ["STORAGE_LOCAL_DIR"] = str(out_dir / "storage")

    # Clear cached settings so our env overrides take effect.
    from app.core.config import get_settings
    get_settings.cache_clear()

    from app.services.storage import LocalStorage
    from app.tools.subtitle_tool import SubtitleTool

    # 1. Generate stub assembled video (matches the output of VideoAssemblyTool).
    total_duration_s = 6.0
    video_path = _generate_demo_video(out_dir / "assembled.mp4", total_duration_s)

    # 2. Build minimal PipelineState with deterministic audio_segments.
    state = {
        "job_id": "demo_subtitles",
        "video_path": video_path,
        "script": {
            "title": "Why typing matters",
            "hook": "Types catch bugs you would never see in tests.",
            "body": (
                "Static types document intent. They help refactors. "
                "They also make IDEs much smarter about your code."
            ),
            "cta": "Follow for more Python tips.",
            "tags": ["python", "typing"],
        },
        "audio_duration_ms": int(total_duration_s * 1000),
        "audio_segments": [
            {
                "section": "hook",
                "chunk_index": 0,
                "text": "Types catch bugs you would never see in tests.",
                "duration_ms": 2000,
            },
            {
                "section": "body",
                "chunk_index": 0,
                "text": "Static types document intent. They help refactors. They also make IDEs much smarter about your code.",
                "duration_ms": 3000,
            },
            {
                "section": "cta",
                "chunk_index": 0,
                "text": "Follow for more Python tips.",
                "duration_ms": 1000,
            },
        ],
    }

    # 3. Invoke the tool (explicit LocalStorage keeps outputs next to the demo).
    storage = LocalStorage(str(out_dir / "storage"))
    tool = SubtitleTool(storage=storage)
    result = tool.run(state)

    # 4. Report
    subtitle_path = result["subtitle_path"]
    final_path = result["final_path"]
    srt_size = Path(subtitle_path).stat().st_size
    mp4_size_kb = Path(final_path).stat().st_size / 1024
    print("\nSubtitles burned successfully.")
    print(f"    subtitle_path : {subtitle_path} ({srt_size} B)")
    print(f"    final_path    : {final_path} ({mp4_size_kb:.1f} KB)")
    print(f"    job_id        : {result['job_id']}")

    get_settings.cache_clear()


if __name__ == "__main__":
    main()
