"""OpenAI / Azure OpenAI Whisper transcription provider."""
from __future__ import annotations

import re
from pathlib import Path

from openai import AsyncAzureOpenAI

from oki.config import Settings
from oki.providers.factory import create_openai_client


class OpenAITranscriptionClient:
    """Transcribe audio/video via OpenAI Whisper or Azure OpenAI Whisper."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()
        self._client = create_openai_client(self._settings)
        self._deployment = self._settings.azure_whisper_deployment

    async def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
        prompt: str | None = None,
        response_format: str = "verbose_json",
        duration_seconds: float = 0.0,
    ) -> dict:
        """Send audio file to Whisper and return segment-level transcription."""
        if self._client is None:
            raise RuntimeError(
                "No OpenAI/Azure API configured. "
                "Set OKI_OPENAI_API_KEY, OKI_AZURE_OPENAI_ENDPOINT, "
                "or OKI_OPENAI_BASE_URL."
            )

        model = self._deployment if isinstance(self._client, AsyncAzureOpenAI) else "whisper-1"

        # Try verbose_json first (gives segments + timestamps)
        result = await self._call_whisper(
            audio_path, model, response_format="verbose_json",
            language=language, prompt=prompt,
        )
        if result is not None:
            return self._parse_segments(result, language)

        # Fallback to json (gives text only, no timestamps)
        print("[Transcription] verbose_json not supported, falling back to json...")
        result = await self._call_whisper(
            audio_path, model, response_format="json",
            language=language, prompt=prompt,
        )
        if result is not None:
            text = getattr(result, "text", "")
            return self._split_into_segments(text, duration_seconds, language)

        raise RuntimeError("Transcription failed for all supported formats.")

    async def _call_whisper(
        self,
        audio_path: Path,
        model: str,
        response_format: str,
        language: str | None = None,
        prompt: str | None = None,
    ) -> object | None:
        """Call Whisper API; return None on format error so caller can retry."""
        try:
            with open(audio_path, "rb") as f:
                kwargs: dict = {"model": model, "file": f, "response_format": response_format}
                if language:
                    kwargs["language"] = language
                if prompt:
                    kwargs["prompt"] = prompt
                return await self._client.audio.transcriptions.create(**kwargs)  # type: ignore[arg-type]
        except Exception as exc:
            msg = str(exc)
            if "verbose_json" in msg and "not compatible" in msg:
                return None
            if "unsupported_value" in msg:
                return None
            raise

    def _parse_segments(self, transcription: object, language: str | None) -> dict:
        """Parse verbose_json response into segments."""
        result: dict = {"segments": [], "language": language or "auto", "text": ""}
        if hasattr(transcription, "text"):
            result["text"] = transcription.text
        data = transcription.model_dump() if hasattr(transcription, "model_dump") else {}
        for idx, seg in enumerate(data.get("segments", [])):
            result["segments"].append(
                {
                    "id": seg.get("id", idx),
                    "start": seg.get("start", 0.0),
                    "end": seg.get("end", 0.0),
                    "text": seg.get("text", ""),
                }
            )
        return result

    def _split_into_segments(
        self, text: str, duration_seconds: float, language: str | None
    ) -> dict:
        """Split full text into sentence-based segments with estimated timestamps."""
        # Split by sentence boundaries (. ! ?)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        if not sentences:
            return {"segments": [], "language": language or "auto", "text": text}

        total_chars = sum(len(s) for s in sentences)
        segments: list[dict] = []
        current_time = 0.0
        for idx, sentence in enumerate(sentences):
            # Estimate duration proportional to character count
            seg_duration = (len(sentence) / total_chars) * duration_seconds if total_chars > 0 else 5.0
            end_time = min(current_time + seg_duration, duration_seconds)
            segments.append(
                {
                    "id": idx,
                    "start": round(current_time, 2),
                    "end": round(end_time, 2),
                    "text": sentence,
                }
            )
            current_time = end_time

        return {"segments": segments, "language": language or "auto", "text": text}
