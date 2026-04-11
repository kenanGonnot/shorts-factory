"""ffmpeg-based assembly: concat normalized visual clips + mux audio.

The visual stage (``VisualTool``) guarantees that every entry in
``state["visual_assets"]`` is a uniform 1080x1920 ``.mp4`` -- so this
stage only needs to concat them in order and mux the voice track.

Internal logic lives in ``app.video.assembler`` and ``app.video.plan``.
``VideoAssemblyTool`` is the single public pipeline node.
"""
from __future__ import annotations

from app.chains.state import PipelineState
from app.core.logging import log
from app.services.storage import get_storage
from app.tools.base import PipelineTool
from app.video.assembler import (
    build_plan,
    render,
    validate_state,
)


class VideoAssemblyTool(PipelineTool):
    name = "VideoAssemblyTool"

    def run(self, state: PipelineState) -> PipelineState:
        job_id = state.get("job_id", "unknown")

        # 1. Validate inputs
        log.info("video.validate.start", job_id=job_id)
        validate_state(state)
        log.info("video.validate.end", job_id=job_id)

        # 2. Build deterministic assembly plan
        plan = build_plan(state)
        log.info(
            "video.plan.ready",
            job_id=job_id,
            clip_count=len(plan.clips),
            visual_duration_ms=plan.total_visual_duration_ms,
            audio_duration_ms=plan.audio_duration_ms,
        )

        # 3. Render (concat + mux)
        rendered_path = render(plan)

        # 4. Persist through storage
        storage = get_storage()
        with open(rendered_path, "rb") as f:
            final = storage.save(plan.output_key, f.read())
        log.info("video.persist", job_id=job_id, video_path=final)

        return {**state, "video_path": final}
