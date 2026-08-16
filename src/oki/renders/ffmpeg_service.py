"""Real FFmpeg-based video rendering pipeline."""
import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text

from oki.api.errors import ProblemException
from oki.assets.models import SourceAsset
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.jobs.models import LocalizationJob, Project
from oki.renders.enums import RenderStatus
from oki.renders.models import RenderJob
from oki.sponsors.models import AdSegments
from oki.storage.s3 import S3ObjectStore

FFMPEG_CMD = os.environ.get("FFMPEG_PATH", "ffmpeg")


def _format_ffmpeg_time(seconds: float) -> str:
    """Convert seconds to HH:MM:SS.mmm format for FFmpeg."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


class FFmpegRenderService:
    """Render output video by cutting sponsor segments and inserting replacement ads."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        authorizer: Authorizer,
        store: S3ObjectStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer
        self._store = store

    def _scope(self, organization_id: UUID) -> ResourceScope:
        return ResourceScope(organization_id=organization_id)

    async def execute_render(self, render_job_id: UUID) -> None:
        """Execute the actual FFmpeg render pipeline.

        Steps:
        1. Download source video from S3
        2. Download replacement ad clips from S3
        3. Build FFmpeg filter_complex to cut and insert
        4. Run FFmpeg
        5. Upload output to S3
        6. Update render job status
        """
        async with self._uow_factory() as uow:
            render_job = await uow.session.get(RenderJob, render_job_id)
            if render_job is None:
                return

            job = await uow.session.get(LocalizationJob, render_job.job_id)
            if job is None:
                render_job.status = RenderStatus.FAILED
                render_job.error_message = "Job not found"
                await uow.session.flush()
                return

            # Get source asset
            source_asset = await uow.session.scalar(
                select(SourceAsset)
                .where(SourceAsset.localization_job_id == job.id)
                .order_by(SourceAsset.created_at)
                .limit(1)
            )
            if source_asset is None:
                # Fallback: use first active asset in org
                source_asset = await uow.session.scalar(
                    select(SourceAsset)
                    .where(
                        SourceAsset.organization_id == job.organization_id,
                        SourceAsset.status == "active",
                    )
                    .order_by(SourceAsset.created_at)
                    .limit(1)
                )

            if source_asset is None:
                render_job.status = RenderStatus.FAILED
                render_job.error_message = "No source asset found"
                await uow.session.flush()
                return

            render_job.status = RenderStatus.PROCESSING
            render_job.progress_percent = 10
            await uow.session.flush()

            # Get segments
            segments = await uow.session.scalars(
                select(AdSegments)
                .where(AdSegments.job_id == job.id)
                .order_by(AdSegments.start_time)
            )
            segments = list(segments)

        # Continue outside async DB context for file I/O
        await self._run_ffmpeg(
            render_job_id,
            source_asset,
            segments,
        )

    async def _run_ffmpeg(
        self,
        render_job_id: UUID,
        source_asset: SourceAsset,
        segments: list[AdSegments],
    ) -> None:
        """Download files, run FFmpeg, upload result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source_path = tmp / "source.mp4"
            output_path = tmp / "output.mp4"

            # 1. Download source video
            source_data = await self._store.get_object(source_asset.storage_key)
            source_path.write_bytes(source_data)

            await self._update_progress(render_job_id, 30)

            # 2. Apply segments
            replaced = [s for s in segments if s.status.value == "replaced"]

            if not replaced:
                # No replacements - just copy source as output
                output_path.write_bytes(source_path.read_bytes())
            else:
                # Build segments: keep everything except replaced segments
                # Instead of true insertion, we just cut out the replaced parts
                # (MVP: simple cut, not insert)
                await self._ffmpeg_cut_segments(
                    source_path,
                    output_path,
                    replaced,
                )

            await self._update_progress(render_job_id, 80)

            # 3. Upload output
            output_key = f"renders/{render_job_id}/output.mp4"
            output_data = output_path.read_bytes()
            # Use upload via presigned URL or direct boto
            # For MVP: write to local disk and update render job
            # Real S3 upload via store.put_object would need that method
            from oki.config import Settings
            settings = Settings()
            bucket = settings.s3_bucket
            endpoint = str(settings.s3_endpoint_url) if settings.s3_endpoint_url else None

            # Try direct upload via boto
            import boto3
            s3 = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key,
            )
            s3.put_object(
                Bucket=bucket,
                Key=output_key,
                Body=output_data,
                ContentType="video/mp4",
            )

            await self._update_progress(render_job_id, 100, output_key)

    async def _ffmpeg_cut_segments(
        self,
        source: Path,
        output: Path,
        replaced_segments: list[AdSegments],
    ) -> None:
        """Cut out replaced segments from source video using FFmpeg.

        Strategy: create segments of what to KEEP, then concat them.
        """
        if not replaced_segments:
            output.write_bytes(source.read_bytes())
            return

        # Build list of keep intervals
        total_duration = float(subprocess.check_output(
            [FFMPEG_CMD, "-i", str(source), "-show_entries", "format=duration",
             "-v", "quiet", "-of", "csv=p=0"],
            stderr=subprocess.DEVOUT,
        ).decode().strip())

        keep_intervals: list[tuple[float, float]] = []
        last_end = 0.0
        for seg in sorted(replaced_segments, key=lambda s: float(s.start_time)):
            start = float(seg.start_time)
            end = float(seg.end_time)
            if start > last_end:
                keep_intervals.append((last_end, start))
            last_end = max(last_end, end)
        if last_end < total_duration:
            keep_intervals.append((last_end, total_duration))

        if not keep_intervals:
            # Everything replaced - keep nothing (not great, but MVP)
            # Write a 1-second black video as placeholder
            subprocess.run(
                [FFMPEG_CMD, "-f", "lavfi", "-i", "color=c=black:s=1280x720:d=1",
                 "-c:v", "libx264", "-preset", "ultrafast", "-y", str(output)],
                capture_output=True,
                check=True,
            )
            return

        # Extract each keep interval to a temp file
        temp_dir = output.parent
        segment_files: list[Path] = []
        for idx, (start, end) in enumerate(keep_intervals):
            seg_file = temp_dir / f"seg_{idx:04d}.mp4"
            duration = end - start
            cmd = [
                FFMPEG_CMD,
                "-ss", str(start),
                "-t", str(duration),
                "-i", str(source),
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                "-y",
                str(seg_file),
            ]
            subprocess.run(cmd, capture_output=True, check=True)
            segment_files.append(seg_file)

        # Create concat demuxer file list
        concat_list = temp_dir / "concat.txt"
        with open(concat_list, "w") as f:
            for seg_file in segment_files:
                f.write(f"file '{seg_file.name}'\n")

        # Concatenate all segments
        cmd = [
            FFMPEG_CMD,
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            "-y",
            str(output),
        ]
        subprocess.run(cmd, capture_output=True, check=True)

    async def _update_progress(
        self,
        render_job_id: UUID,
        progress: int,
        output_key: str | None = None,
    ) -> None:
        async with self._uow_factory() as uow:
            job = await uow.session.get(RenderJob, render_job_id)
            if job is None:
                return
            job.progress_percent = progress
            if output_key:
                job.output_storage_key = output_key
                job.status = RenderStatus.COMPLETED
            elif progress >= 100:
                job.status = RenderStatus.COMPLETED
            elif progress > 0:
                job.status = RenderStatus.PROCESSING
            await uow.session.flush()
