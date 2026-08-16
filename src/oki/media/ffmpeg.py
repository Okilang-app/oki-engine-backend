"""FFmpeg runner for media transformation and proxy generation.

TODO: Implement real ffmpeg integration when libffmpeg / imageio-ffmpeg is available.
"""

import logging
from pathlib import Path
from typing import Any

from oki.media.command import CommandRunner

logger = logging.getLogger(__name__)


class FFmpegRunner:
    """Stub FFmpeg runner for proxy generation and audio extraction."""

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or CommandRunner()

    async def generate_proxy(
        self,
        source: Path | str,
        destination: Path | str,
        *,
        width: int = 1280,
        height: int = 720,
        video_bitrate: str = "2M",
    ) -> dict[str, Any]:
        """Generate a low-resolution proxy video.

        TODO: Wire real ffmpeg command once binary is available in deployment.
        """
        logger.info("proxy generation stub called: %s -> %s", source, destination)
        return {"status": "stub", "source": str(source), "destination": str(destination)}

    async def extract_audio(
        self,
        source: Path | str,
        destination: Path | str,
        *,
        codec: str = "pcm_s24le",
        sample_rate: int = 48000,
    ) -> dict[str, Any]:
        """Extract a lossless audio track from a source file.

        TODO: Wire real ffmpeg command once binary is available in deployment.
        """
        logger.info("audio extraction stub called: %s -> %s", source, destination)
        return {"status": "stub", "source": str(source), "destination": str(destination)}
