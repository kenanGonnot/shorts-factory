"""Example usage for the structured script-generation module.

Run from the repository root:

    .venv/bin/python examples/script_generator_example.py --topic "Why coffee makes you focus"

With an OpenAI key configured, the example uses the structured-output LLM path.
Without one, it demonstrates the deterministic fallback behavior.
"""
from __future__ import annotations

import argparse
import json

from app.chains.script_chain import build_script_chain
from app.chains.script_generator import ScriptGenerator
from app.core.logging import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a Shorts script example.")
    parser.add_argument(
        "--topic",
        default="Why coffee makes you focus",
        help="Topic to turn into a structured short-form video script.",
    )
    parser.add_argument(
        "--mode",
        choices=("generator", "runnable", "both"),
        default="both",
        help="Choose direct generator usage, the Runnable adapter, or both.",
    )
    return parser.parse_args()


def print_section(title: str, payload: dict) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main() -> None:
    args = parse_args()
    setup_logging()

    if args.mode in {"generator", "both"}:
        script = ScriptGenerator().generate_script(args.topic)
        print_section("Direct ScriptGenerator.generate_script()", script)

    if args.mode in {"runnable", "both"}:
        state = build_script_chain().invoke({"job_id": "example-job", "topic": args.topic})
        print_section("Runnable build_script_chain().invoke()", state)


if __name__ == "__main__":
    main()
