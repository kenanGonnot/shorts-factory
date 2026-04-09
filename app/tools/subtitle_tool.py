"""Naive subtitle generator: chunks the script into ~3s lines and burns SRT."""
from __future__ import annotations
import subprocess
import tempfile

from app.services.storage import get_storage
from app.chains.state import PipelineState
from app.tools.base import PipelineTool


class SubtitleTool(PipelineTool):
    name = "SubtitleTool"

    def run(self, state: PipelineState) -> PipelineState:
        storage = get_storage()
        script = state["script"]
        body_lines = [line for line in script["body"].split(". ") if line]
        lines = [script["hook"], *body_lines, script["cta"]]
        srt = _to_srt(lines, per_line_seconds=3)
        srt_key = f"{state['job_id']}/subs.srt"
        srt_path = storage.save(srt_key, srt.encode("utf-8"))

        out_path = tempfile.mktemp(suffix=".mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-i", state["video_path"],
             "-vf", f"subtitles={srt_path}:force_style='Fontsize=18,"
                    "PrimaryColour=&H00FFFFFF&,BorderStyle=3,Outline=1'",
             "-c:a", "copy", out_path],
            check=True, capture_output=True,
        )
        final_key = f"{state['job_id']}/final.mp4"
        final = storage.save(final_key, open(out_path, "rb").read())
        return {**state, "subtitle_path": srt_path, "final_path": final}


def _to_srt(lines: list[str], per_line_seconds: int) -> str:
    out = []
    for i, line in enumerate(lines):
        start = i * per_line_seconds
        end = start + per_line_seconds
        out.append(f"{i+1}\n{_ts(start)} --> {_ts(end)}\n{line.strip()}\n")
    return "\n".join(out)


def _ts(s: int) -> str:
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d},000"
