"""ffmpeg-based assembly: concat clips, scale to 1080x1920, mux audio."""
from __future__ import annotations
import subprocess
import tempfile
import os

from app.services.storage import get_storage
from app.chains.state import PipelineState
from app.tools.base import PipelineTool


class VideoAssemblyTool(PipelineTool):
    name = "VideoAssemblyTool"

    def run(self, state: PipelineState) -> PipelineState:
        storage = get_storage()
        clips = state["image_paths"]
        audio = state["audio_path"]

        # 1. concat list
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as lst:
            for c in clips:
                lst.write(f"file '{os.path.abspath(c)}'\n")
            list_path = lst.name

        concat_path = tempfile.mktemp(suffix=".mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
             "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,"
                    "crop=1080:1920,setsar=1",
             "-r", "30", "-pix_fmt", "yuv420p", "-an", concat_path],
            check=True, capture_output=True,
        )

        out_path = tempfile.mktemp(suffix=".mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-i", concat_path, "-i", audio,
             "-c:v", "copy", "-c:a", "aac", "-shortest", out_path],
            check=True, capture_output=True,
        )

        key = f"{state['job_id']}/video.mp4"
        final = storage.save(key, open(out_path, "rb").read())
        return {**state, "video_path": final}
