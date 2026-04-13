"""Validation tests for the publishing stage."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.publishing.validate import PublishValidationError, validate_state


def _stub_final(tmp_path: Path) -> str:
    final_path = tmp_path / "final.mp4"
    final_path.write_bytes(b"\x00" * 64)
    return str(final_path)


def _stub_state(tmp_path: Path, **overrides) -> dict:
    state = {
        "job_id": "job-42",
        "final_path": _stub_final(tmp_path),
        "script": {
            "title": "Typed Python",
            "hook": "Types catch bugs early.",
            "body": "Type hints reduce refactor fear.",
            "cta": "Follow for more Python tips.",
            "tags": ["python", "typing"],
        },
    }
    state.update(overrides)
    return state


def test_validate_state_happy_path_returns_context(tmp_path: Path) -> None:
    context = validate_state(_stub_state(tmp_path))
    assert context.job_id == "job-42"
    assert context.final_path.endswith("final.mp4")
    assert context.script["title"] == "Typed Python"


def test_validate_state_accepts_staged_s3_uri(tmp_path: Path) -> None:
    context = validate_state(
        _stub_state(tmp_path, final_path="s3://shorts-bucket/job-42/final.mp4")
    )
    assert context.final_path == "s3://shorts-bucket/job-42/final.mp4"


def test_validate_state_rejects_missing_job_id(tmp_path: Path) -> None:
    state = _stub_state(tmp_path)
    del state["job_id"]
    with pytest.raises(PublishValidationError, match="job_id"):
        validate_state(state)


def test_validate_state_rejects_missing_final_path(tmp_path: Path) -> None:
    state = _stub_state(tmp_path)
    del state["final_path"]
    with pytest.raises(PublishValidationError, match="final_path"):
        validate_state(state)


def test_validate_state_rejects_missing_script(tmp_path: Path) -> None:
    state = _stub_state(tmp_path)
    del state["script"]
    with pytest.raises(PublishValidationError, match="script"):
        validate_state(state)


def test_validate_state_rejects_empty_script_field(tmp_path: Path) -> None:
    state = _stub_state(tmp_path)
    state["script"] = {**state["script"], "body": ""}
    with pytest.raises(PublishValidationError, match="body"):
        validate_state(state)


def test_validate_state_rejects_non_string_tag(tmp_path: Path) -> None:
    state = _stub_state(tmp_path)
    state["script"] = {**state["script"], "tags": ["python", 42]}
    with pytest.raises(PublishValidationError, match="tags"):
        validate_state(state)


def test_validate_state_rejects_nonexistent_local_final_path(tmp_path: Path) -> None:
    state = _stub_state(tmp_path, final_path=str(tmp_path / "missing.mp4"))
    with pytest.raises(PublishValidationError, match="does not exist"):
        validate_state(state)


def test_validate_state_rejects_unsupported_remote_scheme(tmp_path: Path) -> None:
    state = _stub_state(tmp_path, final_path="https://example.com/final.mp4")
    with pytest.raises(PublishValidationError, match="unsupported scheme"):
        validate_state(state)
