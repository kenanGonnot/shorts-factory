"""Unit tests for the visual generation domain."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.chains.state import PipelineState, Script
from app.core.config import Settings
from app.services.storage import LocalStorage
from app.tools.visual_tool import VisualTool
from app.visual.models import ResolvedAsset, VisualAsset, VisualRequest
from app.visual.normalizer import VisualNormalizer
from app.visual.planner import VisualPlanner
from app.visual.providers import (
    FallbackVisualProvider,
    NanoBananaVisualProvider,
    PexelsVisualProvider,
    VisualProviderError,
    _pick_best_portrait_file,
)


# ----- helpers --------------------------------------------------------------


def _script() -> Script:
    return {
        "title": "Why honey never spoils",
        "hook": "Did you know honey lasts forever?",
        "body": "Its low water content stops bacteria.",
        "cta": "Follow for more food facts.",
        "tags": ["food"],
    }


class _FakeProvider:
    """Provider test double — records calls and returns canned assets."""

    def __init__(self, name: str, fail: bool = False, asset_type: str = "image") -> None:
        self.name = name
        self.fail = fail
        self.asset_type = asset_type
        self.calls: list[VisualRequest] = []

    def resolve(self, request: VisualRequest) -> ResolvedAsset:
        self.calls.append(request)
        if self.fail:
            raise VisualProviderError(f"{self.name} down")
        return ResolvedAsset(
            asset_type=self.asset_type,  # type: ignore[arg-type]
            data=FallbackVisualProvider._PNG,
            mime_type="image/png",
            provider=self.name,
        )


class _FakeNormalizer:
    """Stand-in normalizer that skips ffmpeg for fast unit tests."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.calls: list[tuple[VisualRequest, ResolvedAsset]] = []

    def normalize(self, request: VisualRequest, resolved: ResolvedAsset) -> VisualAsset:
        self.calls.append((request, resolved))
        return VisualAsset(
            section=request.section,
            chunk_index=request.chunk_index,
            asset_type=resolved.asset_type,
            provider=resolved.provider,
            path=f"/tmp/{self.job_id}/{request.section}_{request.chunk_index}.mp4",
            start_ms=request.start_ms,
            end_ms=request.end_ms,
            duration_ms=request.duration_ms,
            prompt=request.prompt,
        )


# ----- VisualAsset model ----------------------------------------------------


def test_visual_asset_as_dict_round_trip():
    asset = VisualAsset(
        section="hook",
        chunk_index=0,
        asset_type="clip",
        provider="pexels",
        path="/tmp/x.mp4",
        start_ms=0,
        end_ms=3000,
        duration_ms=3000,
    )
    d = asset.as_dict()
    assert d["section"] == "hook"
    assert d["duration_ms"] == 3000
    assert d["width"] == 1080 and d["height"] == 1920


# ----- Planner --------------------------------------------------------------


def test_planner_uses_audio_segments_for_timing():
    planner = VisualPlanner()
    segments = [
        {"section": "hook", "chunk_index": 0, "text": "Hi.", "duration_ms": 1200},
        {"section": "body", "chunk_index": 0, "text": "Body one.", "duration_ms": 2500},
        {"section": "body", "chunk_index": 1, "text": "Body two.", "duration_ms": 2500},
        {"section": "cta", "chunk_index": 0, "text": "Bye.", "duration_ms": 1000},
    ]
    out = planner.plan(_script(), audio_segments=segments)
    assert [r.section for r in out] == ["hook", "body", "body", "cta"]
    assert [r.chunk_index for r in out] == [0, 0, 1, 0]
    assert out[0].start_ms == 0 and out[0].end_ms == 1200
    assert out[1].start_ms == 1200 and out[1].end_ms == 3700
    assert out[-1].end_ms == 7200


def test_planner_equal_splits_when_segments_missing():
    planner = VisualPlanner()
    out = planner.plan(_script(), audio_segments=None, audio_duration_ms=9000)
    assert len(out) == 3
    assert out[-1].end_ms == 9000  # total preserved exactly
    assert all(r.duration_ms > 0 for r in out)


def test_planner_falls_back_to_default_when_no_timing():
    planner = VisualPlanner(default_segment_ms=2000)
    out = planner.plan(_script())
    assert [r.section for r in out] == ["hook", "body", "cta"]
    assert out[-1].end_ms == 6000


