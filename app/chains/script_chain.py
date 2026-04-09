"""LCEL entry point for structured script generation."""
from __future__ import annotations

from langchain_core.runnables import Runnable

from app.chains.script_generator import ScriptGenerator


def build_script_chain() -> Runnable:
    return ScriptGenerator().as_runnable()
