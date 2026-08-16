"""Hatchet task stub for translation execution.

TODO: wire to actual Hatchet worker decorators once the Hatchet SDK is integrated.
"""

from uuid import UUID


async def translation_execution_task(
    translation_id: UUID,
    job_id: UUID,
    asset_id: UUID,
    source_language: str,
    target_language: str,
) -> dict:
    """Execute translation for all segments of an asset.

    TODO: integrate TranslationService, OpenAITranslationClient, and context assembly.
    """
    return {
        "task": "translation_execution",
        "translation_id": str(translation_id),
        "job_id": str(job_id),
        "asset_id": str(asset_id),
        "source_language": source_language,
        "target_language": target_language,
        "status": "pending",
    }
