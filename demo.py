#!/usr/bin/env python
"""End-to-end demo: Topic Input -> Subtitle Generation.

Runs the real Shorts Factory pipeline on the host, skipping the
publishing stage, and prompts the user for a topic interactively.

Chain executed:

    topic -> ScriptChain -> VoiceTool -> VisualTool
          -> VideoAssemblyTool -> SubtitleTool

Any API keys declared in ``.env`` are used as-is. Missing keys simply
degrade the corresponding stage (silent audio, offline visuals, etc.).

Usage:

    python demo.py

Requirements:
    - ffmpeg on PATH
    - dependencies installed (``pip install -e ".[dev]"``)
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

# Ensure the project root is on sys.path when running directly.
_PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Environment overrides -- the committed .env targets the Docker container
# (``/app/storage``), which is not writable on the host. Redirect to a
# project-local folder before any Settings instance is built.
# ---------------------------------------------------------------------------
_current_storage_dir = os.environ.get("STORAGE_LOCAL_DIR", "")
if not _current_storage_dir or _current_storage_dir.startswith("/app"):
    os.environ["STORAGE_LOCAL_DIR"] = str(_PROJECT_ROOT / "storage")
os.environ.setdefault("STORAGE_BACKEND", "local")

from langchain_core.runnables import Runnable  # noqa: E402

from app.chains.script_chain import build_script_chain  # noqa: E402
from app.chains.state import PipelineState  # noqa: E402
from app.core.logging import log, setup_logging  # noqa: E402
from app.tools.subtitle_tool import SubtitleTool  # noqa: E402
from app.tools.video_tool import VideoAssemblyTool  # noqa: E402
from app.tools.visual_tool import VisualTool  # noqa: E402
from app.tools.voice_tool import VoiceTool  # noqa: E402


def build_demo_pipeline() -> Runnable:
    """LCEL sub-pipeline stopping at SubtitleTool (no publishing)."""
    return (
        build_script_chain()
        | VoiceTool()
        | VisualTool()
        | VideoAssemblyTool()
        | SubtitleTool()
    )


def prompt_topic() -> str:
    print()
    print("=" * 72)
    print("  Shorts Factory - End-to-end demo (topic -> subtitles)")
    print("=" * 72)
    print()
    print("Enter a topic for your short. Example: '3 surprising facts about")
    print("octopuses' / 'Pourquoi le cafe aide a se concentrer'.")
    print()
    while True:
        try:
            topic = input("Topic > ").strip()
        except EOFError:
            raise SystemExit("no topic provided, aborting")
        if topic:
            return topic
        print("  (topic cannot be empty - please try again)")


def summarize(state: PipelineState) -> None:
    script = state.get("script") or {}
    print()
    print("-" * 72)
    print("  Pipeline finished")
    print("-" * 72)
    print(f"  job_id         : {state.get('job_id')}")
    print(f"  topic          : {state.get('topic')}")
    print(f"  script.title   : {script.get('title')}")
    print(f"  script.hook    : {script.get('hook')}")
    print(f"  voice_provider : {state.get('voice_provider')}")
    print(f"  voice_id       : {state.get('voice_id')}")
    print(f"  audio_path     : {state.get('audio_path')}")
    print(f"  duration (ms)  : {state.get('audio_duration_ms')}")
    visuals = state.get("visual_assets") or []
    print(f"  visual_assets  : {len(visuals)} clip(s)")
    print(f"  video_path     : {state.get('video_path')}")
    print(f"  subtitle_path  : {state.get('subtitle_path')}")
    print(f"  final_path     : {state.get('final_path')}")
    print()


def main() -> int:
    setup_logging()
    topic = prompt_topic()

    job_id = f"demo-{uuid.uuid4().hex[:8]}"
    initial_state: PipelineState = {"job_id": job_id, "topic": topic}

    log.info("demo.start", job_id=job_id, topic=topic)
    pipeline = build_demo_pipeline()

    try:
        final_state = pipeline.invoke(initial_state)
    except Exception as exc:  # noqa: BLE001
        log.error("demo.failed", job_id=job_id, error=str(exc))
        print()
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 1

    log.info(
        "demo.done",
        job_id=job_id,
        subtitle_path=final_state.get("subtitle_path"),
        final_path=final_state.get("final_path"),
    )
    summarize(final_state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
