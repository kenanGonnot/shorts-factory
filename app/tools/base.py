"""Common base for pipeline tools.

Each tool is a LangChain Runnable that takes PipelineState and returns
PipelineState. We subclass Runnable directly so they compose with `|`.
"""
from __future__ import annotations
from abc import abstractmethod
from typing import Any
from langchain_core.runnables import Runnable
from langchain_core.runnables.config import RunnableConfig

from app.chains.state import PipelineState
from app.core.logging import log


class PipelineTool(Runnable[PipelineState, PipelineState]):
    name: str = "PipelineTool"

    @abstractmethod
    def run(self, state: PipelineState) -> PipelineState: ...

    def invoke(
        self, input: PipelineState, config: RunnableConfig | None = None, **kwargs: Any
    ) -> PipelineState:
        log.info("tool.start", tool=self.name, job_id=input.get("job_id"))
        try:
            out = self.run(input)
        except Exception as e:
            log.exception("tool.error", tool=self.name, error=str(e))
            raise
        log.info("tool.end", tool=self.name, job_id=input.get("job_id"))
        return out
