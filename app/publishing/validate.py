"""Validation helpers for the publishing stage."""

from __future__ import annotations

from pathlib import Path

from app.chains.state import PipelineState
from app.publishing.models import PublishContext


class PublishValidationError(ValueError):
    """Raised when publishing inputs are unusable."""


def validate_state(state: PipelineState) -> PublishContext:
    job_id = _require_non_empty_str(state, "job_id")
    final_path = _require_non_empty_str(state, "final_path")
    _validate_final_path(final_path)

    script = state.get("script")
    if not isinstance(script, dict):
        raise PublishValidationError("script is missing or not a dict")

    title = _require_script_str(script, "title")
    hook = _require_script_str(script, "hook")
    body = _require_script_str(script, "body")
    cta = _require_script_str(script, "cta")

    tags = script.get("tags", [])
    if not isinstance(tags, list):
        raise PublishValidationError("script['tags'] must be a list")
    for index, tag in enumerate(tags):
        if not isinstance(tag, str):
            raise PublishValidationError(
                f"script['tags'][{index}] must be a string"
            )

    return PublishContext(
        job_id=job_id,
        final_path=final_path,
        script={
            "title": title,
            "hook": hook,
            "body": body,
            "cta": cta,
            "tags": list(tags),
        },
    )


def _require_non_empty_str(state: PipelineState, key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PublishValidationError(f"{key} is missing or empty")
    return value.strip()


def _require_script_str(script: dict, key: str) -> str:
    value = script.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PublishValidationError(f"script['{key}'] is missing or empty")
    return value.strip()


def _validate_final_path(final_path: str) -> None:
    if final_path.startswith("s3://"):
        return
    if "://" in final_path:
        raise PublishValidationError(
            f"final_path uses an unsupported scheme: {final_path}"
        )
    if not Path(final_path).is_file():
        raise PublishValidationError(f"final_path does not exist: {final_path}")
