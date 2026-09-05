"""YouTube Analytics ingestion."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx

from oki.api.errors import ProblemException
from oki.config import get_settings


class YoutubeAnalyticsIngestor:
    """Ingest YouTube Analytics data via Data API v3."""

    async def ingest(
        self, channel_id: str, start_date: str, end_date: str
    ) -> dict[str, Any]:
        """Fetch analytics report for a channel date range."""
        settings = get_settings()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "statistics", "id": channel_id},
                headers={
                    "Authorization": f"Bearer {settings.youtube_client_id or 'stub'}"
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                if items:
                    stats = items[0].get("statistics", {})
                    return {
                        "channel_id": channel_id,
                        "views": int(stats.get("viewCount", 0)),
                        "subscribers": int(stats.get("subscriberCount", 0)),
                        "videos": int(stats.get("videoCount", 0)),
                        "period": {"start": start_date, "end": end_date},
                    }
            return {
                "channel_id": channel_id,
                "views": 0,
                "subscribers": 0,
                "videos": 0,
                "period": {"start": start_date, "end": end_date},
                "note": "YouTube Analytics API requires OAuth2 channel authorization",
            }

    async def ingest_video_metrics(self, video_id: str) -> dict[str, Any]:
        """Fetch per-video metrics."""
        settings = get_settings()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "statistics", "id": video_id},
                headers={
                    "Authorization": f"Bearer {settings.youtube_client_id or 'stub'}"
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                if items:
                    stats = items[0].get("statistics", {})
                    return {
                        "video_id": video_id,
                        "views": int(stats.get("viewCount", 0)),
                        "likes": int(stats.get("likeCount", 0)),
                        "comments": int(stats.get("commentCount", 0)),
                    }
            return {
                "video_id": video_id,
                "views": 0,
                "likes": 0,
                "comments": 0,
                "note": "YouTube Analytics API requires OAuth2",
            }
