from typing import TypedDict


class Script(TypedDict):
    title: str
    hook: str
    body: str
    cta: str
    tags: list[str]


class PipelineState(TypedDict, total=False):
    job_id: str
    topic: str
    script: Script
    audio_path: str
    image_paths: list[str]
    video_path: str
    subtitle_path: str
    final_path: str
    youtube_id: str | None
