"""Publishes the final video to YouTube Shorts."""
from __future__ import annotations

from app.services.youtube import upload_short
from app.chains.state import PipelineState
from app.tools.base import PipelineTool


class PublishingTool(PipelineTool):
    name = "PublishingTool"

    def run(self, state: PipelineState) -> PipelineState:
        script = state["script"]
        description = (
            f"{script['hook']}\n\n{script['body']}\n\n{script['cta']}\n\n#shorts"
        )
        yt_id = upload_short(
            video_path=state["final_path"],
            title=script["title"] + " #shorts",
            description=description,
            tags=script.get("tags", []),
        )
        return {**state, "youtube_id": yt_id}
