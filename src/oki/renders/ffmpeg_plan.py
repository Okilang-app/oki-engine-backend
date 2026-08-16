from typing import Any
from uuid import UUID


class FFmpegPlanBuilder:
    """Build FFmpeg command plans for render execution.

    TODO: integrate with ffmpeg-python or raw ffmpeg subprocess.
    """

    def __init__(self, ffmpeg_path: str = "ffmpeg") -> None:
        self._ffmpeg_path = ffmpeg_path

    def build(
        self,
        *,
        inputs: list[dict[str, Any]],
        filters: list[dict[str, Any]],
        output: dict[str, Any],
    ) -> dict[str, Any]:
        """Produce a structured plan that can be executed later.

        TODO: generate actual ffmpeg filter_complex graphs.
        """
        return {
            "ffmpeg_path": self._ffmpeg_path,
            "inputs": inputs,
            "filters": filters,
            "output": output,
            "command": [
                self._ffmpeg_path,
                # TODO: build real argument list
                "-i", "input.mp4",
                "-c", "copy",
                "output.mp4",
            ],
            "mock": True,
        }
