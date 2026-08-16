from typing import Any
from uuid import UUID


class AudioMixer:
    """Build and execute an audio mix plan.

    TODO: integrate with ffmpeg for actual mixing.
    """

    def __init__(self, output_bucket: str, s3_endpoint: str | None = None) -> None:
        self._output_bucket = output_bucket
        self._s3_endpoint = s3_endpoint

    def mix(
        self,
        *,
        dialogue_tracks: list[dict[str, Any]],
        music_stems: list[dict[str, Any]],
        sfx_stems: list[dict[str, Any]],
        target_loudness_lufs: float = -14.0,
    ) -> dict[str, Any]:
        """Produce a deterministic mix plan without executing it.

        TODO: execute via ffmpeg and upload result to S3.
        """
        return {
            "dialogue_tracks": dialogue_tracks,
            "music_stems": music_stems,
            "sfx_stems": sfx_stems,
            "target_loudness_lufs": target_loudness_lufs,
            "steps": [
                "normalize_dialogue",
                "duck_music",
                "mix_sfx",
                "render_master",
            ],
            "mock": True,
        }
