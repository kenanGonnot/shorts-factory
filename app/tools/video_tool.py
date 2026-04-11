"""ffmpeg-based assembly: concat normalized visual clips + mux audio.

The visual stage (``VisualTool``) guarantees that every entry in
``state["visual_assets"]`` is a uniform 1080x1920 ``.mp4`` — so this
stage only needs to concat them in order and mux the voice track.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

from app.chains.state import PipelineState
from app.services.storage import get_storage
from app.tools.base import PipelineTool


class VideoAssemblyTool(PipelineTool):
    name = "VideoAssemblyTool"

    def run(self, state: PipelineState) -> PipelineState:
        storage = get_storage()
        assets = state["visual_assets"]
        if not assets:
            raise ValueError("VideoAssemblyTool: visual_assets is empty")
        clip_paths = [a["path"] for a in assets]
        audio = state["audio_path"]

        # 1. concat list (all inputs are already normalized to the same
        # codec / scale / fps, so concat demuxer with -c copy works).
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as lst:
            for c in clip_paths:
                lst.write(f"file '{os.path.abspath(c)}'\n")
            list_path = lst.name

        concat_path = tempfile.mktemp(suffix=".mp4")
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", list_path,
                "-c", "copy",
                concat_path,
            ],
            check=True,
            capture_output=True,
        )

        out_path = tempfile.mktemp(suffix=".mp4")
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", concat_path,
                "-i", audio,
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                out_path,
            ],
            check=True,
            capture_output=True,
        )

        key = f"{state['job_id']}/video.mp4"
        final = storage.save(key, open(out_path, "rb").read())
        return {**state, "video_path": final}
