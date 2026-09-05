import re
from typing import Any


class PronunciationDictionary:
    """Apply pronunciation overrides to text and return SSML-like output.

    Integrates with provider-specific phoneme dictionaries (IPA, X-SAMPA).
    """

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._entries = entries

    @classmethod
    def empty(cls) -> "PronunciationDictionary":
        return cls([])

    def apply(self, text: str, language: str) -> str:
        """Return text with pronunciation substitutions applied.

        Each entry's original_text is replaced case-insensitively with its
        pronunciation value.
        """
        if not text:
            return ""

        result = text
        for entry in self._entries:
            original = entry.get("original_text", "")
            pronunciation = entry.get("pronunciation", "")
            if not original or pronunciation is None:
                continue
            pattern = re.compile(re.escape(original), re.IGNORECASE)
            result = pattern.sub(pronunciation, result)

        return result
