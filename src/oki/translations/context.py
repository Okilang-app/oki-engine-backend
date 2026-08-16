"""Stub context assembler for translation.

TODO: Implement full context assembly with terminology, style guides,
neighbor segments, and project glossary injection.
"""

from uuid import UUID

from oki.translations.models import GlossaryTerms, TranslationMemories


class TranslationContextAssembler:
    """Assemble translation context from transcript, glossary, and memories."""

    async def build_context(
        self,
        project_id: UUID,
        source_language: str,
        target_language: str,
        source_text: str,
    ) -> dict:
        """Return a context dictionary for a single translation request.

        Real implementation should:
        1. Load the project glossary for language pair.
        2. Query translation memories for fuzzy matches.
        3. Fetch neighbor segments for discourse context.
        4. Load project style guide snippets.
        """
        return {
            "project_id": str(project_id),
            "source_language": source_language,
            "target_language": target_language,
            "glossary": {},
            "translation_memories": [],
            "neighbors": {"before": None, "after": None},
            "style_guide": None,
        }

    async def load_glossary(
        self,
        project_id: UUID,
        source_language: str,
        target_language: str,
    ) -> dict[str, str]:
        """Return a mapping of source terms to target terms."""
        # TODO: query GlossaryTerms table
        return {}

    async def load_translation_memories(
        self,
        project_id: UUID,
        source_language: str,
        target_language: str,
        source_text: str,
    ) -> list[dict]:
        """Return fuzzy-matched translation memory entries."""
        # TODO: query TranslationMemories table
        return []
