"""TTS provider abstraction.

A provider takes plain text and returns ``RenderedAudio``. ``VoiceTool``
selects the active provider through :func:`get_voice_provider` so the
pipeline never depends on provider-specific details.
"""
from __future__ import annotations

import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

from app.core.config import Settings, get_settings
from app.voice.models import RenderedAudio, VoiceConfig

ELEVENLABS_PROVIDER = "elevenlabs"
SILENT_PROVIDER = "silent"

# Friendly name → official voice ID for ElevenLabs' default voice library.
# Lets users keep ``ELEVENLABS_VOICE_ID=Rachel`` in .env without looking up
# the underlying hash. Lookup is case-insensitive.
ELEVENLABS_DEFAULT_VOICES: dict[str, str] = {
    "rachel": "21m00Tcm4TlvDq8ikWAM",
    "drew": "29vD33N1CtxCmqQRPOHJ",
    "clyde": "2EiwWnXFnvU5JabPnv8n",
    "paul": "5Q0t7uMcjvnagumLfvZi",
    "domi": "AZnzlk1XvdvUeBnXmlld",
    "dave": "CYw3kZ02Hs0563khs1Fj",
    "fin": "D38z5RcWu1voky8WS1ja",
    "sarah": "EXAVITQu4vr4xnSDxMaL",
    "antoni": "ErXwobaYiN019PkySvjV",
    "thomas": "GBv7mTt0atIp3Br8iCZE",
    "charlie": "IKne3meq5aSn9XLyUdCD",
    "george": "JBFqnCBsd6RMkjVDRZzb",
    "emily": "LcfcDJNUP1GQjkzn1xUU",
    "elli": "MF3mGyEYCl7XYWbV9V6O",
    "callum": "N2lVS1w4EtoT3dr4eOWO",
    "patrick": "ODq5zmih8GrVes37Dizd",
    "harry": "SOYHLrjzK2X1ezoPC6cr",
    "liam": "TX3LPaxmHKxFdv7VOQHJ",
    "dorothy": "ThT5KcBeYPX3keUQqHPh",
    "josh": "TxGEqnHWrfWFTfGW9XjX",
    "arnold": "VR6AewLTigWG4xSOukaG",
    "charlotte": "XB0fDUnXU5powFXDhCwa",
    "matilda": "XrExE9yKIg1WjnnlVkGX",
    "matthew": "Yko7PKHZNXotIFUBG7I9",
    "james": "ZQe5CZNOzWyzPSCn5a3c",
    "joseph": "Zlb1dXrM653N07WRdFW3",
    "jeremy": "bVMeCyTHy58xNoL34h3p",
    "michael": "flq6f7yk4E4fJM5XTYuZ",
    "ethan": "g5CIjZEefAph4nQFvHAz",
    "gigi": "jBpfuIE2acCO8z3wKNLl",
    "freya": "jsCqWAovK2LkecY7zXl4",
    "grace": "oWAxZDx7w5VEj9dCyTzz",
    "daniel": "onwK4e9ZLuTAKqWW03F9",
    "serena": "pMsXgVXv3BLzUgSXRplE",
    "adam": "pNInz6obpgDQGcFmaJgB",
    "nicole": "piTKgcLEGmPE4e6mEKli",
    "bill": "pqHfZKP75CvOlQylNhV4",
    "jessie": "t0jbNlBVZ17f02VDIeMI",
    "sam": "yoZ06aMxZJJ28mfd3POQ",
    "glinda": "z9fAnlkpzviPz146aGWa",
    "giovanni": "zcAOhNBS3c14rBihAFp1",
    "mimi": "zrHiDhphv9ZnVXBqCLjz",
}


def resolve_elevenlabs_voice_id(voice: str) -> str:
    """Return a real ElevenLabs voice ID, mapping friendly names if needed.

    A 20-character alphanumeric token is treated as an actual voice ID and
    returned as-is. Otherwise the lookup falls back to the default-voice
    table; an unknown name is returned unchanged so the API can produce a
    clear error message.
    """
    candidate = (voice or "").strip()
    if len(candidate) == 20 and candidate.isalnum():
        return candidate
    return ELEVENLABS_DEFAULT_VOICES.get(candidate.lower(), candidate)


