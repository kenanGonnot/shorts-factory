"""Metadata tests for the publishing stage."""

from __future__ import annotations

import pytest

from app.publishing.metadata import (
    MAX_DESCRIPTION_BYTES,
    MAX_TAGS_BUDGET,
    MAX_TITLE_LENGTH,
    PublishMetadataError,
    build_publish_metadata,
)


def _script(**overrides) -> dict:
    script = {
        "title": "Typed Python for refactors",
        "hook": "Types catch bugs before prod.",
        "body": "Type hints document behavior and make tooling smarter.",
        "cta": "Follow for more Python architecture tips.",
        "tags": ["python", "type hints", "refactoring"],
    }
    script.update(overrides)
    return script


def _tag_budget(tags: tuple[str, ...]) -> int:
    total = 0
    for index, tag in enumerate(tags):
        if index:
            total += 1
        total += len(tag) + 2 if " " in tag else len(tag)
    return total


def test_build_publish_metadata_truncates_title_and_keeps_shorts_suffix() -> None:
    long_title = "Very long title " * 10
    metadata = build_publish_metadata(
        _script(title=long_title),
        privacy_status="private",
    )
    assert len(metadata.title) <= MAX_TITLE_LENGTH
    assert metadata.title.endswith("#shorts")


def test_build_publish_metadata_does_not_duplicate_shorts_hashtag() -> None:
    metadata = build_publish_metadata(
        _script(
            title="Typed Python #shorts",
            hook="Types catch bugs early. #shorts",
        ),
        privacy_status="private",
    )
    assert metadata.title.lower().count("#shorts") == 1
    assert metadata.description.lower().count("#shorts") == 1


def test_build_publish_metadata_enforces_description_byte_limit() -> None:
    metadata = build_publish_metadata(
        _script(body="é" * 6000),
        privacy_status="private",
    )
    assert len(metadata.description.encode("utf-8")) <= MAX_DESCRIPTION_BYTES
    assert "#shorts" in metadata.description.lower()


def test_build_publish_metadata_normalizes_tags_and_caps_budget() -> None:
    metadata = build_publish_metadata(
        _script(
            tags=[
                " python ",
                "#python",
                "type hints",
                "",
                "A" * 600,
                "clean code",
            ]
        ),
        privacy_status="private",
    )
    assert metadata.tags[0] == "python"
    assert "type hints" in metadata.tags
    assert metadata.tags.count("python") == 1
    assert _tag_budget(metadata.tags) <= MAX_TAGS_BUDGET


def test_build_publish_metadata_rejects_unsupported_privacy() -> None:
    with pytest.raises(PublishMetadataError, match="unsupported privacy_status"):
        build_publish_metadata(_script(), privacy_status="friends")


def test_build_publish_metadata_is_deterministic_for_same_script() -> None:
    script = _script()
    first = build_publish_metadata(script, privacy_status="private")
    second = build_publish_metadata(script, privacy_status="private")
    assert first == second
