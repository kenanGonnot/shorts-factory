"""Unit tests for internal publishing models."""

from app.publishing.models import (
    PublishContext,
    PublishMetadata,
    PublishRequest,
    PublishResult,
)


SAMPLE_SCRIPT = {
    "title": "Why typing matters",
    "hook": "Types catch bugs early.",
    "body": "Typed refactors are easier to trust.",
    "cta": "Follow for more Python tips.",
    "tags": ["python", "typing"],
}


def test_publish_metadata_normalizes_tags_to_tuple() -> None:
    metadata = PublishMetadata(
        title="Typed Python #shorts",
        description="Description",
        tags=["python", "typing"],
    )
    assert metadata.tags == ("python", "typing")


def test_publish_context_builds_deterministic_dry_run_id() -> None:
    context = PublishContext(
        job_id="job-42",
        final_path="/tmp/final.mp4",
        script=SAMPLE_SCRIPT,
    )
    assert context.dry_run_youtube_id == "dryrun-job-42"


def test_publish_result_exposes_dry_run_flag() -> None:
    result = PublishResult(
        youtube_id="dryrun-job-42",
        mode="dry_run",
        requested_privacy_status="private",
        effective_privacy_status="private",
        dry_run_reason="missing credentials",
    )
    assert result.is_dry_run is True


def test_publish_request_keeps_metadata_reference() -> None:
    metadata = PublishMetadata(
        title="Typed Python #shorts",
        description="Description",
    )
    request = PublishRequest(
        job_id="job-42",
        video_path="/tmp/final.mp4",
        metadata=metadata,
    )
    assert request.metadata is metadata
