"""FFmpeg-based video rendering pipeline."""
import asyncio
import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import boto3
from sqlalchemy import select

from oki.assets.models import SourceAsset
from oki.config import Settings
from oki.db.uow import UnitOfWork
from oki.jobs.models import LocalizationJob
from oki.renders.enums import RenderStatus
from oki.renders.models import RenderJob
from oki.sponsors.models import AdSegments
from oki.storage.s3 import S3ObjectStore


class OpenCVRenderService:
    """Render video using FFmpeg (fast, copy-codec concatenation)."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        authorizer: "Authorizer",
        store: S3ObjectStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer
        self._store = store
        self._settings = Settings()
        self._s3 = boto3.client(
            "s3",
            endpoint_url=str(self._settings.s3_endpoint_url)
            if self._settings.s3_endpoint_url
            else None,
            aws_access_key_id=self._settings.s3_access_key or "",
            aws_secret_access_key=self._settings.s3_secret_key or "",
        )

    async def execute_render(self, render_job_id: UUID) -> None:
        """Download source, cut replaced segments via FFmpeg, upload result."""
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

            source_asset = await uow.session.scalar(
                select(SourceAsset)
                .where(
                    SourceAsset.localization_job_id == job.id,
                    SourceAsset.status == "active",
                )
            )
            if source_asset is None:
                source_asset = await uow.session.scalar(
                    select(SourceAsset)
                    .where(
                        SourceAsset.organization_id == job.organization_id,
                        SourceAsset.status == "active",
                    )
                    .order_by(SourceAsset.created_at.desc())
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

            segments = list(await uow.session.scalars(
                select(AdSegments)
                .where(AdSegments.job_id == job.id)
                .order_by(AdSegments.start_time)
            ))

        ffmpeg = self._settings.ffmpeg_path
        bucket = self._settings.s3_bucket
        source_key = source_asset.storage_key

        print(f"[Renderer] Starting render {render_job_id}")
        print(f"[Renderer] Source: s3://{bucket}/{source_key}")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source_path = tmp / "source.mp4"
            output_path = tmp / "output.mp4"
            concat_list = tmp / "concat.txt"

            # 1. Download source
            try:
                print(f"[Renderer] Downloading...")
                resp = self._s3.get_object(Bucket=bucket, Key=source_key)
                source_path.write_bytes(resp["Body"].read())
                print(f"[Renderer] Downloaded {source_path.stat().st_size} bytes")
            except Exception as e:
                print(f"[Renderer] Download FAILED: {e}")
                await self._fail(render_job_id, f"Download failed: {e}")
                return

            await self._update_progress(render_job_id, 30)

            # Get duration via ffprobe (fallback to ffmpeg)
            duration = await self._get_duration(ffmpeg, str(source_path))
            print(f"[Renderer] Duration: {duration:.2f}s")

            # Build keep intervals (everything NOT replaced or rejected)
            to_remove = sorted(
                [s for s in segments if s.status.value in ("replaced", "rejected")],
                key=lambda s: float(s.start_time),
            )
            print(f"[Renderer] {len(to_remove)} segments to remove (replaced/rejected)")

            keep_intervals: list[tuple[float, float]] = []
            last_end = 0.0
            for seg in to_remove:
                s = float(seg.start_time)
                e = float(seg.end_time)
                if s > last_end:
                    keep_intervals.append((last_end, s))
                last_end = max(last_end, e)
            if last_end < duration:
                keep_intervals.append((last_end, duration))

            if not keep_intervals:
                # Entire video removed — create 1s black video
                print("[Renderer] All segments removed — creating black video")
                await self._run_ffmpeg(
                    ffmpeg,
                    "-f", "lavfi", "-i", "color=c=black:s=1280x720:d=1",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=1",
                    "-shortest",
                    "-y", str(output_path),
                )
            else:
                print(f"[Renderer] Keeping intervals: {keep_intervals}")
                parts: list[Path] = []
                for idx, (start, end) in enumerate(keep_intervals):
                    dur = end - start
                    part = tmp / f"part{idx:03d}.mp4"
                    await self._run_ffmpeg(
                        ffmpeg,
                        "-ss", str(start),
                        "-t", str(dur),
                        "-i", str(source_path),
                        "-c", "copy",
                        "-avoid_negative_ts", "make_zero",
                        "-y", str(part),
                    )
                    if part.exists():
                        parts.append(part)
                        print(f"  part{idx:03d}.mp4: {part.stat().st_size} bytes")

                if not parts:
                    await self._fail(render_job_id, "No segments extracted")
                    return

                # Build concat list
                concat_list.write_text(
                    "\n".join(f"file '{p}'" for p in parts) + "\n"
                )
                print(f"[Renderer] Concatenating {len(parts)} parts...")
                await self._run_ffmpeg(
                    ffmpeg,
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(concat_list),
                    "-c", "copy",
                    "-y", str(output_path),
                )

            if not output_path.exists():
                await self._fail(render_job_id, "Output file not created")
                return

            print(f"[Renderer] Output: {output_path.stat().st_size} bytes")
            await self._update_progress(render_job_id, 80)

            # Upload
            output_key = f"renders/{render_job_id}/output.mp4"
            try:
                self._s3.put_object(
                    Bucket=bucket,
                    Key=output_key,
                    Body=output_path.read_bytes(),
                    ContentType="video/mp4",
                )
                print(f"[Renderer] Uploaded s3://{bucket}/{output_key}")
            except Exception as e:
                print(f"[Renderer] Upload FAILED: {e}")
                await self._fail(render_job_id, f"Upload failed: {e}")
                return

            await self._update_progress(render_job_id, 100, output_key)

    async def _get_duration(self, ffmpeg: str, path: str) -> float:
        """Get video duration in seconds using ffprobe or fallback."""
        from pathlib import Path as P
        ffmpeg_path = P(ffmpeg)
        if ffmpeg_path.name.lower() == "ffmpeg.exe":
            ffprobe = str(ffmpeg_path.with_name("ffprobe.exe"))
        elif ffmpeg_path.name.lower() == "ffmpeg":
            ffprobe = str(ffmpeg_path.with_name("ffprobe"))
        else:
            ffprobe = str(ffmpeg_path.parent / ("ffprobe" + ffmpeg_path.suffix))
        try:
            result = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries",
                 "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, timeout=30,
            )
            return float(result.stdout.strip())
        except Exception:
            # Fallback: parse ffmpeg output
            result = subprocess.run(
                [ffmpeg, "-i", path],
                capture_output=True, text=True, timeout=30,
            )
            for line in (result.stdout + result.stderr).splitlines():
                if "Duration:" in line:
                    parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
                    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            return 30.0

    async def _run_ffmpeg(self, ffmpeg: str, *args: str) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [ffmpeg, *args],
                capture_output=True, text=True, check=True,
            ),
        )

    async def _update_progress(
        self, render_job_id: UUID, progress: int, output_key: str | None = None
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
            else:
                job.status = RenderStatus.PROCESSING
            await uow.session.flush()

    async def _fail(self, render_job_id: UUID, message: str) -> None:
        async with self._uow_factory() as uow:
            job = await uow.session.get(RenderJob, render_job_id)
            if job is None:
                return
            job.status = RenderStatus.FAILED
            job.error_message = message
            await uow.session.flush()
