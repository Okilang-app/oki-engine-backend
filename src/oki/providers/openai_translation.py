"""OpenAI / Azure OpenAI translation provider."""
from __future__ import annotations

from oki.config import Settings
from oki.providers.factory import create_openai_client


SYSTEM_PROMPT = (
    "You are a professional video localization translator. "
    "Translate the user's text faithfully into the target language, "
    "preserving meaning, tone, and length. "
    "Return ONLY the translated text, no explanations."
)


class OpenAITranslationClient:
    """Translate text via OpenAI GPT or Azure OpenAI GPT."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()
        self._client = create_openai_client(self._settings)
        self._deployment = self._settings.azure_gpt_deployment

    async def translate(
        self,
        text: str,
        target_language: str = "es",
        source_language: str | None = None,
        glossary: dict[str, str] | None = None,
    ) -> dict:
        """Send text to GPT for translation."""
        if self._client is None:
            raise RuntimeError(
                "No OpenAI/Azure API configured. "
                "Set OKI_OPENAI_API_KEY, OKI_AZURE_OPENAI_ENDPOINT, "
                "or OKI_OPENAI_BASE_URL."
            )

        user_prompt = f"Translate to {target_language}:\n\n```\n{text}\n```"
        if glossary:
            glossary_lines = "\n".join(f"{k}: {v}" for k, v in glossary.items())
            user_prompt += f"\n\nUse this glossary:\n{glossary_lines}"
        if source_language:
            user_prompt = f"Translate from {source_language} to {target_language}:\n\n```\n{text}\n```"

        model = self._deployment if self._settings.azure_openai_endpoint else "gpt-4"
        response = await self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
        )

        translated = response.choices[0].message.content or ""
        return {
            "translated_text": translated.strip(),
            "target_language": target_language,
            "source_language": source_language,
            "confidence": getattr(response.choices[0], "logprobs", None),  # None for most APIs
        }

    async def translate_segments(
        self,
        segments: list[dict],
        target_language: str = "es",
        source_language: str | None = None,
    ) -> list[dict]:
        """Batch translate a list of transcript segments."""
        results: list[dict] = []
        for seg in segments:
            result = await self.translate(
                text=seg.get("text", ""),
                target_language=target_language,
                source_language=source_language,
            )
            results.append(
                {
                    "id": seg.get("id"),
                    "start": seg.get("start"),
                    "end": seg.get("end"),
                    "original_text": seg.get("text", ""),
                    "translated_text": result["translated_text"],
                    "target_language": target_language,
                }
            )
        return results
