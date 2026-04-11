"""Smoke test: tools compose into a Runnable and run with stubs."""
from app.tools.base import PipelineTool
from app.chains.state import PipelineState


class StubScript(PipelineTool):
    name = "StubScript"

    def run(self, state: PipelineState) -> PipelineState:
        return {
            **state,
            "script": {
                "title": "t",
                "hook": "h",
                "body": "b1. b2.",
                "cta": "c",
                "tags": ["a"],
            },
        }


class StubStep(PipelineTool):
    def __init__(self, name, key, value):
        self.name = name
        self.key = key
        self.value = value

    def run(self, state):
        return {**state, self.key: self.value}


def test_pipeline_composes_and_runs():
    pipeline = (
        StubScript()
        | StubStep("voice", "audio_path", "/tmp/a.mp3")
        | StubStep("visual", "visual_assets", [{"path": "/tmp/c.mp4", "section": "hook", "chunk_index": 0, "asset_type": "clip", "provider": "stub", "start_ms": 0, "end_ms": 1000, "duration_ms": 1000, "width": 1080, "height": 1920, "prompt": None, "source_url": None}])
        | StubStep("video", "video_path", "/tmp/v.mp4")
        | StubStep("subs", "final_path", "/tmp/f.mp4")
        | StubStep("publish", "youtube_id", "yt123")
    )
    out = pipeline.invoke({"job_id": "j1", "topic": "x"})
    assert out["youtube_id"] == "yt123"
    assert out["script"]["title"] == "t"
