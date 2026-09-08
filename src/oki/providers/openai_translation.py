"""OpenAI / Azure OpenAI translation provider."""
from __future__ import annotations

from oki.config import Settings
from oki.providers.cost_guard import check_cost
from oki.providers.factory import create_openai_client


SYSTEM_PROMPT = (
    "You are a professional video localization translator. "
    "Translate faithfully, preserving meaning, tone, and factual accuracy. "
    "Do not add statements on behalf of the creator. "
    "Do not change numbers, proper names, or facts. "
    "Adapt humour only when the function is preserved. "
    "Flag any ambiguous phrases in the ambiguous_phrases list."
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
        creator_style: str | None = None,
        target_duration_seconds: float | None = None,
        neighbors: list[str] | None = None,
    ) -> dict:
        """Send text to GPT for translation with full SOW context."""
        if self._client is None:
            raise RuntimeError(
                "No OpenAI/Azure API configured. "
                "Set OKI_OPENAI_API_KEY, OKI_AZURE_OPENAI_ENDPOINT, "
                "or OKI_OPENAI_BASE_URL."
            )

        lines: list[str] = []
        if source_language:
            lines.append(f"Translate from {source_language} to {target_language}.")
        else:
            lines.append(f"Translate to {target_language}.")

        if creator_style:
            lines.append(f"Creator voice/style: {creator_style}")

        if target_duration_seconds is not None:
            lines.append(
                f"Target spoken duration: ~{target_duration_seconds:.1f}s. "
                "Shorten phrasing if needed without losing meaning."
            )

        if neighbors:
            lines.append("Neighbouring segments for context (do not translate these):")
            for n in neighbors[:2]:
                lines.append(f"  - {n}")

        if glossary:
            lines.append("Glossary (use these exact translations):")
            for k, v in glossary.items():
                lines.append(f"  {k} → {v}")

        lines.append(
            "\nReturn JSON: "
            '{"translated_text": "...", "ambiguous_phrases": ["..."]}'
        )
        lines.append(f"\nSource text:\n```\n{text}\n```")

        user_prompt = "\n".join(lines)
        estimated = max(len(text), 1) * 2e-5
        await check_cost("openai", estimated_cost_usd=estimated)

        model = self._deployment if self._settings.azure_openai_endpoint else "gpt-4"
        response = await self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=2000,
            response_format={"type": "json_object"},
        )

        import json
        raw = json.loads(response.choices[0].message.content or "{}")
        translated = raw.get("translated_text", "").strip()
        ambiguous = raw.get("ambiguous_phrases", [])

        return {
            "translated_text": translated,
            "target_language": target_language,
            "source_language": source_language,
            "ambiguous_phrases": ambiguous,
            "confidence": getattr(response.choices[0], "logprobs", None),
        }

    async def translate_segments(
        self,
        segments: list[dict],
        target_language: str = "es",
        source_language: str | None = None,
        glossary: dict[str, str] | None = None,
        creator_style: str | None = None,
    ) -> list[dict]:
        """Batch translate a list of transcript segments with neighbour context."""
        results: list[dict] = []
        texts = [s.get("text", "") for s in segments]
        for i, seg in enumerate(segments):
            neighbors = [t for j, t in enumerate(texts) if abs(i - j) == 1]
            result = await self.translate(
                text=seg.get("text", ""),
                target_language=target_language,
                source_language=source_language,
                glossary=glossary,
                creator_style=creator_style,
                target_duration_seconds=(
                    seg.get("end", 0) - seg.get("start", 0) if seg.get("end") else None
                ),
                neighbors=neighbors,
            )
            results.append({
                "id": seg.get("id"),
                "start": seg.get("start"),
                "end": seg.get("end"),
                "original_text": seg.get("text", ""),
                "translated_text": result["translated_text"],
                "ambiguous_phrases": result.get("ambiguous_phrases", []),
                "target_language": target_language,
            })
        return results
