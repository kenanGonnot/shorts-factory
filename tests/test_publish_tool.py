"""Tests for the public PublishingTool pipeline node."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.publishing.models import PublishResult
from app.services.storage import StagedAsset
from app.tools.publish_tool import PublishingTool


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


def _state(tmp_path: Path, **overrides) -> dict:
    final_path = tmp_path / "final.mp4"
    final_path.write_bytes(b"\x00" * 64)
    state = {
        "job_id": "job-42",
        "topic": "typed python",
        "final_path": str(final_path),
        "script": {
            "title": "Typed Python",
            "hook": "Types catch bugs early.",
            "body": "Typed refactors are easier to trust.",
            "cta": "Follow for more Python tips.",
            "tags": ["python", "typing"],
        },
    }
    state.update(overrides)
    return state


def test_publishing_tool_preserves_state_immutability_and_output_shape(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    original_script = dict(state["script"])
    tool = PublishingTool(
        settings=_settings(tmp_path, youtube_client_secrets_file=""),
    )

    output = tool.invoke(state)

    assert state["script"] == original_script
    assert "youtube_id" not in state
    assert output["youtube_id"] == "dryrun-job-42"
    assert set(output) == set(state) | {"youtube_id"}


def test_publishing_tool_stages_final_asset_through_service_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    stage_calls: list[str] = []
    upload_calls: list[str] = []
    staged_path = tmp_path / "staged-final.mp4"
    staged_path.write_bytes(b"\x00" * 64)

    class FakeStorage:
        def stage_local(self, key_or_path: str) -> StagedAsset:
            stage_calls.append(key_or_path)
            return StagedAsset(local_path=str(staged_path))

    def fake_upload_video(request, *, settings):
        upload_calls.append(request.video_path)
        return PublishResult(
            youtube_id="yt123",
            mode="uploaded",
            requested_privacy_status=request.metadata.privacy_status,
            effective_privacy_status=request.metadata.privacy_status,
        )

    monkeypatch.setattr("app.publishing.service.upload_video", fake_upload_video)

    state = _state(tmp_path, final_path="s3://shorts-bucket/job-42/final.mp4")
    tool = PublishingTool(
        storage=FakeStorage(),
        settings=_settings(tmp_path),
    )

    output = tool.invoke(state)

    assert stage_calls == ["s3://shorts-bucket/job-42/final.mp4"]
    assert upload_calls == [str(staged_path)]
    assert output["youtube_id"] == "yt123"


def test_publishing_tool_only_writes_expected_pipeline_field(tmp_path: Path) -> None:
    state = _state(tmp_path, subtitle_path="/tmp/subtitles.srt", video_path="/tmp/video.mp4")
    tool = PublishingTool(
        settings=_settings(tmp_path, youtube_client_secrets_file=""),
    )

    output = tool.invoke(state)

    assert output["subtitle_path"] == "/tmp/subtitles.srt"
    assert output["video_path"] == "/tmp/video.mp4"
    assert output["youtube_id"] == "dryrun-job-42"
