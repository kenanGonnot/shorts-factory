"""Top-level LCEL pipeline composition.

topic → ScriptChain → VoiceTool → VisualTool → VideoAssemblyTool → SubtitleTool → PublishingTool
"""
from langchain_core.runnables import Runnable

from app.chains.script_chain import build_script_chain
from app.tools.voice_tool import VoiceTool
from app.tools.visual_tool import VisualTool
from app.tools.video_tool import VideoAssemblyTool
from app.tools.subtitle_tool import SubtitleTool
from app.tools.publish_tool import PublishingTool


def build_pipeline() -> Runnable:
    return (
        build_script_chain()
        | VoiceTool()
        | VisualTool()
        | VideoAssemblyTool()
        | SubtitleTool()
        | PublishingTool()
    )
