from typing import Protocol
from uuid import UUID


class TtsProvider(Protocol):
    """Contract for text-to-speech synthesis providers."""

    async def synthesize(
        self,
        text: str,
        voice_profile_id: UUID,
        *,
        language_code: str = "en",
        ssml: bool = False,
    ) -> bytes:
        """Synthesize speech and return raw audio bytes.

        TODO: stream-return variant for long-form dubbing.
        """
        ...
