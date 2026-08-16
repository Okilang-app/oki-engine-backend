"""YouTube Data API client stub."""

from typing import Any
from uuid import UUID


class YoutubeClient:
    """Stub client for YouTube uploads, publishing, and metadata updates."""

    async def upload_video(
        self,
        connection_id: UUID,
        file_path: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Upload a video file to YouTube."""
        raise NotImplementedError("TODO: Implement YouTube video upload via resumable API.")

    async def publish_video(
        self,
        connection_id: UUID,
        video_id: str,
    ) -> dict[str, Any]:
        """Transition a video to public visibility."""
        raise NotImplementedError("TODO: Implement YouTube video publish transition.")

    async def update_metadata(
        self,
        connection_id: UUID,
        video_id: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch video title, description, tags, and category."""
        raise NotImplementedError("TODO: Implement YouTube metadata patch.")
