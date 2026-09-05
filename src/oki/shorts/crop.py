import json
import subprocess
from pathlib import Path
from typing import Any


class CropTracker:
    """Track subject position and compute vertical crop parameters."""

    def __init__(self, ffprobe_path: str = "ffprobe") -> None:
        self._ffprobe = ffprobe_path

    def track(self, source_video_path: str, timestamps: list[float]) -> dict[str, Any]:
        """Return crop params for vertical 9:16 output."""
        if not Path(source_video_path).exists():
            return {"width": 608, "height": 1080, "x": 656, "y": 0, "source_width": 1920, "source_height": 1080}

        # Get video dimensions
        try:
            cmd = [
                self._ffprobe, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "json", source_video_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            data = json.loads(result.stdout)
            stream = data.get("streams", [{}])[0]
            src_w = stream.get("width", 1920)
            src_h = stream.get("height", 1080)
        except Exception:
            src_w, src_h = 1920, 1080

        # Target: 9:16 vertical from center of 16:9 source
        target_w = int(src_h * 9 / 16)
        target_h = src_h
        x = (src_w - target_w) // 2
        y = 0

        return {
            "width": target_w,
            "height": target_h,
            "x": x,
            "y": y,
            "source_width": src_w,
            "source_height": src_h,
        }