def test_planner_prompts_are_deterministic():
    planner = VisualPlanner()
    a = planner.plan(_script(), audio_duration_ms=6000)
    b = planner.plan(_script(), audio_duration_ms=6000)
    assert [r.prompt for r in a] == [r.prompt for r in b]
    assert [r.query for r in a] == [r.query for r in b]


def test_planner_ignores_malformed_segments():
    planner = VisualPlanner()
    segments = [
        {"section": "hook", "chunk_index": 0, "text": "Hi.", "duration_ms": 0},
        {"section": "unknown", "chunk_index": 0, "text": "x"},
    ]
    out = planner.plan(_script(), audio_segments=segments)
    # Only hook is kept; duration_ms=0 is replaced with the default.
    assert len(out) == 1
    assert out[0].section == "hook"
    assert out[0].duration_ms == VisualPlanner().default_segment_ms


# ----- Providers ------------------------------------------------------------


def test_pick_best_portrait_file_selects_highest_resolution():
    videos = [
        {
            "video_files": [
                {"link": "sd.mp4", "width": 540, "height": 960},
                {"link": "hd.mp4", "width": 1080, "height": 1920},
                {"link": "landscape.mp4", "width": 1920, "height": 1080},
            ]
        }
    ]
    assert _pick_best_portrait_file(videos) == "hd.mp4"


def test_pick_best_portrait_file_returns_none_when_no_portrait():
    assert _pick_best_portrait_file([{"video_files": []}]) is None


def test_pexels_provider_happy_path():
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "videos": [
                    {"video_files": [{"link": "http://v/1.mp4", "width": 1080, "height": 1920}]}
                ]
            }

        content = b"BINARY"

    class FakeClient:
        def __init__(self):
            self.gets: list[tuple] = []

        def get(self, url, params=None, headers=None, timeout=None):  # noqa: ARG002
            self.gets.append((url, params))
            return FakeResp()

    provider = PexelsVisualProvider(api_key="k", client=FakeClient())
    req = VisualRequest("hook", 0, 0, 3000, "prompt", "honey")
    resolved = provider.resolve(req)
    assert resolved.asset_type == "clip"
    assert resolved.data == b"BINARY"
    assert resolved.provider == "pexels"


def test_pexels_provider_empty_results_raises():
    class EmptyResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"videos": []}

    class FakeClient:
        def get(self, *a, **kw):
            return EmptyResp()

    provider = PexelsVisualProvider(api_key="k", client=FakeClient())
    with pytest.raises(VisualProviderError):
        provider.resolve(VisualRequest("hook", 0, 0, 1000, "p", "q"))


def test_pexels_requires_api_key():
    with pytest.raises(ValueError):
        PexelsVisualProvider(api_key="")


def test_nano_banana_provider_uses_injected_client():
    captured: dict = {}

    class FakeGenAI:
        def generate_image(self, prompt: str, model: str) -> bytes:
            captured["prompt"] = prompt
            captured["model"] = model
            return b"PNGBYTES"

    provider = NanoBananaVisualProvider(api_key="", model="gemini-3.1-flash-image", client=FakeGenAI())
    resolved = provider.resolve(VisualRequest("hook", 0, 0, 3000, "a prompt", "q"))
    assert captured == {"prompt": "a prompt", "model": "gemini-3.1-flash-image"}
    assert resolved.data == b"PNGBYTES"
    assert resolved.asset_type == "image"


def test_nano_banana_provider_wraps_errors():
    class FailClient:
        def generate_image(self, prompt: str, model: str) -> bytes:
            raise RuntimeError("boom")

    provider = NanoBananaVisualProvider(api_key="", model="m", client=FailClient())
    with pytest.raises(VisualProviderError):
        provider.resolve(VisualRequest("hook", 0, 0, 1000, "p", "q"))


def test_fallback_provider_always_returns_image():
    provider = FallbackVisualProvider()
    resolved = provider.resolve(VisualRequest("body", 0, 0, 1000, "p", "q"))
    assert resolved.asset_type == "image"
    assert resolved.provider == "fallback"
    assert resolved.data.startswith(b"\x89PNG")


# ----- Normalizer -----------------------------------------------------------


def test_normalizer_renders_still_image_to_clip(tmp_path: Path):
    pytest.importorskip("subprocess")  # always present; placeholder
    storage = LocalStorage(str(tmp_path))
    normalizer = VisualNormalizer(storage=storage, job_id="job-N")
    request = VisualRequest("hook", 0, 0, 500, "prompt", "query")
    resolved = FallbackVisualProvider().resolve(request)
    try:
        asset = normalizer.normalize(request, resolved)
    except FileNotFoundError:
        pytest.skip("ffmpeg not installed")
    assert asset.asset_type == "image"
    assert asset.duration_ms == 500
    assert Path(asset.path).exists()
    assert asset.path.endswith("job-N/visuals/hook_00.mp4")