class VoiceProvider(ABC):
    """Minimum interface every TTS backend must implement."""

    name: str
    config: VoiceConfig

    @abstractmethod
    def synthesize(self, text: str) -> RenderedAudio:
        """Synthesize ``text`` and return raw audio bytes."""


class ElevenLabsProvider(VoiceProvider):
    """ElevenLabs HTTP TTS provider."""

    name = ELEVENLABS_PROVIDER

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str = "eleven_turbo_v2",
        timeout: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("ElevenLabsProvider requires a non-empty api_key")
        self._api_key = api_key
        self._timeout = timeout
        self._client = client
        resolved_id = resolve_elevenlabs_voice_id(voice_id)
        self.config = VoiceConfig(provider=self.name, voice_id=resolved_id, model_id=model_id)

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def synthesize(self, text: str) -> RenderedAudio:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.config.voice_id}"
        response = self._http().post(
            url,
            headers={"xi-api-key": self._api_key, "accept": "audio/mpeg"},
            json={"text": text, "model_id": self.config.model_id},
        )
        response.raise_for_status()
        return RenderedAudio(audio=response.content, mime_type="audio/mpeg")


class SilentFallbackProvider(VoiceProvider):
    """Generates short silent MP3 chunks via ffmpeg.

    Keeps the pipeline runnable end-to-end when no TTS credentials are
    configured. Duration is a deterministic function of text length so that
    tests and downstream stages observe predictable behavior.
    """

    name = SILENT_PROVIDER

    def __init__(self, voice_id: str = "silent", seconds_per_chunk: float | None = None) -> None:
        self._fixed_seconds = seconds_per_chunk
        self.config = VoiceConfig(provider=self.name, voice_id=voice_id, model_id=None)

    def _seconds_for(self, text: str) -> float:
        if self._fixed_seconds is not None:
            return self._fixed_seconds
        # ~3 words/second is a comfortable narration baseline; clamp to a
        # safe range so empty/huge inputs still produce a valid file.
        words = max(1, len(text.split()))
        return max(1.0, min(30.0, words / 3.0))

    def synthesize(self, text: str) -> RenderedAudio:
        seconds = self._seconds_for(text)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as fh:
            tmp_path = Path(fh.name)
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-f", "lavfi",
                    "-i", "anullsrc=r=44100:cl=mono",
                    "-t", f"{seconds:.2f}", "-q:a", "9", str(tmp_path),
                ],
                check=True,
                capture_output=True,
            )
            audio = tmp_path.read_bytes()
        finally:
            tmp_path.unlink(missing_ok=True)
        return RenderedAudio(
            audio=audio,
            mime_type="audio/mpeg",
            duration_ms=int(seconds * 1000),
        )


def get_voice_provider(settings: Settings | None = None) -> VoiceProvider:
    """Return the active voice provider based on configuration.

    Selection is fully configuration-driven:

    - ``voice_provider="elevenlabs"`` requires ``ELEVENLABS_API_KEY``.
    - ``voice_provider="silent"`` always uses the silent fallback.
    - ``voice_provider="auto"`` (default) picks ElevenLabs if a key is
      present, otherwise the silent fallback.
    """
    s = settings or get_settings()
    requested = (s.voice_provider or "auto").lower()
    has_key = bool(s.elevenlabs_api_key)

    if requested == SILENT_PROVIDER:
        return SilentFallbackProvider()
    if requested == ELEVENLABS_PROVIDER:
        return ElevenLabsProvider(
            api_key=s.elevenlabs_api_key,
            voice_id=s.elevenlabs_voice_id,
            model_id=s.elevenlabs_model,
        )
    if requested == "auto":
        if has_key:
            return ElevenLabsProvider(
                api_key=s.elevenlabs_api_key,
                voice_id=s.elevenlabs_voice_id,
                model_id=s.elevenlabs_model,
            )
        return SilentFallbackProvider()
    raise ValueError(f"Unknown voice_provider: {requested!r}")
