"""PublishingTool demo in deterministic dry-run mode.

Run from the project root::

    python examples/publishing_tool_example.py

The example:
    1. creates a stub final asset under ``examples/output/``
    2. builds a minimal ``PipelineState`` with publishable script metadata
    3. invokes ``PublishingTool`` with explicit dry-run settings
    4. prints the deterministic ``youtube_id`` returned by the tool
"""
from __future__ import annotations

from pathlib import Path

from app.chains.state import PipelineState
from app.core.config import Settings
from app.tools.publish_tool import PublishingTool


def main() -> None:
    out_dir = Path(__file__).resolve().parent / "output" / "publishing_tool_demo"
    out_dir.mkdir(parents=True, exist_ok=True)

    final_path = out_dir / "final.mp4"
    final_path.write_bytes(b"\x00" * 128)

    state: PipelineState = {
        "job_id": "publish_demo",
        "topic": "typed python",
        "final_path": str(final_path),
        "script": {
            "title": "Why typed Python refactors faster",
            "hook": "Type hints catch problems before your tests do.",
            "body": (
                "They document intent, improve editor feedback, and make larger "
                "changes easier to trust."
            ),
            "cta": "Follow for more Python architecture tips.",
            "tags": ["python", "typing", "refactoring"],
        },
    }

    settings = Settings(
        youtube_client_secrets_file="",
        youtube_token_file="",
        youtube_privacy="private",
    )
    tool = PublishingTool(settings=settings)
    result = tool.run(state)

    print("PublishingTool dry-run completed.")
    print(f"    final_path : {result['final_path']}")
    print(f"    youtube_id : {result['youtube_id']}")
    print("    expected   : dryrun-publish_demo")


if __name__ == "__main__":
    main()
