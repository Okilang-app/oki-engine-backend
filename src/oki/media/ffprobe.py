"""Media file introspection via ffprobe."""

import json
import logging
from pathlib import Path
from typing import Any

from oki.media.command import CommandRunner

logger = logging.getLogger(__name__)

ALLOWLISTED_VIDEO_CODECS = {"h264", "hevc", "vp9", "av1"}
ALLOWLISTED_AUDIO_CODECS = {"aac", "mp3", "flac", "opus", "pcm_s24le", "pcm_s16le"}
ALLOWLISTED_CONTAINERS = {"mp4", "mov", "mkv", "webm", "mxf", "wav", "aiff"}


class MediaProbe:
    """Run ffprobe and return structured stream/container information."""

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or CommandRunner()

    async def probe(self, path: Path | str) -> dict[str, Any]:
        """Return ffprobe JSON output as a Python dict."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_format",
            "-show_streams",
            "-of", "json",
            str(path),
        ]
        result = await self._runner.run(cmd)
        if result["rc"] != 0:
            logger.error("ffprobe failed: %s", result["stderr"])
            raise RuntimeError(f"ffprobe failed: {result['stderr']}")
        return json.loads(result["stdout"])

    def parse_streams(self, probe_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalize stream entries from ffprobe output."""
        streams: list[dict[str, Any]] = []
        for stream in probe_data.get("streams", []):
            streams.append(
                {
                    "index": stream.get("index"),
                    "type": stream.get("codec_type"),
                    "codec_name": stream.get("codec_name"),
                    "codec_long_name": stream.get("codec_long_name"),
                    "bitrate": self._safe_int(stream.get("bit_rate")),
                    "width": stream.get("width"),
                    "height": stream.get("height"),
                    "sample_rate": self._safe_int(stream.get("sample_rate")),
                    "channel_count": stream.get("channels"),
                    "language": stream.get("tags", {}).get("language"),
                    "duration": self._safe_float(stream.get("duration")),
                }
            )
        return streams

    def parse_container(self, probe_data: dict[str, Any]) -> dict[str, Any]:
        """Normalize format-level metadata."""
        fmt = probe_data.get("format", {})
        return {
            "container": fmt.get("format_name", "").split(",")[0],
            "duration": self._safe_float(fmt.get("duration")),
            "bitrate": self._safe_int(fmt.get("bit_rate")),
            "size_bytes": self._safe_int(fmt.get("size")),
        }

    def validate_codecs(
        self,
        probe_data: dict[str, Any],
        *,
        require_audio: bool = True,
    ) -> dict[str, Any]:
        """Check that streams use allow-listed codecs and contain required types."""
        streams = self.parse_streams(probe_data)
        container = self.parse_container(probe_data)
        errors: list[str] = []

        if container["container"] not in ALLOWLISTED_CONTAINERS:
            errors.append(f"container_not_allowed:{container['container']}")

        has_audio = False
        for stream in streams:
            codec = stream.get("codec_name", "")
            stype = stream.get("type", "")
            if stype == "audio":
                has_audio = True
                if codec not in ALLOWLISTED_AUDIO_CODECS:
                    errors.append(f"audio_codec_not_allowed:{codec}")
            elif stype == "video":
                if codec not in ALLOWLISTED_VIDEO_CODECS:
                    errors.append(f"video_codec_not_allowed:{codec}")

        if require_audio and not has_audio:
            errors.append("missing_audio_stream")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "streams": streams,
            "container": container,
        }

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
