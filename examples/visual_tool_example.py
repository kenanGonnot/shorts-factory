"""End-to-end voice_demo of the Visual Agent pipeline stage against the real
Nano Banana (Gemini Flash Image) API.

Loads credentials from ``.env`` via :class:`Settings`:

- ``NANO_BANANA_API_KEY`` / ``NANO_BANANA_MODEL`` drive
  :class:`NanoBananaVisualProvider` (used for ``hook`` and ``cta``).
- ``PEXELS_API_KEY`` drives :class:`PexelsVisualProvider` when set;
  otherwise ``body`` sections fall through to the deterministic
  :class:`FallbackVisualProvider`.

Resolved assets are normalized by the real ffmpeg pipeline into
1080x1920 H.264 ``.mp4`` clips under
``examples/output/visual_demo/voice_demo/visuals/``.

Run::

    python examples/visual_tool_example.py
"""
from __future__ import annotations

from pathlib import Path

from app.chains.state import PipelineState, Script
from app.core.config import Settings
from app.services.storage import LocalStorage
from app.tools.visual_tool import VisualTool
from app.visual.providers import build_providers


def main() -> None:
    out_dir = Path(__file__).parent / "output" / "visual_demo"
    storage = LocalStorage(str(out_dir))

    script: Script = {
        "title": "Why honey never spoils",
        "hook": "Did you know honey lasts forever?",
        "body": "Honey has very low water content and high acidity.",
        "cta": "Follow for more food facts!",
        "tags": ["food", "science"],
    }
    audio_segments = [
        {"section": "hook", "chunk_index": 0, "text": script["hook"], "duration_ms": 2000},
        {"section": "body", "chunk_index": 0, "text": "Honey low water.", "duration_ms": 2500},
        {"section": "body", "chunk_index": 1, "text": "High acidity.", "duration_ms": 2500},
        {"section": "cta", "chunk_index": 0, "text": script["cta"], "duration_ms": 1500},
    ]

    # Read everything from .env (NANO_BANANA_API_KEY / NANO_BANANA_MODEL
    # / PEXELS_API_KEY / ...). Fresh Settings instance — avoids the
    # ``get_settings`` lru_cache if the env has been mutated.
    settings = Settings(
        visual_provider="section_map",
        visual_provider_map={
            "hook": "nano_banana",
            "body": "pexels",
            "cta": "nano_banana",
        },
    )

    providers = build_providers(settings)
    print("Active providers:", sorted(providers))
    if "nano_banana" not in providers:
        raise SystemExit(
            "nano_banana provider not configured — set NANO_BANANA_API_KEY in .env"
        )

    tool = VisualTool(providers=providers, storage=storage, settings=settings)
    state: PipelineState = {
        "job_id": "voice_demo",
        "topic": "honey",
        "script": script,
        "audio_segments": audio_segments,
        "audio_duration_ms": 8500,
    }
    out = tool.run(state)

    print(f"Rendered {len(out['visual_assets'])} visual assets:")
    for a in out["visual_assets"]:
        print(
            f"  [{a['section']}#{a['chunk_index']}] "
            f"{a['provider']:<11} {a['duration_ms']:>5}ms  {a['path']}"
        )


if __name__ == "__main__":
    main()
