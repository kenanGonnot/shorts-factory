"""``.srt`` serialization for :class:`SubtitleCue` lists.

Outputs conform to the SubRip specification (``N\\nHH:MM:SS,mmm -->
HH:MM:SS,mmm\\nline1\\nline2\\n\\n``) and are deterministic: the same
cue list always produces the same bytes.
"""
from __future__ import annotations

from app.subtitles.cues import SubtitleCue


def format_timestamp(milliseconds: int) -> str:
    """Format a millisecond offset as a SubRip timestamp.

    ``500`` → ``"00:00:00,500"``, ``3_661_000`` → ``"01:01:01,000"``.
    """
    if milliseconds < 0:
        milliseconds = 0
    total_ms = int(milliseconds)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def serialize_srt(cues: list[SubtitleCue]) -> str:
    """Serialize a cue list into a ``.srt`` document.

    Cue indices are re-assigned to a contiguous ``1..N`` range so that
    callers that build cue lists through multiple planners still emit a
    well-formed SubRip file.
    """
    blocks: list[str] = []
    for i, cue in enumerate(cues, start=1):
        start = format_timestamp(cue.start_ms)
        end = format_timestamp(cue.end_ms)
        body = "\n".join(cue.lines)
        blocks.append(f"{i}\n{start} --> {end}\n{body}\n")
    return "\n".join(blocks)
