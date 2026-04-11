"""Visual provider abstraction and concrete implementations.

Providers turn one :class:`VisualRequest` into one :class:`ResolvedAsset`
(raw bytes + MIME). They must not touch storage or ffmpeg — that is the
normalizer's job. Network calls live behind lazily-injectable clients so
tests can run offline.
"""
from __future__ import annotations

import base64
import struct
import zlib
from typing import Protocol, runtime_checkable

import httpx

from app.core.config import Settings
from app.core.logging import log
from app.visual.models import ResolvedAsset, VisualRequest


def _build_solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """Build a valid solid-color RGB PNG from scratch using stdlib zlib.

    Used by :class:`FallbackVisualProvider` so the fallback path has no
    third-party image dependency and cannot silently ship malformed data.
    """
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    raw = b""
    row = bytes(rgb) * width
    for _ in range(height):
        raw += b"\x00" + row  # filter byte 0 (None)
    idat = zlib.compress(raw, 9)
    return signature + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


class VisualProviderError(Exception):
    """Raised when a provider cannot resolve a request.

    Orchestration code catches this to route to the fallback provider.
    """


@runtime_checkable
class VisualProvider(Protocol):
    name: str

    def resolve(self, request: VisualRequest) -> ResolvedAsset: ...


# ----------------------------------------------------------------------
# Pexels (stock video)
# ----------------------------------------------------------------------


class PexelsVisualProvider:
    """Portrait stock-video provider backed by the Pexels API."""

    name = "pexels"

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        if not api_key:
            raise ValueError("PexelsVisualProvider requires a non-empty api_key")
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=60)

    def resolve(self, request: VisualRequest) -> ResolvedAsset:
        try:
            r = self._client.get(
                "https://api.pexels.com/videos/search",
                params={
                    "query": request.query,
                    "orientation": "portrait",
                    "per_page": 5,
                },
                headers={"Authorization": self._api_key},
            )
            r.raise_for_status()
            videos = r.json().get("videos") or []
        except Exception as exc:  # noqa: BLE001
            raise VisualProviderError(f"pexels search failed: {exc}") from exc

        file_url = _pick_best_portrait_file(videos)
        if not file_url:
            raise VisualProviderError(f"pexels: no portrait video for {request.query!r}")

        try:
            data = self._client.get(file_url, timeout=120).content
        except Exception as exc:  # noqa: BLE001
            raise VisualProviderError(f"pexels download failed: {exc}") from exc

        return ResolvedAsset(
            asset_type="clip",
            data=data,
            mime_type="video/mp4",
            provider=self.name,
            source_url=file_url,
        )


def _pick_best_portrait_file(videos: list[dict]) -> str | None:
    """Deterministically pick a portrait file from Pexels search results.

    Prefers the first video's highest-resolution portrait file — this is
    stable across runs for the same query and avoids the previous
    "always pick index 0" heuristic.
    """
    for video in videos:
        portrait_files = [
            f
            for f in video.get("video_files", [])
            if int(f.get("height") or 0) >= int(f.get("width") or 0)
            and f.get("link")
        ]
        if not portrait_files:
            continue
        portrait_files.sort(key=lambda f: int(f.get("height") or 0), reverse=True)
        return portrait_files[0]["link"]
    return None


# ----------------------------------------------------------------------
# Nano Banana 2 (Gemini 3.1 Flash Image)
# ----------------------------------------------------------------------


