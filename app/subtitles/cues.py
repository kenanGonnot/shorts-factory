"""Subtitle cue model and planning.

Cue planning turns voice-stage metadata into a deterministic list of
subtitle cards ready for ``.srt`` serialization and burn-in.

Timing priority (highest first):

1. ``audio_segments`` -- rich per-chunk timing already produced by
   :class:`app.tools.voice_tool.VoiceTool`.
2. ``audio_segments_path`` -- the same manifest persisted to disk. We
   parse the JSON when the in-memory copy is absent (e.g. when replaying
   a job from storage).
3. Deterministic fallback: split the ``script`` into short cues and
   distribute ``audio_duration_ms`` proportionally to text length.

The resulting cues always satisfy two invariants:

- cues are ordered by ``start_ms`` and do not overlap,
- long segments are split into multiple cards for readability while
  preserving the parent timing envelope (sub-cues add up to the parent
  duration to the nearest millisecond).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.chains.state import Script
from app.subtitles.validate import SubtitlePlanContext

# ---------------------------------------------------------------------------
# Readability knobs. These are deliberately hard-coded for v1 -- see
# ``implementation-plan.md`` question 2.
# ---------------------------------------------------------------------------

#: Maximum characters per subtitle line. Keeps cards mobile-readable.
MAX_LINE_CHARS: int = 32

#: Maximum lines per cue card. Two lines is the common short-form style.
MAX_LINES_PER_CUE: int = 2

#: Upper bound on total characters per cue (``MAX_LINES_PER_CUE * MAX_LINE_CHARS``).
MAX_CHARS_PER_CUE: int = MAX_LINES_PER_CUE * MAX_LINE_CHARS

# Split on word boundaries while preserving punctuation-attached words.
_WORD_SPLIT_RE = re.compile(r"\s+")

# Prefer splitting at sentence-like punctuation before word boundaries.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?,;:])\s+")

_SECTIONS: tuple[str, ...] = ("hook", "body", "cta")


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    """One subtitle card ready for serialization.

    Times are stored in integer milliseconds so rounding behavior is
    explicit and deterministic across the cue planner, serializer, and
    ffmpeg burn-in.
    """

    index: int
    start_ms: int
    end_ms: int
    lines: tuple[str, ...]

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def build_cues(ctx: SubtitlePlanContext) -> list[SubtitleCue]:
    """Build subtitle cues from a validated :class:`SubtitlePlanContext`.

    Applies the documented timing priority: in-memory segments first,
    persisted segments second, deterministic fallback third.
    """
    segments = ctx.audio_segments
    if not segments and ctx.audio_segments_path:
        segments = _load_segments_file(ctx.audio_segments_path)

    if segments:
        return plan_cues_from_segments(segments, ctx.audio_duration_ms)

    return plan_cues_from_script_fallback(ctx.script, ctx.audio_duration_ms or 0)


# ---------------------------------------------------------------------------
# Segment-driven planning
# ---------------------------------------------------------------------------


def plan_cues_from_segments(
    segments: list[dict],
    total_duration_ms: int | None,
) -> list[SubtitleCue]:
    """Plan cues from per-chunk voice segments.

    Each segment is split into one or more cards for readability. Sub-cue
    durations are distributed proportionally to text length so the sum
    equals the parent segment duration.
    """
    durations = _resolve_segment_durations(segments, total_duration_ms)
    cues: list[SubtitleCue] = []
    cursor_ms = 0
    next_index = 1

    for segment, duration_ms in zip(segments, durations):
        text = (segment.get("text") or "").strip()
        if not text:
            cursor_ms += duration_ms
            continue

        cards = _split_text_into_cards(text)
        sub_durations = _distribute_duration(cards, duration_ms)
        for card_text, sub_ms in zip(cards, sub_durations):
            start_ms = cursor_ms
            end_ms = cursor_ms + sub_ms
            cues.append(
                SubtitleCue(
                    index=next_index,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    lines=_wrap_lines(card_text),
                )
            )
            next_index += 1
            cursor_ms = end_ms
        # Absorb any rounding drift inside the segment envelope so the
        # next segment starts at the intended cursor.
        expected_cursor = cues[-1].end_ms if cues else cursor_ms
        if cards:
            # Snap to the parent envelope to avoid accumulated drift.
            cursor_ms = expected_cursor

    return cues


# ---------------------------------------------------------------------------
# Script-driven deterministic fallback
# ---------------------------------------------------------------------------


def plan_cues_from_script_fallback(
    script: Script,
    total_duration_ms: int,
) -> list[SubtitleCue]:
    """Deterministic fallback: split the script and allocate time by length.

    Used when no voice metadata is available. When ``total_duration_ms``
    is zero we emit one 2-second cue per card so the output is still
    valid (degraded-mode runs with silent audio still produce readable
    subtitles).
    """
    pseudo_segments: list[dict] = []
    for section in _SECTIONS:
        text = (script.get(section) or "").strip()
        if not text:
            continue
        pseudo_segments.append({"text": text, "duration_ms": None})

    if not pseudo_segments:
        return []

    if total_duration_ms <= 0:
        # 2 seconds per card gives a readable, deterministic output.
        cards_total = sum(
            max(1, len(_split_text_into_cards(s["text"])))
            for s in pseudo_segments
        )
        total_duration_ms = cards_total * 2000

    # Distribute proportionally to character length.
    lengths = [len(s["text"]) for s in pseudo_segments]
    allocations = _allocate_proportional(lengths, total_duration_ms)
    for segment, allocation in zip(pseudo_segments, allocations):
        segment["duration_ms"] = allocation

    return plan_cues_from_segments(pseudo_segments, total_duration_ms)


# ---------------------------------------------------------------------------
# Line breaking
# ---------------------------------------------------------------------------


def _split_text_into_cards(text: str) -> list[str]:
    """Split ``text`` into subtitle-card-sized chunks.

    Splits first on sentence/phrase punctuation. Any phrase still longer
    than :data:`MAX_CHARS_PER_CUE` is hard-wrapped on word boundaries.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= MAX_CHARS_PER_CUE:
        return [text]

    phrases = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]
    cards: list[str] = []
    buffer = ""
    for phrase in phrases:
        if len(phrase) > MAX_CHARS_PER_CUE:
            if buffer:
                cards.append(buffer)
                buffer = ""
            cards.extend(_hard_wrap_to_cards(phrase))
            continue
        candidate = f"{buffer} {phrase}".strip() if buffer else phrase
        if len(candidate) > MAX_CHARS_PER_CUE:
            if buffer:
                cards.append(buffer)
            buffer = phrase
        else:
            buffer = candidate
    if buffer:
        cards.append(buffer)
    return cards


