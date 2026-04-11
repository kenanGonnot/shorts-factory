"""Subtitle generation pipeline stage.

``SubtitleTool`` is a thin orchestrator that stitches together the
helpers inside :mod:`app.subtitles`:

1. validate pipeline state and resolve deterministic storage keys
2. build subtitle cues from voice metadata (or deterministic fallback)
3. serialize cues to ``.srt`` and persist through storage
4. stage ``video_path`` locally, burn subtitles, persist the final MP4

The public contract -- one ``PipelineTool`` node, no state mutation,
returns ``{**state, "subtitle_path": ..., "final_path": ...}`` -- stays
intact while the implementation moves into a testable package.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from app.chains.state import PipelineState
from app.core.logging import log
from app.services.storage import Storage, get_storage
from app.subtitles.burn import burn_subtitles
from app.subtitles.cues import build_cues
from app.subtitles.srt import serialize_srt
from app.subtitles.validate import SubtitlePlanContext, validate_state
from app.tools.base import PipelineTool


class SubtitleTool(PipelineTool):
    name = "SubtitleTool"

    def __init__(self, storage: Storage | None = None) -> None:
        # Lazy storage resolution so tests can construct the tool with
        # no side effects.
        self._storage = storage

    def run(self, state: PipelineState) -> PipelineState:
        storage = self._storage or get_storage()

        # 1. Validate inputs + resolve deterministic keys.
        log.info("subtitle.validate.start", job_id=state.get("job_id"))
        ctx: SubtitlePlanContext = validate_state(state)
        log.info("subtitle.validate.end", job_id=ctx.job_id)

        # 2. Plan cues from voice metadata (with deterministic fallback).
        cues = build_cues(ctx)
        log.info("subtitle.plan.ready", job_id=ctx.job_id, cue_count=len(cues))

        # 3. Serialize to ``.srt`` and persist.
        srt_text = serialize_srt(cues)
        subtitle_path = storage.save(ctx.subtitle_key, srt_text.encode("utf-8"))
        log.info(
            "subtitle.persist.srt",
            job_id=ctx.job_id,
            subtitle_path=subtitle_path,
        )

        # 4. Stage video + subtitles locally, burn, persist final MP4.
        final_path = self._render_and_persist(
            storage=storage,
            ctx=ctx,
            subtitle_local_key=ctx.subtitle_key,
            subtitle_persisted=subtitle_path,
        )
        log.info(
            "subtitle.persist.final",
            job_id=ctx.job_id,
            final_path=final_path,
        )

        return {
            **state,
            "subtitle_path": subtitle_path,
            "final_path": final_path,
        }

    # ------------------------------------------------------------------

    def _render_and_persist(
        self,
        storage: Storage,
        ctx: SubtitlePlanContext,
        subtitle_local_key: str,
        subtitle_persisted: str,
    ) -> str:
        """Stage inputs, run burn-in, persist the final MP4."""
        with (
            storage.stage_local(ctx.video_path) as video_asset,
            storage.stage_local(subtitle_persisted) as subtitle_asset,
            tempfile.TemporaryDirectory(prefix="shorts_subtitle_out_") as tmp,
        ):
            output_path = Path(tmp) / "final.mp4"
            burn_subtitles(
                video_path=video_asset.local_path,
                subtitle_path=subtitle_asset.local_path,
                output_path=str(output_path),
            )
            final_path = storage.save(ctx.final_key, output_path.read_bytes())
        return final_path
