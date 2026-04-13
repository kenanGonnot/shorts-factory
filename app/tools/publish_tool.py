"""Publishing pipeline stage."""

from __future__ import annotations

from app.chains.state import PipelineState
from app.core.config import Settings, get_settings
from app.core.logging import log
from app.publishing.metadata import build_publish_metadata
from app.publishing.service import publish_video
from app.publishing.validate import validate_state
from app.services.storage import Storage
from app.tools.base import PipelineTool


class PublishingTool(PipelineTool):
    name = "PublishingTool"

    def __init__(
        self,
        storage: Storage | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._storage = storage
        self._settings = settings

    def run(self, state: PipelineState) -> PipelineState:
        settings = self._settings or get_settings()

        log.info("publish.validate.start", job_id=state.get("job_id"))
        context = validate_state(state)
        log.info("publish.validate.end", job_id=context.job_id)

        metadata = build_publish_metadata(
            context.script,
            privacy_status=settings.youtube_privacy,
        )
        log.info(
            "publish.metadata.ready",
            job_id=context.job_id,
            title=metadata.title,
            tag_count=len(metadata.tags),
            privacy_status=metadata.privacy_status,
        )

        result = publish_video(
            context=context,
            metadata=metadata,
            storage=self._storage,
            settings=settings,
        )
        if result.effective_privacy_status != result.requested_privacy_status:
            log.warning(
                "publish.privacy.adjusted",
                job_id=context.job_id,
                requested_privacy_status=result.requested_privacy_status,
                effective_privacy_status=result.effective_privacy_status,
            )

        log.info(
            "publish.completed",
            job_id=context.job_id,
            youtube_id=result.youtube_id,
            mode=result.mode,
            dry_run_reason=result.dry_run_reason,
        )
        return {**state, "youtube_id": result.youtube_id}
