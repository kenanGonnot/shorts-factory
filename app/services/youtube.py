"""Focused YouTube upload wrapper."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.publishing.models import PublishMetadata, PublishRequest, PublishResult

YOUTUBE_UPLOAD_SCOPES = ("https://www.googleapis.com/auth/youtube.upload",)
RETRYABLE_STATUS_CODES = frozenset({500, 502, 503, 504})
MAX_RESUMABLE_RETRIES = 3


class YouTubeUploadError(RuntimeError):
    """Raised when the runtime upload path cannot continue."""


@dataclass(frozen=True, slots=True)
class YouTubeUploadEligibility:
    enabled: bool
    reason: str | None = None


def resolve_upload_eligibility(settings: Settings) -> YouTubeUploadEligibility:
    if not settings.youtube_client_secrets_file:
        return YouTubeUploadEligibility(
            enabled=False,
            reason="no client secrets configured",
        )

    client_secrets = Path(settings.youtube_client_secrets_file)
    if not client_secrets.is_file():
        return YouTubeUploadEligibility(
            enabled=False,
            reason=f"client secrets file not found: {client_secrets}",
        )

    if not settings.youtube_token_file:
        return YouTubeUploadEligibility(
            enabled=False,
            reason="no token file configured",
        )

    token_file = Path(settings.youtube_token_file)
    if not token_file.is_file():
        return YouTubeUploadEligibility(
            enabled=False,
            reason=f"token file not found: {token_file}",
        )

    return YouTubeUploadEligibility(enabled=True)


def upload_video(
    request: PublishRequest,
    *,
    settings: Settings | None = None,
) -> PublishResult:
    resolved_settings = settings or get_settings()
    _require_upload_ready(resolved_settings)

    Credentials, build, MediaFileUpload, http_error_cls = _load_google_dependencies()

    credentials = Credentials.from_authorized_user_file(
        resolved_settings.youtube_token_file,
        YOUTUBE_UPLOAD_SCOPES,
    )
    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )
    media_body = MediaFileUpload(
        request.video_path,
        chunksize=-1,
        resumable=True,
        mimetype="video/mp4",
    )
    insert_request = youtube.videos().insert(
        part="snippet,status",
        body=_build_request_body(request.metadata),
        media_body=media_body,
    )
    response = _execute_resumable_upload(
        insert_request,
        http_error_cls=http_error_cls,
    )

    youtube_id = response.get("id")
    if not isinstance(youtube_id, str) or not youtube_id:
        raise YouTubeUploadError("youtube upload response missing video id")

    response_status = response.get("status", {})
    actual_privacy = response_status.get(
        "privacyStatus",
        request.metadata.privacy_status,
    )
    return PublishResult(
        youtube_id=youtube_id,
        mode="uploaded",
        requested_privacy_status=request.metadata.privacy_status,
        effective_privacy_status=actual_privacy,
    )


def _build_request_body(metadata: PublishMetadata) -> dict[str, Any]:
    return {
        "snippet": {
            "title": metadata.title,
            "description": metadata.description,
            "tags": list(metadata.tags),
            "categoryId": metadata.category_id,
        },
        "status": {
            "privacyStatus": metadata.privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }


def _require_upload_ready(settings: Settings) -> None:
    eligibility = resolve_upload_eligibility(settings)
    if not eligibility.enabled:
        raise YouTubeUploadError(eligibility.reason or "youtube upload disabled")


def _execute_resumable_upload(
    insert_request: Any,
    *,
    http_error_cls: type[Exception],
) -> dict[str, Any]:
    retries = 0
    while True:
        try:
            _, response = insert_request.next_chunk()
        except http_error_cls as exc:
            status_code = getattr(getattr(exc, "resp", None), "status", None)
            if (
                status_code in RETRYABLE_STATUS_CODES
                and retries < MAX_RESUMABLE_RETRIES
            ):
                retries += 1
                time.sleep(min(2**retries, 8))
                continue
            raise YouTubeUploadError(
                f"youtube resumable upload failed with status {status_code}"
            ) from exc

        if response is None:
            continue
        return response


def _load_google_dependencies():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    return Credentials, build, MediaFileUpload, HttpError
