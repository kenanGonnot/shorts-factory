"""Metadata building helpers for the publishing stage."""

from __future__ import annotations

import re

from app.chains.state import Script
from app.publishing.models import PublishMetadata

SHORTS_HASHTAG = "#shorts"
MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_BYTES = 5000
MAX_TAGS_BUDGET = 500
SUPPORTED_PRIVACY_STATUSES = frozenset({"public", "private", "unlisted"})


class PublishMetadataError(ValueError):
    """Raised when metadata cannot be normalized into a valid payload."""


def build_publish_metadata(
    script: Script,
    *,
    privacy_status: str,
) -> PublishMetadata:
    normalized_privacy = _validate_privacy_status(privacy_status)
    title = _build_title(script["title"])
    description = _build_description(script)
    tags = _normalize_tags(script.get("tags", []))
    return PublishMetadata(
        title=title,
        description=description,
        tags=tags,
        privacy_status=normalized_privacy,
    )


def _build_title(title: str) -> str:
    normalized = _collapse_whitespace(_remove_shorts_hashtag(title))
    suffix = f" {SHORTS_HASHTAG}"
    truncated = _truncate_text(normalized, MAX_TITLE_LENGTH - len(suffix))
    return f"{truncated}{suffix}".strip()


def _build_description(script: Script) -> str:
    sections = [
        _collapse_whitespace(script["hook"]),
        _collapse_whitespace(script["body"]),
        _collapse_whitespace(script["cta"]),
    ]
    content = "\n\n".join(section for section in sections if section)
    if _contains_shorts_hashtag(content):
        return _truncate_utf8(content, MAX_DESCRIPTION_BYTES)

    suffix = f"\n\n{SHORTS_HASHTAG}"
    reserved_bytes = len(suffix.encode("utf-8"))
    truncated_content = _truncate_utf8(content, MAX_DESCRIPTION_BYTES - reserved_bytes)
    return f"{truncated_content}{suffix}".strip()


def _normalize_tags(tags: list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_tag in tags:
        clean_tag = _collapse_whitespace(raw_tag).lstrip("#").strip()
        if not clean_tag:
            continue
        seen_key = clean_tag.casefold()
        if seen_key in seen:
            continue
        seen.add(seen_key)
        normalized.append(clean_tag)

    kept: list[str] = []
    budget = 0
    for tag in normalized:
        tag_cost = _youtube_tag_cost(tag)
        separator_cost = 1 if kept else 0
        if budget + separator_cost + tag_cost > MAX_TAGS_BUDGET:
            continue
        kept.append(tag)
        budget += separator_cost + tag_cost
    return tuple(kept)


def _validate_privacy_status(privacy_status: str) -> str:
    normalized = privacy_status.strip().lower()
    if normalized not in SUPPORTED_PRIVACY_STATUSES:
        raise PublishMetadataError(
            f"unsupported privacy_status: {privacy_status}"
        )
    return normalized


def _truncate_text(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    truncated = text[:max_length].rstrip()
    return truncated


def _truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()


def _collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def _remove_shorts_hashtag(text: str) -> str:
    return re.sub(r"(?i)(?<!\w)#shorts\b", "", text).strip()


def _contains_shorts_hashtag(text: str) -> bool:
    return re.search(r"(?i)(?<!\w)#shorts\b", text) is not None


def _youtube_tag_cost(tag: str) -> int:
    return len(tag) + 2 if " " in tag else len(tag)