def _hard_wrap_to_cards(phrase: str) -> list[str]:
    words = _WORD_SPLIT_RE.split(phrase)
    cards: list[str] = []
    buffer = ""
    for word in words:
        if not word:
            continue
        candidate = f"{buffer} {word}".strip() if buffer else word
        if len(candidate) > MAX_CHARS_PER_CUE and buffer:
            cards.append(buffer)
            buffer = word
        else:
            buffer = candidate
    if buffer:
        cards.append(buffer)
    return cards


def _wrap_lines(card_text: str) -> tuple[str, ...]:
    """Wrap a single card into at most :data:`MAX_LINES_PER_CUE` lines."""
    words = _WORD_SPLIT_RE.split(card_text)
    lines: list[str] = []
    buffer = ""
    for word in words:
        if not word:
            continue
        candidate = f"{buffer} {word}".strip() if buffer else word
        if len(candidate) > MAX_LINE_CHARS and buffer:
            lines.append(buffer)
            buffer = word
        else:
            buffer = candidate
    if buffer:
        lines.append(buffer)
    # If wrapping overflowed our line budget (very long words), keep the
    # extra content on the last line rather than dropping characters.
    if len(lines) > MAX_LINES_PER_CUE:
        head = lines[: MAX_LINES_PER_CUE - 1]
        tail = " ".join(lines[MAX_LINES_PER_CUE - 1 :])
        lines = [*head, tail]
    return tuple(lines)


# ---------------------------------------------------------------------------
# Duration math
# ---------------------------------------------------------------------------


def _resolve_segment_durations(
    segments: list[dict],
    total_duration_ms: int | None,
) -> list[int]:
    """Return one duration per segment, filling gaps deterministically.

    When a segment is missing ``duration_ms``, the gap is filled by
    allocating remaining ``total_duration_ms`` proportionally to text
    length. If no total is available, a 2-second default is used.
    """
    known: list[int | None] = []
    for segment in segments:
        value = segment.get("duration_ms")
        if isinstance(value, (int, float)) and value >= 0:
            known.append(int(value))
        else:
            known.append(None)

    known_sum = sum(v for v in known if v is not None)
    missing_indices = [i for i, v in enumerate(known) if v is None]

    if not missing_indices:
        return [v for v in known if v is not None]

    if total_duration_ms is not None and total_duration_ms > known_sum:
        remainder = total_duration_ms - known_sum
        lengths = [
            max(1, len((segments[i].get("text") or "").strip()))
            for i in missing_indices
        ]
        allocations = _allocate_proportional(lengths, remainder)
    else:
        allocations = [2000] * len(missing_indices)

    for idx, allocation in zip(missing_indices, allocations):
        known[idx] = allocation
    return [int(v) for v in known]  # type: ignore[misc]


def _distribute_duration(cards: list[str], parent_ms: int) -> list[int]:
    """Split ``parent_ms`` across ``cards`` proportionally to card length."""
    if not cards:
        return []
    if len(cards) == 1:
        return [parent_ms]
    lengths = [max(1, len(card)) for card in cards]
    return _allocate_proportional(lengths, parent_ms)


def _allocate_proportional(weights: list[int], total: int) -> list[int]:
    """Allocate ``total`` units across ``weights`` proportionally.

    Uses floor + largest-remainder distribution so the result always
    sums to ``total`` exactly. Guarantees every bucket gets at least one
    unit when ``total >= len(weights)``.
    """
    if not weights:
        return []
    if total <= 0:
        return [0] * len(weights)
    weight_sum = sum(weights) or len(weights)
    raw = [(w * total) / weight_sum for w in weights]
    floors = [int(r) for r in raw]
    remainder = total - sum(floors)
    # Largest remainder wins the leftover units.
    fractional = sorted(
        range(len(weights)),
        key=lambda i: (raw[i] - floors[i], weights[i]),
        reverse=True,
    )
    for i in fractional[:remainder]:
        floors[i] += 1
    return floors


# ---------------------------------------------------------------------------
# Filesystem fallback
# ---------------------------------------------------------------------------


def _load_segments_file(path: str) -> list[dict]:
    """Load a voice ``segments.json`` manifest from disk.

    Accepts either ``{"segments": [...]}`` (the format emitted by
    :class:`VoiceTool`) or a bare list.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "segments" in data:
        return list(data["segments"])
    if isinstance(data, list):
        return list(data)
    return []
