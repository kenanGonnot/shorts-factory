"""Smoke tests for the internal publishing package layout."""

from app import publishing


def test_publishing_package_exports_public_helpers() -> None:
    assert hasattr(publishing, "validate_state")
    assert hasattr(publishing, "publish_video")
    assert hasattr(publishing, "build_publish_metadata")
