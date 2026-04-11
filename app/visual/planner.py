"""Deterministic visual planner.

Converts ``script`` + ``audio_segments`` into a sequence of
:class:`VisualRequest` slots ready for provider resolution.

The planner is pure and has no IO. It favors timing from
``audio_segments`` when available and falls back to an equal-split
across the known ``audio_duration_ms`` (or a fixed per-segment default).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.chains.state import Script
from app.visual.models import VisualRequest, VisualSection

# When no audio timing is known at all, each segment defaults to 3 s.
_DEFAULT_SEGMENT_MS = 3000
_SECTIONS: tuple[VisualSection, ...] = ("hook", "body", "cta")


@dataclass(slots=True)
class VisualPlanner:
    """Plans visual slots from script + voice timing metadata."""

    default_segment_ms: int = _DEFAULT_SEGMENT_MS

    def plan(
        self,
        script: Script,
        audio_segments: list[dict] | None = None,
        audio_duration_ms: int | None = None,
    ) -> list[VisualRequest]:
        segments = audio_segments or []
        if segments:
            return self._plan_from_segments(script, segments)
        return self._plan_equal_split(script, audio_duration_ms)

    # ------------------------------------------------------------------
    # primary path: derive timing from voice segments
    # ------------------------------------------------------------------
    def _plan_from_segments(
        self, script: Script, segments: list[dict]
    ) -> list[VisualRequest]:
        cursor = 0
        requests: list[VisualRequest] = []
        for seg in segments:
            section = seg.get("section")
            if section not in _SECTIONS:
                continue
            chunk_index = int(seg.get("chunk_index", 0))
            duration = seg.get("duration_ms")
            if duration is None or int(duration) <= 0:
                duration = self.default_segment_ms
            duration = int(duration)
            start, end = cursor, cursor + duration
            cursor = end
            text = str(seg.get("text", "")).strip()
            requests.append(
                VisualRequest(
                    section=section,  # type: ignore[arg-type]
                    chunk_index=chunk_index,
                    start_ms=start,
                    end_ms=end,
                    prompt=self._prompt_for(script, section, text),  # type: ignore[arg-type]
                    query=self._query_for(script, section, text),  # type: ignore[arg-type]
                )
            )
        if requests:
            return requests
        return self._plan_equal_split(script, None)

    # ------------------------------------------------------------------
    # fallback path: equal-split across known/assumed duration
    # ------------------------------------------------------------------
    def _plan_equal_split(
        self, script: Script, audio_duration_ms: int | None
    ) -> list[VisualRequest]:
        sections = [s for s in _SECTIONS if str(script.get(s, "")).strip()]
        if not sections:
            sections = list(_SECTIONS)
        total = (
            int(audio_duration_ms)
            if audio_duration_ms and audio_duration_ms > 0
            else self.default_segment_ms * len(sections)
        )
        # Integer split with remainder added to the last slot so the
        # total duration is preserved exactly.
        base = total // len(sections)
        remainder = total - base * len(sections)
        requests: list[VisualRequest] = []
        cursor = 0
        for i, section in enumerate(sections):
            dur = base + (remainder if i == len(sections) - 1 else 0)
            start, end = cursor, cursor + dur
            cursor = end
            text = str(script.get(section, "")).strip()
            requests.append(
                VisualRequest(
                    section=section,
                    chunk_index=0,
                    start_ms=start,
                    end_ms=end,
                    prompt=self._prompt_for(script, section, text),
                    query=self._query_for(script, section, text),
                )
            )
        return requests

    # ------------------------------------------------------------------
    # deterministic prompt / query generation (no LLM)
    # ------------------------------------------------------------------
    @staticmethod
    def _prompt_for(script: Script, section: VisualSection, text: str) -> str:
        title = str(script.get("title", "")).strip()
        base = text or title
        match section:
            case "hook":
                return f"Bold vertical 9:16 poster illustrating: {base}. High contrast, cinematic."
            case "cta":
                return f"Clean 9:16 call-to-action still for: {title}. Minimalist, brand-friendly."
            case _:
                return f"Informative 9:16 visual for: {base}"

    @staticmethod
    def _query_for(script: Script, section: VisualSection, text: str) -> str:
        title = str(script.get("title", "")).strip()
        # Stock search works best with a short keyword query. Fall back
        # to the title when the per-segment text is empty.
        keyword = text.split(".")[0] if text else title
        return keyword.strip() or title or "abstract background"
