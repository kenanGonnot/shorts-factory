"""Tests for the focused YouTube upload wrapper."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.publishing.models import PublishMetadata, PublishRequest
from app.services.youtube import (
    YouTubeUploadError,
    resolve_upload_eligibility,
    upload_video,
)


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


def _request() -> PublishRequest:
    return PublishRequest(
        job_id="job-42",
        video_path="/tmp/final.mp4",
        metadata=PublishMetadata(
            title="Typed Python #shorts",
            description="Hook\n\nBody\n\nCTA\n\n#shorts",
            tags=("python", "type hints"),
            privacy_status="unlisted",
        ),
    )


def test_resolve_upload_eligibility_skips_when_client_secrets_are_missing(
    tmp_path: Path,
) -> None:
    eligibility = resolve_upload_eligibility(
        _settings(tmp_path, youtube_client_secrets_file="")
    )
    assert eligibility.enabled is False
    assert eligibility.reason == "no client secrets configured"


def test_upload_video_rejects_missing_token_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path, youtube_token_file=str(tmp_path / "missing.json"))
    with pytest.raises(YouTubeUploadError, match="token file not found"):
        upload_video(_request(), settings=settings)


def test_upload_video_builds_expected_request_body(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    insert_calls: dict[str, object] = {}
    media_calls: dict[str, object] = {}

    class FakeCredentials:
        @classmethod
        def from_authorized_user_file(cls, path, scopes):
            insert_calls["credentials_path"] = path
            insert_calls["scopes"] = scopes
            return object()

    class FakeMediaFileUpload:
        def __init__(self, filename, *, chunksize, resumable, mimetype):
            media_calls["filename"] = filename
            media_calls["chunksize"] = chunksize
            media_calls["resumable"] = resumable
            media_calls["mimetype"] = mimetype

    class FakeInsertRequest:
        def next_chunk(self):
            return None, {"id": "yt123", "status": {"privacyStatus": "unlisted"}}

    class FakeVideos:
        def insert(self, *, part, body, media_body):
            insert_calls["part"] = part
            insert_calls["body"] = body
            insert_calls["media_body"] = media_body
            return FakeInsertRequest()

    class FakeYouTube:
        def videos(self):
            return FakeVideos()

    def fake_build(service_name, version, **kwargs):
        insert_calls["service_name"] = service_name
        insert_calls["version"] = version
        insert_calls["build_kwargs"] = kwargs
        return FakeYouTube()

    class FakeHttpError(Exception):
        pass

    monkeypatch.setattr(
        "app.services.youtube._load_google_dependencies",
        lambda: (FakeCredentials, fake_build, FakeMediaFileUpload, FakeHttpError),
    )

    result = upload_video(_request(), settings=_settings(tmp_path))

    assert result.youtube_id == "yt123"
    assert insert_calls["part"] == "snippet,status"
    assert insert_calls["body"] == {
        "snippet": {
            "title": "Typed Python #shorts",
            "description": "Hook\n\nBody\n\nCTA\n\n#shorts",
            "tags": ["python", "type hints"],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": "unlisted",
            "selfDeclaredMadeForKids": False,
        },
    }
    assert media_calls == {
        "filename": "/tmp/final.mp4",
        "chunksize": -1,
        "resumable": True,
        "mimetype": "video/mp4",
    }


def test_upload_video_retries_retryable_resumable_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sleep_calls: list[int] = []

    class FakeCredentials:
        @classmethod
        def from_authorized_user_file(cls, path, scopes):
            return object()

    class FakeMediaFileUpload:
        def __init__(self, filename, *, chunksize, resumable, mimetype):
            pass

    class FakeResp:
        def __init__(self, status: int):
            self.status = status

    class FakeHttpError(Exception):
        def __init__(self, status: int):
            super().__init__(f"status={status}")
            self.resp = FakeResp(status)

    class FakeInsertRequest:
        def __init__(self) -> None:
            self.calls = 0

        def next_chunk(self):
            self.calls += 1
            if self.calls == 1:
                raise FakeHttpError(500)
            return None, {"id": "yt123", "status": {"privacyStatus": "private"}}

    class FakeVideos:
        def insert(self, *, part, body, media_body):
            return FakeInsertRequest()

    class FakeYouTube:
        def videos(self):
            return FakeVideos()

    monkeypatch.setattr(
        "app.services.youtube._load_google_dependencies",
        lambda: (
            FakeCredentials,
            lambda *args, **kwargs: FakeYouTube(),
            FakeMediaFileUpload,
            FakeHttpError,
        ),
    )
    monkeypatch.setattr("app.services.youtube.time.sleep", sleep_calls.append)

    result = upload_video(_request(), settings=_settings(tmp_path))

    assert result.youtube_id == "yt123"
    assert sleep_calls == [2]


def test_upload_video_raises_on_non_retryable_resumable_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeCredentials:
        @classmethod
        def from_authorized_user_file(cls, path, scopes):
            return object()

    class FakeMediaFileUpload:
        def __init__(self, filename, *, chunksize, resumable, mimetype):
            pass

    class FakeResp:
        def __init__(self, status: int):
            self.status = status

    class FakeHttpError(Exception):
        def __init__(self, status: int):
            super().__init__(f"status={status}")
            self.resp = FakeResp(status)

    class FakeInsertRequest:
        def next_chunk(self):
            raise FakeHttpError(401)

    class FakeVideos:
        def insert(self, *, part, body, media_body):
            return FakeInsertRequest()

    class FakeYouTube:
        def videos(self):
            return FakeVideos()

    monkeypatch.setattr(
        "app.services.youtube._load_google_dependencies",
        lambda: (
            FakeCredentials,
            lambda *args, **kwargs: FakeYouTube(),
            FakeMediaFileUpload,
            FakeHttpError,
        ),
    )

    with pytest.raises(YouTubeUploadError, match="status 401"):
        upload_video(_request(), settings=_settings(tmp_path))
