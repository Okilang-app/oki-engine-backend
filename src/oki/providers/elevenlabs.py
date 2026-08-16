"""ElevenLabs text-to-speech provider."""
from __future__ import annotations

import httpx

from oki.config import Settings


class ElevenLabsClient:
    """Generate speech via ElevenLabs API."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()
        self._base = self._settings.elevenlabs_base_url.rstrip("/")
        self._key = self._settings.elevenlabs_api_key

    async def synthesize(
        self,
        text: str,
        voice_profile_id: str = "21m00Tcm4TlvDq8ikWAM",  # default "Rachel"
        language_code: str | None = None,
        ssml: str | None = None,
        model_id: str = "eleven_multilingual_v2",
    ) -> bytes:
        """Generate audio bytes from text via ElevenLabs TTS."""
        if not self._key:
            raise RuntimeError(
                "ElevenLabs API key not configured. Set OKI_ELEVENLABS_API_KEY."
            )

        payload: dict = {
            "text": ssml or text,
            "model_id": model_id,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        if language_code:
            payload["language_code"] = language_code

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base}/v1/text-to-speech/{voice_profile_id}",
                headers={
                    "xi-api-key": self._key,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            return response.content

    async def list_voices(self) -> list[dict]:
        """Return available ElevenLabs voices."""
        if not self._key:
            return []

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base}/v1/voices",
                headers={"xi-api-key": self._key},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("voices", [])
