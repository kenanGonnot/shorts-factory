"""Visual pipeline stage.

:class:`VisualTool` is a thin orchestrator that delegates to:

1. :class:`VisualPlanner` — script + voice timing → visual requests
2. a registry of :class:`VisualProvider` — request → raw asset
3. :class:`VisualNormalizer` — raw asset → assembly-ready clip

It always succeeds: unavailable providers, empty results, or network
errors transparently route to the deterministic fallback provider.
"""
from __future__ import annotations

from app.chains.state import PipelineState
from app.core.config import Settings, get_settings
from app.core.logging import log
from app.services.storage import Storage, get_storage
from app.tools.base import PipelineTool
from app.visual.models import VisualAsset, VisualRequest, VisualSection
from app.visual.normalizer import VisualNormalizer
from app.visual.planner import VisualPlanner
from app.visual.providers import (
    VisualProvider,
    VisualProviderError,
    build_providers,
)


class VisualTool(PipelineTool):
    name = "VisualTool"

    def __init__(
        self,
        planner: VisualPlanner | None = None,
        providers: dict[str, VisualProvider] | None = None,
        storage: Storage | None = None,
        settings: Settings | None = None,
    ) -> None:
        # Dependencies are resolved lazily at run() so instantiation has
        # no network or storage side effects — mirrors VoiceTool style.
        self._planner = planner
        self._providers = providers
        self._storage = storage
        self._settings = settings

    def run(self, state: PipelineState) -> PipelineState:
        settings = self._settings or get_settings()
        planner = self._planner or VisualPlanner()
        providers = self._providers or build_providers(settings)
        storage = self._storage or get_storage()

        job_id = state["job_id"]
        normalizer = VisualNormalizer(storage=storage, job_id=job_id)

        requests = planner.plan(
            script=state["script"],
            audio_segments=state.get("audio_segments"),
            audio_duration_ms=state.get("audio_duration_ms"),
        )

        assets: list[VisualAsset] = []
        for request in requests:
            resolved = _resolve_with_fallback(request, providers, settings)
            asset = normalizer.normalize(request, resolved)
            assets.append(asset)
            log.info(
                "visual.asset.ready",
                job_id=job_id,
                section=asset.section,
                chunk_index=asset.chunk_index,
                provider=asset.provider,
                asset_type=asset.asset_type,
                duration_ms=asset.duration_ms,
            )

        return {**state, "visual_assets": [a.as_dict() for a in assets]}


# ----------------------------------------------------------------------
# Provider selection + fallback chain
# ----------------------------------------------------------------------


def _resolve_with_fallback(
    request: VisualRequest,
    providers: dict[str, VisualProvider],
    settings: Settings,
):
    """Try the section's primary provider, then fallback.

    The chain is: primary-by-strategy → ``fallback``. The fallback
    provider is guaranteed to be present in the registry and is itself
    dependency-free.
    """
    primary_name = _primary_provider_name(request.section, settings)
    chain: list[str] = []
    if primary_name and primary_name in providers:
        chain.append(primary_name)
    if "fallback" not in chain:
        chain.append("fallback")

    last_error: Exception | None = None
    for name in chain:
        provider = providers.get(name)
        if provider is None:
            continue
        try:
            return provider.resolve(request)
        except VisualProviderError as exc:
            last_error = exc
            log.warning(
                "visual.provider.failed",
                provider=name,
                section=request.section,
                error=str(exc),
            )
            continue

    # The fallback provider never raises, so reaching here is a bug.
    raise RuntimeError(
        f"visual pipeline exhausted all providers: {last_error}"
    )  # pragma: no cover


def _primary_provider_name(section: VisualSection, settings: Settings) -> str | None:
    strategy = settings.visual_provider
    if strategy == "section_map":
        return settings.visual_provider_map.get(section)
    if strategy in {"pexels", "nano_banana", "fallback"}:
        return strategy
    return None
