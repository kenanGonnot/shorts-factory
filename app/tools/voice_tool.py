"""TTS tool. Default: ElevenLabs HTTP. Falls back to silent wav in dev."""
from __future__ import annotations
import httpx

from app.core.config import get_settings
from app.services.storage import get_storage
from app.chains.state import PipelineState
from app.tools.base import PipelineTool


class VoiceTool(PipelineTool):
    name = "VoiceTool"

    def run(self, state: PipelineState) -> PipelineState:
        s = get_settings()
        script = state["script"]
        text = f"{script['hook']}. {script['body']} {script['cta']}"
        storage = get_storage()
        key = f"{state['job_id']}/voice.mp3"

        if s.elevenlabs_api_key:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{s.elevenlabs_voice_id}"
            r = httpx.post(
                url,
                headers={"xi-api-key": s.elevenlabs_api_key, "accept": "audio/mpeg"},
                json={"text": text, "model_id": "eleven_turbo_v2"},
                timeout=120,
            )
            r.raise_for_status()
            audio = r.content
        else:
            # silent placeholder mp3 — keeps the pipeline runnable end-to-end in dev
            audio = _silent_mp3()

        path = storage.save(key, audio)
        return {**state, "audio_path": path}


def _silent_mp3() -> bytes:
    # 1 second of silence — minimal valid MP3 frame sequence
    # In dev we just use ffmpeg to synthesize silence if available.
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
             "-t", "10", "-q:a", "9", f.name],
            check=True, capture_output=True,
        )
        return open(f.name, "rb").read()
