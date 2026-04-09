"""Fetch background visuals from Pexels (free stock). Falls back to a colored frame."""
from __future__ import annotations
import httpx

from app.core.config import get_settings
from app.services.storage import get_storage
from app.chains.state import PipelineState
from app.tools.base import PipelineTool


class VisualTool(PipelineTool):
    name = "VisualTool"

    def run(self, state: PipelineState) -> PipelineState:
        s = get_settings()
        storage = get_storage()
        query = state["script"]["title"]
        paths: list[str] = []

        if s.pexels_api_key:
            r = httpx.get(
                "https://api.pexels.com/videos/search",
                params={"query": query, "orientation": "portrait", "per_page": 3},
                headers={"Authorization": s.pexels_api_key},
                timeout=60,
            )
            r.raise_for_status()
            for i, v in enumerate(r.json().get("videos", [])):
                file_url = v["video_files"][0]["link"]
                data = httpx.get(file_url, timeout=120).content
                paths.append(storage.save(f"{state['job_id']}/clip_{i}.mp4", data))

        if not paths:
            paths.append(_solid_clip(state["job_id"], storage))

        return {**state, "image_paths": paths}


def _solid_clip(job_id: str, storage) -> str:
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", "color=c=0x101820:s=1080x1920:d=10",
             "-pix_fmt", "yuv420p", f.name],
            check=True, capture_output=True,
        )
        return storage.save(f"{job_id}/clip_0.mp4", open(f.name, "rb").read())
