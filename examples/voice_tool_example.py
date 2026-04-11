"""End-to-end example of the refactored voice generation module.

Uses the configured TTS provider (ElevenLabs by default when
``ELEVENLABS_API_KEY`` is set in ``.env``) and writes the rendered audio
plus segment metadata into ``examples/output/``.

Run with::

    uv run python examples/voice_tool_example.py
"""
from __future__ import annotations

import json
from pathlib import Path

from app.chains.state import PipelineState, Script
from app.core.config import get_settings
from app.services.storage import LocalStorage
from app.tools.voice_tool import VoiceTool
from app.voice.providers import get_voice_provider

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def main() -> None:
    script: Script = {
        "title": "Why typing matters",
        "hook": "Types catch bugs you would never see in tests!",
        "body": (
            "Static types document intent. They help refactors. "
            "They also make IDEs much smarter about your code."
        ),
        "cta": "Follow for more Python tips.",
        "tags": ["python", "typing"],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    storage = LocalStorage(str(OUTPUT_DIR))
    provider = get_voice_provider(get_settings())
    tool = VoiceTool(provider=provider, storage=storage)

    print(f"Using provider: {provider.config.provider} (voice={provider.config.voice_id})")

    state: PipelineState = {"job_id": "voice_demo", "topic": "typing", "script": script}
    out = tool.run(state)

    print("audio_path        :", out["audio_path"])
    print("audio_segments    :", len(out["audio_segments"]), "segments")
    print("voice_provider    :", out["voice_provider"])
    print("voice_id          :", out["voice_id"])
    print("audio_duration_ms :", out.get("audio_duration_ms"))

    meta_path = Path(out["audio_segments_path"])
    print("\nPersisted segment metadata:")
    print(json.dumps(json.loads(meta_path.read_text()), indent=2))


if __name__ == "__main__":
    main()
