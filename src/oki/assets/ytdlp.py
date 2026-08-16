"""YouTube video import via yt-dlp."""

import asyncio
import hashlib
import logging
import subprocess
import tempfile
from pathlib import Path
from uuid import UUID

import boto3

from oki.config import Settings

logger = logging.getLogger(__name__)


class YtDlpImporter:
    """Download videos from YouTube URLs using yt-dlp and upload to S3."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._s3 = boto3.client(
            "s3",
            endpoint_url=str(settings.s3_endpoint_url) if settings.s3_endpoint_url else None,
            aws_access_key_id=settings.s3_access_key or "",
            aws_secret_access_key=settings.s3_secret_key or "",
        )

    async def download_and_upload(
        self,
        url: str,
        asset_id: UUID,
        organization_id: UUID,
    ) -> dict:
        """Download video from URL, upload to S3, return metadata.

        Returns dict with: storage_key, file_size, duration, title, sha256
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_download, url, asset_id, organization_id)

    def _sync_download(self, url: str, asset_id: UUID, organization_id: UUID) -> dict:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            output_template = str(tmp / "video.%(ext)s")

            logger.info("Downloading %s via yt-dlp", url)

            cmd = [
                "yt-dlp",
                "--no-playlist",
                "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "--merge-output-format", "mp4",
                "-o", output_template,
                "--print-json",
                "--no-simulate",
                url,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip().split("\n")[-1] if result.stderr else "Unknown error"
                raise RuntimeError(f"yt-dlp failed: {error_msg}")

            import json
            metadata = json.loads(result.stdout.strip().split("\n")[-1])

            video_files = list(tmp.glob("video.*"))
            if not video_files:
                video_files = list(tmp.glob("*"))
                video_files = [f for f in video_files if f.suffix in (".mp4", ".mkv", ".webm")]
            if not video_files:
                raise RuntimeError("yt-dlp did not produce an output file")

            video_path = video_files[0]
            file_size = video_path.stat().st_size
            logger.info("Downloaded %d bytes: %s", file_size, video_path.name)

            sha256 = hashlib.sha256(video_path.read_bytes()).hexdigest()

            storage_key = f"uploads/{organization_id}/{asset_id}/source.mp4"
            logger.info("Uploading to s3://%s/%s", self._settings.s3_bucket, storage_key)

            self._s3.put_object(
                Bucket=self._settings.s3_bucket,
                Key=storage_key,
                Body=video_path.read_bytes(),
                ContentType="video/mp4",
            )

            duration = metadata.get("duration")
            title = metadata.get("title", "Imported video")

            return {
                "storage_key": storage_key,
                "file_size": file_size,
                "duration": int(duration) if duration else None,
                "title": title,
                "sha256": sha256,
                "original_url": url,
                "channel": metadata.get("channel"),
                "upload_date": metadata.get("upload_date"),
            }
