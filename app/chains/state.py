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
    audio_segments_path: str
    audio_segments: list[dict]
    audio_duration_ms: int
    voice_provider: str
    voice_id: str
    # Rich visual manifest (list of VisualAsset.as_dict()).
    # Replaces the legacy ``image_paths`` contract.
    visual_assets: list[dict]
    video_path: str
    subtitle_path: str
    final_path: str
    youtube_id: str | None
