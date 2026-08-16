from typing import Any


class SourceSeparator:
    """Separate audio into stems (vocals, accompaniment, etc.).

    TODO: integrate demucs or similar source separation when available.
    """

    def __init__(self) -> None:
        self._demucs_available = False
        try:
            import demucs  # noqa: F401
            self._demucs_available = True
        except ImportError:
            pass

    async def separate(self, audio_path: str) -> dict[str, Any]:
        """Return separated stems as asset references.

        TODO: implement actual separation using demucs or ffmpeg.
        """
        if self._demucs_available:
            # TODO: run demucs.separate and upload stems to S3
            pass
        return {
            "vocals": None,
            "accompaniment": None,
            "drums": None,
            "bass": None,
            "other": None,
            "mock": True,
        }
