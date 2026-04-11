#!/usr/bin/env python
"""Video Assembly demo -- generates stub media on the fly and invokes VideoAssemblyTool.

Run from the project root:

    python examples/video_assembly_demo.py

Requirements:
    - ffmpeg available on PATH
    - No API keys needed (fully offline)

The script:
    1. Generates three short color clips (hook=red, body=blue, cta=green)
    2. Generates a silent MP3 narration track
    3. Builds a minimal PipelineState
    4. Invokes VideoAssemblyTool
    5. Prints the path to the assembled video
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Ensure the project root is on sys.path so ``app`` can be imported when
# running the script directly (``python examples/video_assembly_demo.py``).
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

os.environ.setdefault("STORAGE_BACKEND", "local")


# ------------------------------------------------------------------
# Stub media generators
# ------------------------------------------------------------------

def generate_color_clip(path: Path, duration_s: float, color: str) -> str:
    """Render a solid-color 1080x1920 clip."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c={color}:s=1080x1920:r=30:d={duration_s:.3f}",
            "-pix_fmt", "yuv420p",
            "-an",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return str(path)


def generate_silent_audio(path: Path, duration_s: float) -> str:
    """Render a silent MP3 track."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=mono",
            "-t", f"{duration_s:.3f}",
            "-c:a", "libmp3lame",
            "-q:a", "9",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return str(path)


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    from app.tools.video_tool import VideoAssemblyTool

    out_dir = Path("examples/output/video_assembly_demo")
    out_dir.mkdir(parents=True, exist_ok=True)

    os.environ["STORAGE_LOCAL_DIR"] = str(out_dir / "storage")

    # Clear cached settings so our env overrides take effect.
    from app.core.config import get_settings
    get_settings.cache_clear()

    # 1. Generate stub clips
    hook_path = generate_color_clip(out_dir / "hook.mp4", 1.5, "red")
    body_path = generate_color_clip(out_dir / "body.mp4", 3.0, "blue")
    cta_path = generate_color_clip(out_dir / "cta.mp4", 1.5, "green")

    # 2. Generate silent audio matching total visual duration
    total_s = 1.5 + 3.0 + 1.5
    audio_path = generate_silent_audio(out_dir / "narration.mp3", total_s)

    # 3. Build minimal PipelineState
    def _asset(path: str, section: str, idx: int, start: int, end: int) -> dict:
        return {
            "path": path,
            "section": section,
            "chunk_index": idx,
            "start_ms": start,
            "end_ms": end,
            "duration_ms": end - start,
            "asset_type": "clip",
            "provider": "demo",
            "width": 1080,
            "height": 1920,
            "prompt": None,
            "source_url": None,
        }

    state = {
        "job_id": "demo_video_assembly",
        "audio_path": audio_path,
        "audio_duration_ms": int(total_s * 1000),
        "visual_assets": [
            _asset(hook_path, "hook", 0, 0, 1500),
            _asset(body_path, "body", 0, 1500, 4500),
            _asset(cta_path, "cta", 0, 4500, 6000),
        ],
    }

    # 4. Invoke the tool
    result = VideoAssemblyTool().invoke(state)

    # 5. Report
    video = result["video_path"]
    size_kb = Path(video).stat().st_size / 1024
    print("\n✅  Video assembled successfully!")
    print(f"    Path : {video}")
    print(f"    Size : {size_kb:.1f} KB")
    print(f"    Job  : {result['job_id']}")

    get_settings.cache_clear()


if __name__ == "__main__":
    main()