class NanoBananaVisualProvider:
    """Generated still-image provider using Google's Gemini Flash Image.

    The ``client`` parameter accepts any object exposing a
    ``generate_image(prompt: str, model: str) -> bytes`` method so tests
    can inject fakes without importing ``google-genai``.
    """

    name = "nano_banana"

    def __init__(
        self,
        api_key: str,
        model: str,
        client: object | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not api_key and client is None:
            raise ValueError("NanoBananaVisualProvider requires api_key or injected client")
        self._api_key = api_key
        self._model = model
        self._client = client
        self._http = http_client

    def _get_client(self):
        if self._client is not None:
            return self._client
        # Default adapter talks to the Gemini Developer REST API directly
        # via httpx (already a project dep). Avoids a hard dependency on
        # ``google-genai`` while keeping the injectable-client seam used
        # by unit tests.
        http = self._http or httpx.Client(timeout=120)
        api_key = self._api_key

        class _RestAdapter:
            def generate_image(self, prompt: str, model: str) -> bytes:
                url = (
                    "https://generativelanguage.googleapis.com/v1beta/"
                    f"models/{model}:generateContent"
                )
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseModalities": ["IMAGE"],
                        "imageConfig": {"aspectRatio": "9:16"},
                    },
                }
                try:
                    r = http.post(
                        url,
                        headers={
                            "x-goog-api-key": api_key,
                            "content-type": "application/json",
                        },
                        json=payload,
                    )
                    r.raise_for_status()
                    data = r.json()
                except httpx.HTTPStatusError as exc:
                    raise VisualProviderError(
                        f"gemini HTTP {exc.response.status_code}: "
                        f"{exc.response.text[:300]}"
                    ) from exc
                except Exception as exc:  # noqa: BLE001
                    raise VisualProviderError(f"gemini request failed: {exc}") from exc

                for cand in data.get("candidates") or []:
                    parts = (cand.get("content") or {}).get("parts") or []
                    for part in parts:
                        inline = part.get("inlineData") or part.get("inline_data")
                        if inline and inline.get("data"):
                            return base64.b64decode(inline["data"])
                raise VisualProviderError("gemini returned no inline image data")

        self._client = _RestAdapter()
        return self._client

    def resolve(self, request: VisualRequest) -> ResolvedAsset:
        try:
            data = self._get_client().generate_image(request.prompt, self._model)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            raise VisualProviderError(f"nano_banana generation failed: {exc}") from exc
        if not data:
            raise VisualProviderError("nano_banana returned empty image bytes")
        return ResolvedAsset(
            asset_type="image",
            data=data,
            mime_type="image/png",
            provider=self.name,
        )


# ----------------------------------------------------------------------
# Deterministic fallback
# ----------------------------------------------------------------------


class FallbackVisualProvider:
    """Offline, dependency-free fallback provider.

    Always returns a tiny PNG marker (a 1x1 PNG) as an ``image`` asset.
    The normalizer will turn it into a solid-color vertical clip via
    ffmpeg using ``duration_ms`` from the request.
    """

    name = "fallback"

    # 16x16 opaque dark-gray PNG, built once at import time with stdlib
    # zlib. Hand-rolled to avoid a Pillow dependency for the fallback.
    _PNG = _build_solid_png(16, 16, (16, 24, 32))

    def resolve(self, request: VisualRequest) -> ResolvedAsset:  # noqa: ARG002
        return ResolvedAsset(
            asset_type="image",
            data=self._PNG,
            mime_type="image/png",
            provider=self.name,
        )


# ----------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------


def build_providers(settings: Settings) -> dict[str, VisualProvider]:
    """Build a registry of available providers from settings.

    Unavailable providers (missing credentials) are silently skipped;
    orchestration always keeps ``fallback`` as a last resort.
    """
    providers: dict[str, VisualProvider] = {"fallback": FallbackVisualProvider()}
    if settings.pexels_api_key:
        providers["pexels"] = PexelsVisualProvider(api_key=settings.pexels_api_key)
    nb_api_key = settings.nano_banana_api_key or settings.google_api_key
    nb_model = settings.nano_banana_model or settings.visual_ai_model
    if nb_api_key:
        try:
            providers["nano_banana"] = NanoBananaVisualProvider(
                api_key=nb_api_key,
                model=nb_model,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("visual.provider.nano_banana.disabled", error=str(exc))
    return providers
