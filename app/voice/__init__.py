"""Voice generation domain.

Provider abstraction + script renderer used by ``app.tools.voice_tool.VoiceTool``.
"""
from app.voice.models import (
    AudioSegment,
    RenderedAudio,
    VoiceConfig,
    VoiceRenderResult,
)
from app.voice.providers import (
    ElevenLabsProvider,
    SilentFallbackProvider,
    VoiceProvider,
    get_voice_provider,
)
from app.voice.renderer import ScriptVoiceRenderer

__all__ = [
    "AudioSegment",
    "RenderedAudio",
    "VoiceConfig",
    "VoiceRenderResult",
    "VoiceProvider",
    "ElevenLabsProvider",
    "SilentFallbackProvider",
    "get_voice_provider",
    "ScriptVoiceRenderer",
]
