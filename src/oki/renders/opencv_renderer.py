"""FFmpeg-based video rendering pipeline with ad insertion."""
import asyncio
import logging
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import boto3
from sqlalchemy import select

from oki.ads.models import InternalAd
from oki.assets.models import SourceAsset
from oki.config import Settings
from oki.db.uow import UnitOfWork
from oki.jobs.models import LocalizationJob
from oki.renders.enums import RenderStatus
from oki.renders.models import RenderJob
from oki.sponsors.models import AdSegments

logger = logging.getLogger(__name__)


class OpenCVRenderService:
    """Render video using FFmpeg: cut sponsor segments and splice in replacement ads."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        authorizer: "Authorizer",
        store: "S3ObjectStore",
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
        """Download source, cut/replace ad segments via FFmpeg, upload result.

        Runs from a FastAPI BackgroundTask, which discards exceptions — an
        unhandled error would otherwise leave the job stuck on PROCESSING with
        no message and no trace of what went wrong.
        """
        try:
            await self._execute_render(render_job_id)
        except Exception as exc:
            logger.exception("[Renderer] Render %s failed", render_job_id)
            await self._fail(render_job_id, f"{type(exc).__name__}: {exc}")

    async def _execute_render(self, render_job_id: UUID) -> None:
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
                # SourceAsset.localization_job_id only points at one job, so a
                # second job over the same asset re-points it and deleting that
                # job clears it. The segments record the asset the analysis
                # actually ran on, which is what we must render.
                analysed_asset_id = await uow.session.scalar(
                    select(AdSegments.asset_id)
                    .where(AdSegments.job_id == job.id)
                    .limit(1)
                )
                if analysed_asset_id is not None:
                    source_asset = await uow.session.scalar(
                        select(SourceAsset).where(SourceAsset.id == analysed_asset_id)
                    )

            if source_asset is None:
                # Never fall back to "some other asset in the org" — that renders
                # an unrelated video and reports success.
                render_job.status = RenderStatus.FAILED
                render_job.error_message = (
                    "No source asset linked to this job; cannot determine what to render."
                )
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

            # Load replacement ad files for segments marked "replaced"
            ad_map: dict[UUID, InternalAd] = {}
            for seg in segments:
                if seg.status.value == "replaced" and seg.proposed_replacement_ad_id:
                    if seg.proposed_replacement_ad_id not in ad_map:
                        ad = await uow.session.get(InternalAd, seg.proposed_replacement_ad_id)
                        if ad:
                            ad_map[seg.proposed_replacement_ad_id] = ad

        ffmpeg = self._settings.ffmpeg_path
        bucket = self._settings.s3_bucket
        source_key = source_asset.storage_key

        logger.info("[Renderer] Starting render %s", render_job_id)
        logger.info("[Renderer] Source: s3://%s/%s", bucket, source_key)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source_path = tmp / "source.mp4"
            output_path = tmp / "output.mp4"

            # 1. Download source video
            try:
                logger.info("[Renderer] Downloading source...")
                resp = self._s3.get_object(Bucket=bucket, Key=source_key)
                source_path.write_bytes(resp["Body"].read())
                logger.info("[Renderer] Downloaded %d bytes", source_path.stat().st_size)
            except Exception as e:
                logger.error("[Renderer] Download FAILED: %s", e)
                await self._fail(render_job_id, f"Download failed: {e}")
                return

            await self._update_progress(render_job_id, 20)

            # 2. Download replacement ad files
            ad_files: dict[UUID, Path] = {}
            for ad_id, ad in ad_map.items():
                ad_path = tmp / f"ad_{ad_id}.mp4"
                try:
                    resp = self._s3.get_object(Bucket=bucket, Key=ad.storage_key)
                    ad_path.write_bytes(resp["Body"].read())
                    ad_files[ad_id] = ad_path
                    logger.info("[Renderer] Downloaded ad %s (%d bytes)", ad.name, ad_path.stat().st_size)
                except Exception as e:
                    logger.warning("[Renderer] Failed to download ad %s: %s", ad_id, e)

            await self._update_progress(render_job_id, 30)

            # 3. Get source duration
            duration = await self._get_duration(ffmpeg, str(source_path))
            logger.info("[Renderer] Source duration: %.2fs", duration)

            # 4. Build the edit plan: segments to cut/replace
            # "replaced" → cut out original segment, insert replacement ad
            # "rejected" → cut out original segment entirely
            # "detected"/"confirmed"/"proposed" → leave unchanged
            actionable = sorted(
                [s for s in segments if s.status.value in ("replaced", "rejected")],
                key=lambda s: float(s.start_time),
            )

            if not actionable:
                # Nothing to change — copy source as output
                logger.info("[Renderer] No actionable segments — output equals source")
                output_path.write_bytes(source_path.read_bytes())
            else:
                logger.info("[Renderer] %d actionable segments (replaced/rejected)", len(actionable))
                await self._build_output(
                    ffmpeg, source_path, output_path, duration,
                    actionable, ad_files, tmp,
                )

            if not output_path.exists() or output_path.stat().st_size == 0:
                await self._fail(render_job_id, "Output file not created or empty")
                return

            logger.info("[Renderer] Output: %d bytes", output_path.stat().st_size)
            await self._update_progress(render_job_id, 80)

            # 5. Upload result
            output_key = f"renders/{render_job_id}/output.mp4"
            try:
                self._s3.put_object(
                    Bucket=bucket,
                    Key=output_key,
                    Body=output_path.read_bytes(),
                    ContentType="video/mp4",
                )
                logger.info("[Renderer] Uploaded s3://%s/%s", bucket, output_key)
            except Exception as e:
                logger.error("[Renderer] Upload FAILED: %s", e)
                await self._fail(render_job_id, f"Upload failed: {e}")
                return

            await self._update_progress(render_job_id, 100, output_key)

    async def _build_output(
        self,
        ffmpeg: str,
        source_path: Path,
        output_path: Path,
        duration: float,
        actionable: list[AdSegments],
        ad_files: dict[UUID, Path],
        tmp: Path,
    ) -> None:
        """Build output video by splicing keep-intervals and replacement ads."""
        # Build ordered list of parts: either "keep" intervals from source or "ad" files
        parts: list[Path] = []
        part_idx = 0
        last_end = 0.0

        for seg in actionable:
            seg_start = float(seg.start_time)
            seg_end = float(seg.end_time)

            # Keep interval before this segment
            if seg_start > last_end:
                keep_path = tmp / f"keep_{part_idx:03d}.mp4"
                await self._extract_segment(ffmpeg, source_path, keep_path, last_end, seg_start)
                if keep_path.exists() and keep_path.stat().st_size > 0:
                    parts.append(keep_path)
                    part_idx += 1

            # For "replaced" segments: insert the replacement ad
            if seg.status.value == "replaced" and seg.proposed_replacement_ad_id:
                ad_path = ad_files.get(seg.proposed_replacement_ad_id)
                if ad_path and ad_path.exists():
                    # Re-encode ad to match source format for clean concat
                    ad_normalized = tmp / f"ad_norm_{part_idx:03d}.mp4"
                    await self._normalize_for_concat(ffmpeg, ad_path, ad_normalized, source_path)
                    if ad_normalized.exists() and ad_normalized.stat().st_size > 0:
                        parts.append(ad_normalized)
                        part_idx += 1
                    else:
                        logger.warning("[Renderer] Ad normalization failed, skipping ad insert")
                else:
                    logger.warning("[Renderer] No ad file for segment, just cutting")
            # For "rejected" segments: just skip (cut out)

            last_end = max(last_end, seg_end)

        # Keep the tail after the last actionable segment
        if last_end < duration:
            keep_path = tmp / f"keep_{part_idx:03d}.mp4"
            await self._extract_segment(ffmpeg, source_path, keep_path, last_end, duration)
            if keep_path.exists() and keep_path.stat().st_size > 0:
                parts.append(keep_path)

        if not parts:
            # Edge case: nothing left
            await self._run_ffmpeg(
                ffmpeg,
                "-f", "lavfi", "-i", "color=c=black:s=1280x720:d=1",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=1",
                "-shortest", "-y", str(output_path),
            )
            return

        # Concatenate all parts
        concat_list = tmp / "concat.txt"
        concat_list.write_text("\n".join(f"file '{p}'" for p in parts) + "\n")

        logger.info("[Renderer] Concatenating %d parts...", len(parts))
        await self._run_ffmpeg(
            ffmpeg,
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            "-y", str(output_path),
        )

        # A stream-copy concat can "succeed" and still emit a truncated file when
        # the parts disagree, so check the runtime rather than just the size —
        # otherwise a 15-minute render silently ships as a few seconds.
        expected = 0.0
        for part in parts:
            expected += await self._probe_duration(str(part))
        actual = await self._probe_duration(str(output_path))
        too_short = expected > 0 and actual < expected * 0.98

        if not output_path.exists() or output_path.stat().st_size == 0 or too_short:
            logger.warning(
                "[Renderer] Copy-concat unusable (expected %.1fs, got %.1fs); re-encoding...",
                expected, actual,
            )
            await self._run_ffmpeg(
                ffmpeg,
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-y", str(output_path),
            )
            actual = await self._probe_duration(str(output_path))
            if expected > 0 and actual < expected * 0.98:
                raise RuntimeError(
                    f"Render produced {actual:.1f}s of video but the parts total "
                    f"{expected:.1f}s; refusing to publish a truncated output."
                )

    async def _probe_duration(self, path: str) -> float:
        """Return a file's duration in seconds, or 0.0 when it cannot be read.

        Unlike :meth:`_get_duration` this never substitutes a placeholder value —
        callers use it to validate output, where a fabricated number would hide
        the very failure being checked for.
        """
        ffprobe = self._settings.ffprobe_path
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [ffprobe, "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", path],
                    capture_output=True, text=True, timeout=30,
                ),
            )
            return float(result.stdout.strip())
        except Exception:
            return 0.0

    async def _extract_segment(
        self, ffmpeg: str, source: Path, output: Path, start: float, end: float
    ) -> None:
        """Extract a segment from source video."""
        duration = end - start
        if duration <= 0:
            return
        await self._run_ffmpeg(
            ffmpeg,
            "-ss", str(start),
            "-t", str(duration),
            "-i", str(source),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            "-y", str(output),
        )

    async def _normalize_for_concat(
        self, ffmpeg: str, input_path: Path, output_path: Path, reference_path: Path
    ) -> None:
        """Re-encode ad clip to match the source video's parameters for clean concatenation.

        Every part fed to the concat demuxer must carry the same stream layout.
        A silent ad would otherwise yield a video-only part, and concat with
        ``-c copy`` does not reject that — it emits a truncated, audio-less file
        while still reporting success. Synthesise silence so the layout matches.
        """
        # Get source video properties
        probe_info = await self._get_video_info(ffmpeg, str(reference_path))
        width = probe_info.get("width", 1920)
        height = probe_info.get("height", 1080)
        fps = probe_info.get("fps", 30)

        has_audio = await self._has_audio_stream(str(input_path))
        if not has_audio:
            logger.info("[Renderer] Ad %s has no audio; adding a silent track", input_path.name)

        args: list[str] = ["-i", str(input_path)]
        if not has_audio:
            args += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        args += [
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "-r", str(fps),
            "-map", "0:v:0",
            "-map", "1:a:0" if not has_audio else "0:a:0",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        ]
        if not has_audio:
            # anullsrc is infinite; stop when the video track ends.
            args += ["-shortest"]
        args += ["-y", str(output_path)]

        await self._run_ffmpeg(ffmpeg, *args)

    async def _has_audio_stream(self, path: str) -> bool:
        """Return True when the file carries at least one audio stream."""
        ffprobe = self._settings.ffprobe_path
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [ffprobe, "-v", "error", "-select_streams", "a",
                     "-show_entries", "stream=index", "-of", "csv=p=0", path],
                    capture_output=True, text=True, timeout=15,
                ),
            )
            return bool(result.stdout.strip())
        except Exception as exc:
            # Assume audio is present: re-muxing a track that exists is safe,
            # whereas wrongly adding a second one would break the mapping.
            logger.warning("[Renderer] Could not probe audio streams of %s: %s", path, exc)
            return True

    async def _get_video_info(self, ffmpeg: str, path: str) -> dict:
        """Get video width, height, fps via ffprobe."""
        from pathlib import Path as P
        ffmpeg_path = P(ffmpeg)
        if ffmpeg_path.name.lower() in ("ffmpeg.exe", "ffmpeg"):
            ffprobe = str(ffmpeg_path.with_name(
                "ffprobe.exe" if ffmpeg_path.suffix == ".exe" else "ffprobe"
            ))
        else:
            ffprobe = str(ffmpeg_path.parent / ("ffprobe" + ffmpeg_path.suffix))

        info: dict = {"width": 1920, "height": 1080, "fps": 30}
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [ffprobe, "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=width,height,r_frame_rate",
                     "-of", "csv=p=0", path],
                    capture_output=True, text=True, timeout=15,
                ),
            )
            parts = result.stdout.strip().split(",")
            if len(parts) >= 3:
                info["width"] = int(parts[0])
                info["height"] = int(parts[1])
                fps_str = parts[2]
                if "/" in fps_str:
                    num, den = fps_str.split("/")
                    info["fps"] = round(int(num) / int(den))
                else:
                    info["fps"] = round(float(fps_str))
        except Exception:
            pass
        return info

    async def _get_duration(self, ffmpeg: str, path: str) -> float:
        """Get video duration in seconds using ffprobe."""
        from pathlib import Path as P
        ffmpeg_path = P(ffmpeg)
        if ffmpeg_path.name.lower() in ("ffmpeg.exe", "ffmpeg"):
            ffprobe = str(ffmpeg_path.with_name(
                "ffprobe.exe" if ffmpeg_path.suffix == ".exe" else "ffprobe"
            ))
        else:
            ffprobe = str(ffmpeg_path.parent / ("ffprobe" + ffmpeg_path.suffix))

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [ffprobe, "-v", "error", "-show_entries",
                     "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
                    capture_output=True, text=True, timeout=30,
                ),
            )
            return float(result.stdout.strip())
        except Exception:
            # Fallback: parse ffmpeg stderr
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: subprocess.run(
                        [ffmpeg, "-i", path], capture_output=True, text=True, timeout=30,
                    ),
                )
                for line in (result.stdout + result.stderr).splitlines():
                    if "Duration:" in line:
                        parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
                        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            except Exception:
                pass
            return 30.0

    async def _run_ffmpeg(self, ffmpeg: str, *args: str) -> subprocess.CompletedProcess:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [ffmpeg, *args],
                capture_output=True, text=True,
            ),
        )
        if result.returncode != 0:
            logger.warning("[FFmpeg] Non-zero exit: %s\nstderr: %s", " ".join(args[:4]), result.stderr[:500])
        return result

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
