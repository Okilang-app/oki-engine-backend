import json
import subprocess
from pathlib import Path


class ShortScorer:
    """Score short-form video candidates using heuristics."""

    def __init__(self, ffprobe_path: str = "ffprobe") -> None:
        self._ffprobe = ffprobe_path

    def score(self, candidate) -> dict[str, float]:
        """Return factor scores and total score for a candidate.

        candidate has: start_time, end_time, source_video_path, transcript_segments (optional)
        """
        duration = candidate.end_time - candidate.start_time
        scores = {
            "duration_score": self._duration_score(duration),
            "motion_score": self._motion_score(candidate),
            "dialogue_density": self._dialogue_density(candidate),
            "hook_score": self._hook_score(candidate),
            "viral_potential": self._viral_potential(candidate),
        }
        # Weighted total
        weights = {"duration_score": 0.25, "motion_score": 0.2, "dialogue_density": 0.2, "hook_score": 0.2, "viral_potential": 0.15}
        total = sum(scores[k] * weights[k] for k in scores)
        scores["total"] = round(total, 4)
        return scores

    def _duration_score(self, duration: float) -> float:
        # Ideal: 30-60s for Shorts
        if 15 <= duration <= 60:
            return 1.0
        elif duration < 15:
            return duration / 15
        elif duration <= 90:
            return 1.0 - (duration - 60) / 30
        return 0.0

    def _motion_score(self, candidate) -> float:
        # Use ffprobe to detect scene changes (motion intensity proxy)
        path = getattr(candidate, "source_video_path", None)
        if not path or not Path(path).exists():
            return 0.5
        try:
            cmd = [
                self._ffprobe, "-f", "lavfi",
                f"movie={path},select='gte(scene,0.3)',showinfo",
                "-show_entries", "frame=pkt_pts_time", "-of", "json",
                "-v", "quiet",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            data = json.loads(result.stdout) if result.stdout else {}
            frames = data.get("frames", [])
            if not frames:
                return 0.5
            # Count scene changes in the candidate window
            changes = sum(
                1 for f in frames
                if candidate.start_time <= float(f.get("pkt_pts_time", 0)) <= candidate.end_time
            )
            # 1-3 scene changes is good for shorts
            return min(1.0, changes / 3)
        except Exception:
            return 0.5

    def _dialogue_density(self, candidate) -> float:
        # If transcript segments available, measure word density
        segments = getattr(candidate, "transcript_segments", None)
        if not segments:
            return 0.5
        duration = candidate.end_time - candidate.start_time
        words = sum(len(seg.get("text", "").split()) for seg in segments)
        wps = words / duration if duration > 0 else 0
        # 2-4 words per second is good
        return min(1.0, wps / 4)

    def _hook_score(self, candidate) -> float:
        # First 3 seconds should have dialogue or visual change
        duration = candidate.end_time - candidate.start_time
        if duration < 3:
            return 0.3
        segments = getattr(candidate, "transcript_segments", None)
        if segments:
            first_3s_words = sum(
                len(seg.get("text", "").split())
                for seg in segments
                if seg.get("start", 0) <= candidate.start_time + 3
            )
            return min(1.0, first_3s_words / 5)
        return 0.5

    def _viral_potential(self, candidate) -> float:
        # Standalone factor — emotional keywords, call-to-action
        segments = getattr(candidate, "transcript_segments", None)
        if not segments:
            return 0.5
        text = " ".join(seg.get("text", "").lower() for seg in segments)
        viral_keywords = ["amazing", "unbelievable", "secret", "must", "now", "free", "hack", "tip"]
        matches = sum(1 for kw in viral_keywords if kw in text)
        return min(1.0, matches / 3)
