"""Publish orchestration helpers for the publishing stage."""

from __future__ import annotations

from typing import Callable

from app.core.config import Settings
from app.publishing.models import (
    PublishContext,
    PublishMetadata,
    PublishRequest,
    PublishResult,
)
from app.services.storage import Storage, get_storage
from app.services.youtube import resolve_upload_eligibility, upload_video

Uploader = Callable[..., PublishResult]


def publish_video(
    *,
    context: PublishContext,
    metadata: PublishMetadata,
    storage: Storage | None,
    settings: Settings,
    uploader: Uploader | None = None,
) -> PublishResult:
    eligibility = resolve_upload_eligibility(settings)
    if not eligibility.enabled:
        return PublishResult(
            youtube_id=context.dry_run_youtube_id,
            mode="dry_run",
            requested_privacy_status=metadata.privacy_status,
            effective_privacy_status=metadata.privacy_status,
            dry_run_reason=eligibility.reason,
        )

    effective_uploader = uploader or upload_video
    resolved_storage = storage or get_storage()
    with resolved_storage.stage_local(context.final_path) as staged_asset:
        return effective_uploader(
            PublishRequest(
                job_id=context.job_id,
                video_path=staged_asset.local_path,
                metadata=metadata,
            ),
            settings=settings,
        )
