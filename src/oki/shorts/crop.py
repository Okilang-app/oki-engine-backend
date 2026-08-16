class CropTracker:
    """Stub crop tracker for short source videos.

    TODO: integrate with video processing pipeline for actual crop tracking.
    """

    def track(
        self,
        source_video_path: str,
        timestamps: list[tuple[float, float]],
    ) -> dict:
        """Return crop parameters dict for the given timestamps."""
        return {
            "x": 0,
            "y": 0,
            "width": 1920,
            "height": 1080,
            "timestamps": timestamps,
        }
