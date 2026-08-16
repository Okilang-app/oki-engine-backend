from typing import Any


class PronunciationDictionary:
    """Apply pronunciation overrides to text and return SSML-like output.

    TODO: integrate with provider-specific phoneme dictionaries (IPA, X-SAMPA).
    """

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._entries = {e["original_text"]: e for e in entries}

    @classmethod
    def empty(cls) -> "PronunciationDictionary":
        return cls([])

    def apply(self, text: str, language: str) -> str:
        """Return SSML-like phoneme markup for provider consumption.

        TODO: implement tokenization and phoneme substitution.
        """
        if not text:
            return ""
        # Stub: return a speak wrapper that marks the language.
        # In production, this would substitute known pronunciation entries
        # with <phoneme alphabet="ipa" ph="..."> tags.
        return f'<speak xml:lang="{language}">{text}</speak>'
