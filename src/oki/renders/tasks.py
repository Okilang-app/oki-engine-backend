"""Render pipeline tasks — subtitle generation + video render execution."""
from __future__ import annotations

import asyncio
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID


async def generate_subtitles_task(job_id: UUID, asset_id: UUID, *, language: str = "en") -> dict[str, Any]:
    """Generate SRT and VTT subtitle files from transcript segments and upload to S3."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy import select
    from oki.config import Settings
    from oki.db.uow import UnitOfWork
    from oki.analysis.models import TranscriptSegments
    import boto3

    settings = Settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with UnitOfWork(session_factory) as uow:
            segments = list(await uow.session.scalars(
                select(TranscriptSegments)
                .where(TranscriptSegments.asset_id == asset_id, TranscriptSegments.job_id == job_id)
                .order_by(TranscriptSegments.start_time)
            ))
            if not segments:
                return {"task": "generate_subtitles", "status": "no_segments"}

        def _fmt_srt_time(seconds: float) -> str:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            ms = int((seconds % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        def _fmt_vtt_time(seconds: float) -> str:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            ms = int((seconds % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

        srt_lines: list[str] = []
        vtt_lines: list[str] = ["WEBVTT", ""]
        for i, seg in enumerate(segments, 1):
            start = float(seg.start_time)
            end = float(seg.end_time)
            text = seg.text.strip()
            if not text:
                continue

            srt_lines += [
                str(i),
                f"{_fmt_srt_time(start)} --> {_fmt_srt_time(end)}",
                text,
                "",
            ]
            vtt_lines += [
                f"{_fmt_vtt_time(start)} --> {_fmt_vtt_time(end)}",
                text,
                "",
            ]

        srt_content = "\n".join(srt_lines)
        vtt_content = "\n".join(vtt_lines)

        srt_key = f"subtitles/{job_id}/{language}.srt"
        vtt_key = f"subtitles/{job_id}/{language}.vtt"

        loop = asyncio.get_running_loop()

        s3 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.s3_access_key or "",
            aws_secret_access_key=settings.s3_secret_key or "",
        )

        def _upload():
            s3.put_object(
                Bucket=settings.s3_bucket, Key=srt_key,
                Body=srt_content.encode("utf-8"), ContentType="text/plain; charset=utf-8",
            )
            s3.put_object(
                Bucket=settings.s3_bucket, Key=vtt_key,
                Body=vtt_content.encode("utf-8"), ContentType="text/vtt; charset=utf-8",
            )

        await loop.run_in_executor(None, _upload)

        return {
            "task": "generate_subtitles",
            "status": "completed",
            "srt_key": srt_key,
            "vtt_key": vtt_key,
            "segments": len(segments),
            "language": language,
        }
    finally:
        await engine.dispose()


async def run_render_task(
    job_id: UUID,
    render_attempt_id: UUID,
    *,
    hatchet_workflow_run_id: str | None = None,
    hatchet_task_run_id: str | None = None,
) -> dict[str, Any]:
    """Execute render: generate subtitles then run video renderer."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy import select
    from oki.config import Settings
    from oki.db.uow import UnitOfWork
    from oki.renders.models import RenderAttempt, RenderManifest, RenderOutput
    from oki.assets.models import SourceAsset
    from oki.jobs.models import LocalizationJob

    settings = Settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with UnitOfWork(session_factory) as uow:
            attempt = await uow.session.get(RenderAttempt, render_attempt_id)
            if attempt is None:
                return {"render_attempt_id": str(render_attempt_id), "status": "not_found"}
            if attempt.status == "completed":
                return {"render_attempt_id": str(render_attempt_id), "status": "already_done"}

            manifest = await uow.session.get(RenderManifest, attempt.render_manifest_id)
            if manifest is None:
                attempt.status = "failed"
                attempt.error_message = "Manifest not found"
                await uow.session.flush()
                return {"render_attempt_id": str(render_attempt_id), "status": "no_manifest"}

            job = await uow.session.get(LocalizationJob, manifest.job_id)
            if job is None:
                attempt.status = "failed"
                attempt.error_message = "Localization job not found"
                await uow.session.flush()
                return {"render_attempt_id": str(render_attempt_id), "status": "no_job"}

            asset = await uow.session.scalar(
                select(SourceAsset)
                .where(SourceAsset.localization_job_id == manifest.job_id, SourceAsset.status == "active")
                .limit(1)
            )
            if asset is None:
                asset = await uow.session.scalar(
                    select(SourceAsset)
                    .where(SourceAsset.project_id == job.project_id)
                    .order_by(SourceAsset.created_at.desc())
                    .limit(1)
                )

            attempt.status = "processing"
            org_id = manifest.organization_id
            job_lang = getattr(job, "target_language", "en") or "en"
            asset_id = asset.id if asset else None
            await uow.session.flush()

        # Step 1: Generate subtitles
        subtitle_result: dict[str, Any] = {}
        if asset_id:
            try:
                subtitle_result = await generate_subtitles_task(job_id, asset_id, language=job_lang)
            except Exception as exc:
                subtitle_result = {"task": "generate_subtitles", "status": "error", "error": str(exc)}

        # Step 2: Run video renderer via OpenCVRenderService
        output_key: str | None = None
        render_error: str | None = None
        try:
            import boto3
            from oki.renders.opencv_renderer import OpenCVRenderService
            from oki.identity.authorization import Authorizer
            from oki.identity.schemas import Principal

            class _NullAuthorizer(Authorizer):
                def require(self, *args, **kwargs): pass

            engine2 = create_async_engine(settings.database_url)
            session_factory2 = async_sessionmaker(engine2, expire_on_commit=False)

            def _make_uow():
                return UnitOfWork(session_factory2)

            class _FakeStore:
                bucket = settings.s3_bucket
                _s3 = boto3.client(
                    "s3",
                    endpoint_url=str(settings.s3_endpoint_url) if settings.s3_endpoint_url else None,
                    aws_access_key_id=settings.s3_access_key or "",
                    aws_secret_access_key=settings.s3_secret_key or "",
                )

                def get_object(self, key: str):
                    return self._s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()

                def put_object(self, key: str, data: bytes, content_type: str = "video/mp4"):
                    self._s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

            renderer = OpenCVRenderService(_make_uow, _NullAuthorizer(), _FakeStore())

            # Map render_attempt to a RenderJob for the renderer
            fake_render_job_id = render_attempt_id
            await renderer.execute_render(fake_render_job_id)

            await engine2.dispose()
        except Exception as exc:
            render_error = f"{type(exc).__name__}: {exc}"

        # Step 3: Record subtitle outputs and finalize
        async with UnitOfWork(session_factory) as uow:
            attempt = await uow.session.get(RenderAttempt, render_attempt_id)
            if attempt is None:
                return {"render_attempt_id": str(render_attempt_id), "status": "lost"}

            outputs: list[dict] = []
            for fmt, key_field in (("srt", "srt_key"), ("vtt", "vtt_key")):
                key = subtitle_result.get(key_field)
                if key:
                    uow.session.add(RenderOutput(
                        organization_id=org_id,
                        render_attempt_id=render_attempt_id,
                        asset_reference=key,
                        format=fmt,
                        meta={"language": job_lang, "source": "generate_subtitles_task"},
                    ))
                    outputs.append({"format": fmt, "key": key})

            if render_error:
                attempt.status = "failed"
                attempt.error_message = render_error
            else:
                attempt.status = "completed"

            await uow.session.flush()

        return {
            "job_id": str(job_id),
            "render_attempt_id": str(render_attempt_id),
            "status": "completed" if not render_error else "failed",
            "subtitles": outputs,
            "render_error": render_error,
            "hatchet_workflow_run_id": hatchet_workflow_run_id,
        }
    finally:
        await engine.dispose()
