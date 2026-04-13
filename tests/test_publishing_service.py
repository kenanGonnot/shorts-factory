"""Tests for the publishing orchestration service."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.publishing.models import PublishContext, PublishMetadata, PublishResult
from app.publishing.service import publish_video
from app.services.storage import LocalStorage, StagedAsset


def _settings(tmp_path: Path, **overrides) -> Settings:
    client_secrets = tmp_path / "client-secrets.json"
    client_secrets.write_text("{}")
    token_file = tmp_path / "youtube-token.json"
    token_file.write_text("{}")
    values = {
        "youtube_client_secrets_file": str(client_secrets),
        "youtube_token_file": str(token_file),
        "youtube_privacy": "private",
    }
    values.update(overrides)
    return Settings(**values)


def _context(final_path: str) -> PublishContext:
    return PublishContext(
        job_id="job-42",
        final_path=final_path,
        script={
            "title": "Typed Python",
            "hook": "Types catch bugs early.",
            "body": "Typed refactors are easier.",
            "cta": "Follow for more Python tips.",
            "tags": ["python"],
        },
    )


def _metadata() -> PublishMetadata:
    return PublishMetadata(
        title="Typed Python #shorts",
        description="Hook\n\nBody\n\nCTA\n\n#shorts",
        tags=("python",),
        privacy_status="private",
    )


def test_publish_video_returns_deterministic_dry_run_id(tmp_path: Path) -> None:
    storage = LocalStorage(str(tmp_path / "storage"))
    final_path = storage.save("job-42/final.mp4", b"video")

    result = publish_video(
        context=_context(final_path),
        metadata=_metadata(),
        storage=storage,
        settings=_settings(tmp_path, youtube_client_secrets_file=""),
    )

    assert result.youtube_id == "dryrun-job-42"
    assert result.is_dry_run is True


def test_publish_video_uses_local_storage_path_for_real_upload(tmp_path: Path) -> None:
    storage = LocalStorage(str(tmp_path / "storage"))
    final_path = storage.save("job-42/final.mp4", b"video")
    captured: dict[str, object] = {}

    def fake_uploader(request, *, settings):
        captured["video_path"] = request.video_path
        captured["job_id"] = request.job_id
        return PublishResult(
            youtube_id="yt123",
            mode="uploaded",
            requested_privacy_status=request.metadata.privacy_status,
            effective_privacy_status=request.metadata.privacy_status,
        )

    result = publish_video(
        context=_context(final_path),
        metadata=_metadata(),
        storage=storage,
        settings=_settings(tmp_path),
        uploader=fake_uploader,
    )

    assert captured["job_id"] == "job-42"
    assert captured["video_path"] == final_path
    assert result.youtube_id == "yt123"


def test_publish_video_stages_remote_asset_before_upload(tmp_path: Path) -> None:
    class FakeStorage:
        def __init__(self) -> None:
            self.stage_calls: list[str] = []

        def stage_local(self, key_or_path: str) -> StagedAsset:
            self.stage_calls.append(key_or_path)
            staged = tmp_path / "staged-final.mp4"
            staged.write_bytes(b"video")
            return StagedAsset(local_path=str(staged))

    captured: dict[str, object] = {}

    def fake_uploader(request, *, settings):
        captured["video_path"] = request.video_path
        return PublishResult(
            youtube_id="yt456",
            mode="uploaded",
            requested_privacy_status=request.metadata.privacy_status,
            effective_privacy_status="private",
        )

    storage = FakeStorage()
    result = publish_video(
        context=_context("s3://shorts-bucket/job-42/final.mp4"),
        metadata=_metadata(),
        storage=storage,
        settings=_settings(tmp_path),
        uploader=fake_uploader,
    )

    assert storage.stage_calls == ["s3://shorts-bucket/job-42/final.mp4"]
    assert str(captured["video_path"]).endswith("staged-final.mp4")
    assert result.youtube_id == "yt456"


def test_publish_video_passes_through_real_upload_result(tmp_path: Path) -> None:
    storage = LocalStorage(str(tmp_path / "storage"))
    final_path = storage.save("job-42/final.mp4", b"video")

    def fake_uploader(request, *, settings):
        return PublishResult(
            youtube_id="yt789",
            mode="uploaded",
            requested_privacy_status="private",
            effective_privacy_status="unlisted",
        )

    result = publish_video(
        context=_context(final_path),
        metadata=_metadata(),
        storage=storage,
        settings=_settings(tmp_path),
        uploader=fake_uploader,
    )

    assert result.youtube_id == "yt789"
    assert result.effective_privacy_status == "unlisted"
