"""YouTube Analytics ingestion stub."""

from typing import Any


class YoutubeAnalyticsIngestor:
    """Ingestor for pulling YouTube Analytics metrics.

    TODO: Implement actual YouTube Analytics API integration.
    """

    async def ingest(self, channel_id: str, date_range: tuple[str, str]) -> dict[str, Any]:
        """Ingest metrics for a channel over a date range.

        Args:
            channel_id: The YouTube channel identifier.
            date_range: Inclusive start and end dates (YYYY-MM-DD).

        Raises:
            NotImplementedError: YouTube Analytics API ingestion is not yet implemented.
        """
        raise NotImplementedError("TODO: YouTube Analytics API ingestion")

    async def ingest_video_metrics(self, video_id: str) -> dict[str, Any]:
        """Ingest detailed metrics for a single video.

        Args:
            video_id: The YouTube video identifier.

        Raises:
            NotImplementedError: YouTube Analytics API ingestion is not yet implemented.
        """
        raise NotImplementedError("TODO: YouTube Analytics API ingestion")
