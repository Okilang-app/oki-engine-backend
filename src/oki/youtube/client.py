import os
from typing import Any
from uuid import UUID

import httpx

from oki.youtube.oauth import YoutubeOAuthService


class YoutubeClient:
    """YouTube Data API v3 client for uploads, publishing, and metadata."""

    def __init__(self, oauth_service: YoutubeOAuthService) -> None:
        self._oauth = oauth_service

    async def upload_video(
        self,
        connection_id: UUID,
        file_path: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Upload a video file to YouTube via two-step resumable upload."""
        access_token = await self._oauth.get_valid_access_token(connection_id)
        file_size = os.path.getsize(file_path)

        # Step 1: initiate resumable upload
        async with httpx.AsyncClient() as client:
            init_resp = await client.post(
                "https://www.googleapis.com/upload/youtube/v3/videos",
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Type": "video/mp4",
                    "X-Upload-Content-Length": str(file_size),
                },
                json=metadata,
            )
            init_resp.raise_for_status()
            upload_url = init_resp.headers["Location"]

        # Step 2: upload file bytes
        async with httpx.AsyncClient(timeout=600.0) as client:
            with open(file_path, "rb") as f:
                upload_resp = await client.put(
                    upload_url,
                    content=f.read(),
                    headers={"Content-Type": "video/mp4"},
                )
            upload_resp.raise_for_status()

        return upload_resp.json()

    async def publish_video(self, connection_id: UUID, video_id: str) -> dict[str, Any]:
        """Transition a video to public visibility."""
        access_token = await self._oauth.get_valid_access_token(connection_id)
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "status"},
                headers={"Authorization": f"Bearer {access_token}",
                         "Content-Type": "application/json"},
                json={"id": video_id, "status": {"privacyStatus": "public"}},
            )
            resp.raise_for_status()
            return resp.json()

    async def update_metadata(
        self, connection_id: UUID, video_id: str, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        """Patch video title, description, tags, and category."""
        access_token = await self._oauth.get_valid_access_token(connection_id)
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "snippet"},
                headers={"Authorization": f"Bearer {access_token}",
                         "Content-Type": "application/json"},
                json={"id": video_id, "snippet": metadata},
            )
            resp.raise_for_status()
            return resp.json()

    async def upload_caption(
        self,
        connection_id: UUID,
        video_id: str,
        caption_path: str,
        language: str,
        name: str = "Localized subtitles",
    ) -> dict[str, Any]:
        """Upload SRT/VTT captions to an existing video."""
        access_token = await self._oauth.get_valid_access_token(connection_id)
        file_size = os.path.getsize(caption_path)
        async with httpx.AsyncClient() as client:
            with open(caption_path, "rb") as f:
                resp = await client.post(
                    "https://www.googleapis.com/upload/youtube/v3/captions",
                    params={"uploadType": "resumable", "part": "snippet"},
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json; charset=UTF-8",
                        "X-Upload-Content-Type": "application/octet-stream",
                        "X-Upload-Content-Length": str(file_size),
                    },
                    json={
                        "snippet": {
                            "videoId": video_id,
                            "language": language,
                            "name": name,
                            "isDraft": False,
                        }
                    },
                )
            resp.raise_for_status()
            upload_url = resp.headers["Location"]

        async with httpx.AsyncClient() as client:
            with open(caption_path, "rb") as f:
                upload_resp = await client.put(
                    upload_url,
                    content=f.read(),
                    headers={"Content-Type": "application/octet-stream"},
                )
            upload_resp.raise_for_status()
            return upload_resp.json()

    async def poll_processing_status(self, connection_id: UUID, video_id: str) -> str:
        """Return 'processing', 'succeeded', 'failed', or 'terminated'."""
        access_token = await self._oauth.get_valid_access_token(connection_id)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "processingDetails", "id": video_id},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            if not items:
                return "not_found"
            status = items[0].get("processingDetails", {}).get("processingStatus", "unknown")
            return status