def test_normalizer_uses_deterministic_storage_keys(tmp_path: Path):
    storage = LocalStorage(str(tmp_path))
    normalizer = VisualNormalizer(storage=storage, job_id="same")
    req = VisualRequest("body", 2, 0, 500, "p", "q")
    assert normalizer._key(req) == "same/visuals/body_02.mp4"


# ----- VisualTool orchestration ---------------------------------------------


def _settings(**overrides) -> Settings:
    base = dict(
        visual_provider="section_map",
        visual_provider_map={"hook": "pexels", "body": "pexels", "cta": "pexels"},
        google_api_key="",
        pexels_api_key="",
    )
    base.update(overrides)
    return Settings(**base)


def test_visual_tool_happy_path_uses_section_provider(tmp_path: Path):
    storage = LocalStorage(str(tmp_path))
    stock = _FakeProvider("pexels", asset_type="clip")
    providers = {"pexels": stock, "fallback": _FakeProvider("fallback")}

    tool = VisualTool(
        planner=VisualPlanner(),
        providers=providers,
        storage=storage,
        settings=_settings(),
    )
    # Inject a fake normalizer by monkey-patching the instance's run flow
    # via swapping storage's behavior: instead, we override the normalizer
    # path by using the real one with ffmpeg — but tests should stay fast.
    # Easiest: patch the VisualNormalizer in the tool module.
    import app.tools.visual_tool as vt_mod

    orig = vt_mod.VisualNormalizer
    vt_mod.VisualNormalizer = lambda storage, job_id: _FakeNormalizer(job_id)  # type: ignore[assignment]
    try:
        state: PipelineState = {
            "job_id": "job-V",
            "topic": "honey",
            "script": _script(),
            "audio_duration_ms": 6000,
        }
        out = tool.run(state)
    finally:
        vt_mod.VisualNormalizer = orig  # type: ignore[assignment]

    assets = out["visual_assets"]
    assert len(assets) == 3
    assert [a["section"] for a in assets] == ["hook", "body", "cta"]
    assert all(a["provider"] == "pexels" for a in assets)
    assert len(stock.calls) == 3


def test_visual_tool_falls_back_when_primary_fails(tmp_path: Path):
    storage = LocalStorage(str(tmp_path))
    broken = _FakeProvider("pexels", fail=True, asset_type="clip")
    fb = _FakeProvider("fallback")
    tool = VisualTool(
        planner=VisualPlanner(),
        providers={"pexels": broken, "fallback": fb},
        storage=storage,
        settings=_settings(),
    )
    import app.tools.visual_tool as vt_mod

    orig = vt_mod.VisualNormalizer
    vt_mod.VisualNormalizer = lambda storage, job_id: _FakeNormalizer(job_id)  # type: ignore[assignment]
    try:
        out = tool.run(
            {"job_id": "j", "topic": "x", "script": _script(), "audio_duration_ms": 3000}
        )
    finally:
        vt_mod.VisualNormalizer = orig  # type: ignore[assignment]

    assert all(a["provider"] == "fallback" for a in out["visual_assets"])
    assert len(broken.calls) == 3 and len(fb.calls) == 3


def test_visual_tool_does_not_mutate_input_state(tmp_path: Path):
    storage = LocalStorage(str(tmp_path))
    tool = VisualTool(
        planner=VisualPlanner(),
        providers={"fallback": _FakeProvider("fallback")},
        storage=storage,
        settings=_settings(
            visual_provider_map={"hook": "fallback", "body": "fallback", "cta": "fallback"}
        ),
    )
    import app.tools.visual_tool as vt_mod

    orig = vt_mod.VisualNormalizer
    vt_mod.VisualNormalizer = lambda storage, job_id: _FakeNormalizer(job_id)  # type: ignore[assignment]
    try:
        state: PipelineState = {
            "job_id": "j2",
            "topic": "x",
            "script": _script(),
            "audio_duration_ms": 3000,
        }
        snapshot = dict(state)
        tool.run(state)
        assert state == snapshot
        assert "visual_assets" not in state
    finally:
        vt_mod.VisualNormalizer = orig  # type: ignore[assignment]
