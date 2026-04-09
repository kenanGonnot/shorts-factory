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
        | StubStep("visual", "image_paths", ["/tmp/c.mp4"])
        | StubStep("video", "video_path", "/tmp/v.mp4")
        | StubStep("subs", "final_path", "/tmp/f.mp4")
        | StubStep("publish", "youtube_id", "yt123")
    )
    out = pipeline.invoke({"job_id": "j1", "topic": "x"})
    assert out["youtube_id"] == "yt123"
    assert out["script"]["title"] == "t"
