"""Dubbing execution task — TTS per segment, then triggers audio mix pipeline."""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from oki.config import Settings
from oki.db.uow import UnitOfWork

log = logging.getLogger(__name__)

# Max concurrent TTS calls
_TTS_CONCURRENCY = 4


async def run_dubbing_task(
    job_id: UUID,
    *,
    resume_only: bool = False,
    hatchet_workflow_run_id: str | None = None,
    hatchet_task_run_id: str | None = None,
) -> dict[str, Any]:
    """Execute TTS dubbing for all (or only pending) segments, then run the audio mix pipeline.

    When resume_only=True, segments that already have a completed DubSegment are skipped.
    """
    from oki.jobs.models import LocalizationJob
    from oki.translations.models import TranslationSegments, Translations
    from oki.translations.enums import TranslationStatus
    from oki.dubbing.models import DubSegment

    settings = Settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        # ── 1. Load approved translation segments ──────────────────────────
        async with UnitOfWork(session_factory) as uow:
            job = await uow.session.get(LocalizationJob, job_id)
            if job is None:
                return {"job_id": str(job_id), "status": "not_found"}

            translation = await uow.session.scalar(
                select(Translations)
                .where(
                    Translations.job_id == job_id,
                    Translations.status.in_([
                        TranslationStatus.APPROVED,
                        TranslationStatus.REVIEW_PENDING,
                    ]),
                )
                .order_by(Translations.created_at.desc())
                .limit(1)
            )
            if translation is None:
                return {"job_id": str(job_id), "status": "no_approved_translation"}

            trans_segments = list(await uow.session.scalars(
                select(TranslationSegments)
                .where(TranslationSegments.translation_id == translation.id)
                .order_by(TranslationSegments.sequence_number)
            ))

            dub_segments = list(await uow.session.scalars(
                select(DubSegment)
                .where(DubSegment.job_id == job_id)
                .order_by(DubSegment.sequence_number)
            ))

        # When resuming, skip TranslationSegments that already have completed DubSegments
        if resume_only:
            completed_seqs = {
                ds.sequence_number
                for ds in dub_segments
                if ds.status == "completed" and ds.audio_asset_reference
            }
            trans_segments = [
                s for s in trans_segments
                if s.sequence_number not in completed_seqs
            ]
            log.info(
                "Resume dubbing job %s: %d segments to generate (%d already completed)",
                job_id, len(trans_segments), len(completed_seqs),
            )

        # Re-load dub_segments after potential filter (needed for seg_map below)
        async with UnitOfWork(session_factory) as uow:
            dub_segments = list(await uow.session.scalars(
                select(DubSegment)
                .where(DubSegment.job_id == job_id)
                .order_by(DubSegment.sequence_number)
            ))

        if not trans_segments:
            return {"job_id": str(job_id), "status": "no_segments"}

        from oki.providers.elevenlabs import ElevenLabsClient
        from oki.storage.s3 import S3ObjectStore
        from oki.voices.models import VoiceProfile

        store = S3ObjectStore(settings)
        elevenlabs = ElevenLabsClient(settings) if settings.elevenlabs_api_key else None

        # Build sequence_number → ElevenLabs voice ID from DubSegment voice profiles
        seq_to_voice_id: dict[int, str] = {}
        voice_profile_ids = {ds.voice_profile_id for ds in dub_segments if ds.voice_profile_id}
        if voice_profile_ids:
            async with UnitOfWork(session_factory) as uow:
                profiles = await uow.session.scalars(
                    select(VoiceProfile).where(VoiceProfile.id.in_(voice_profile_ids))
                )
                vp_map = {vp.id: vp.provider_voice_id for vp in profiles if vp.provider_voice_id}
            for ds in dub_segments:
                if ds.voice_profile_id and ds.voice_profile_id in vp_map:
                    seq_to_voice_id[ds.sequence_number] = vp_map[ds.voice_profile_id]

        # ── 2. TTS each segment concurrently ──────────────────────────────
        sem = asyncio.Semaphore(_TTS_CONCURRENCY)

        async def tts_one(seg: TranslationSegments) -> dict[str, Any]:
            if not seg.translated_text:
                return {"seq": seg.sequence_number, "segment_id": str(seg.id), "status": "skipped_empty"}
            if elevenlabs is None:
                return {"seq": seg.sequence_number, "segment_id": str(seg.id), "status": "skipped_no_tts"}
            voice_id = seq_to_voice_id.get(seg.sequence_number)
            async with sem:
                try:
                    audio_bytes = await elevenlabs.synthesize(
                        text=seg.translated_text,
                        voice_profile_id=voice_id or "21m00Tcm4TlvDq8ikWAM",
                    )
                    storage_key = f"dubs/{job_id}/{seg.id}.mp3"
                    await store.put_object(storage_key, audio_bytes, content_type="audio/mpeg")
                    return {
                        "seq": seg.sequence_number,
                        "segment_id": str(seg.id),
                        "storage_key": storage_key,
                        "start_time": seg.start_time,
                        "end_time": seg.end_time,
                        "status": "completed",
                    }
                except Exception as exc:
                    log.exception("TTS failed for segment %s (seq=%s)", seg.id, seg.sequence_number)
                    return {"seq": seg.sequence_number, "segment_id": str(seg.id), "status": "failed", "error": str(exc)[:200]}

        dub_results = await asyncio.gather(*[tts_one(s) for s in trans_segments])

        # ── 3. Persist audio_asset_reference on DubSegments ───────────────
        # Map by sequence_number — DubSegment has no source_segment_id FK
        seg_map = {s.sequence_number: s for s in dub_segments}
        async with UnitOfWork(session_factory) as uow:
            for result in dub_results:
                if result["status"] != "completed":
                    continue
                dub_seg = seg_map.get(result["seq"])
                if dub_seg:
                    db_seg = await uow.session.get(DubSegment, dub_seg.id)
                    if db_seg:
                        db_seg.audio_asset_reference = result["storage_key"]
                        db_seg.status = "completed"
                else:
                    log.warning("No DubSegment found for seq=%s job=%s", result["seq"], job_id)
            await uow.session.flush()

        completed = sum(1 for r in dub_results if r["status"] == "completed")
        log.info("Dubbing TTS complete: %d/%d segments dubbed for job %s", completed, len(trans_segments), job_id)

        # ── 4. Kick off audio mix pipeline ────────────────────────────────
        if completed > 0:
            try:
                mix_result = await run_audio_mix_pipeline(
                    job_id=job_id,
                    tts_results=[r for r in dub_results if r["status"] == "completed"],
                    session_factory=session_factory,
                    settings=settings,
                )
                log.info("Audio mix pipeline result for job %s: %s", job_id, mix_result.get("status"))
            except Exception:
                log.exception("Audio mix pipeline failed for job %s — TTS audio still saved", job_id)

        return {
            "job_id": str(job_id),
            "status": "completed",
            "segments_dubbed": completed,
            "total_segments": len(trans_segments),
        }
    finally:
        await engine.dispose()


async def run_audio_mix_pipeline(
    job_id: UUID,
    tts_results: list[dict[str, Any]],
    session_factory: async_sessionmaker,
    settings: Settings,
) -> dict[str, Any]:
    """
    Full audio mixing pipeline:
      1. Assemble dialogue track from TTS segments (with timing)
      2. Source-separate the original video (demucs or ffmpeg fallback)
      3. Mix dialogue + accompaniment, normalize to -14 LUFS
      4. Run QA (clipping, silence, loudness, true peak)
      5. Persist AudioMixVersion + AudioQaResult
      6. Advance workflow to DUBBING_REVIEW
    """
    import tempfile
    import subprocess
    from pathlib import Path

    import boto3

    from oki.assets.models import SourceAsset
    from oki.audio.mixing import AudioMixer
    from oki.audio.models import AudioMixVersion, AudioQaResult
    from oki.audio.qa import AudioQa
    from oki.audio.separation import SourceSeparator
    from oki.db.uow import UnitOfWork
    from oki.jobs.enums import WorkflowState
    from oki.jobs.models import LocalizationJob

    loop = asyncio.get_running_loop()

    s3 = boto3.client(
        "s3",
        endpoint_url=str(settings.s3_endpoint_url) if settings.s3_endpoint_url else None,
        aws_access_key_id=settings.s3_access_key or "",
        aws_secret_access_key=settings.s3_secret_key or "",
    )

    # ── Load job + source asset key ───────────────────────────────────────
    async with UnitOfWork(session_factory) as uow:
        job = await uow.session.get(LocalizationJob, job_id)
        if job is None:
            return {"status": "job_not_found"}

        organization_id = job.organization_id

        asset = await uow.session.scalar(
            select(SourceAsset)
            .where(SourceAsset.localization_job_id == job_id)
            .order_by(SourceAsset.created_at.desc())
        )
        if asset is None:
            asset = await uow.session.scalar(
                select(SourceAsset)
                .where(SourceAsset.project_id == job.project_id)
                .order_by(SourceAsset.created_at.desc())
            )
        source_key = asset.storage_key if asset else None

    # ── Create AudioMixVersion record ─────────────────────────────────────
    async with UnitOfWork(session_factory) as uow:
        prev = await uow.session.scalar(
            select(AudioMixVersion)
            .where(AudioMixVersion.job_id == job_id)
            .order_by(AudioMixVersion.version_number.desc())
            .limit(1)
        )
        version_number = (prev.version_number + 1) if prev else 1

        mix_version = AudioMixVersion(
            organization_id=organization_id,
            job_id=job_id,
            asset_id=job_id,  # placeholder
            version_number=version_number,
            status="processing",
            mix_plan={"tts_segments": len(tts_results)},
            stems={},
        )
        uow.session.add(mix_version)
        await uow.session.flush()
        mix_version_id = mix_version.id

    ffmpeg = settings.ffmpeg_path

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # ── Step 1: Download all TTS segment audio files ──────────────────
        def _download_segment(storage_key: str, dest: Path) -> None:
            resp = s3.get_object(Bucket=settings.s3_bucket, Key=storage_key)
            dest.write_bytes(resp["Body"].read())

        segment_paths: list[tuple[float | None, float | None, Path]] = []
        for i, r in enumerate(tts_results):
            dest = tmp / f"seg_{i:04d}.mp3"
            try:
                await loop.run_in_executor(None, _download_segment, r["storage_key"], dest)
                segment_paths.append((r.get("start_time"), r.get("end_time"), dest))
            except Exception:
                log.warning("Could not download segment %s", r["storage_key"])

        if not segment_paths:
            return {"status": "no_segments_downloaded"}

        # ── Step 2: Assemble full dialogue track with timing ──────────────
        dialogue_track = tmp / "dialogue.mp3"
        await loop.run_in_executor(
            None,
            lambda: _assemble_dialogue_track(segment_paths, dialogue_track, ffmpeg),
        )

        dialogue_key = f"dubs/{job_id}/dialogue_master.mp3"

        # ── Step 3: Source separation (if we have original video) ─────────
        accompaniment_key: str | None = None
        separation_method = "none"
        if source_key:
            try:
                separator = SourceSeparator()
                sep_result = await separator.separate(
                    source_key,
                    s3_bucket=settings.s3_bucket,
                    output_prefix=f"stems/{job_id}",
                    s3_endpoint=str(settings.s3_endpoint_url) if settings.s3_endpoint_url else None,
                    s3_access_key=settings.s3_access_key or "",
                    s3_secret_key=settings.s3_secret_key or "",
                    ffmpeg_path=ffmpeg,
                )
                accompaniment_key = sep_result.get("accompaniment")
                separation_method = sep_result.get("method", "unknown")
                log.info("Source separation complete for job %s: method=%s", job_id, separation_method)
            except Exception:
                log.exception("Source separation failed for job %s — mixing with silence bed", job_id)

        # ── Step 4: Upload assembled dialogue track ───────────────────────
        def _upload_dialogue():
            with dialogue_track.open("rb") as f:
                s3.put_object(
                    Bucket=settings.s3_bucket,
                    Key=dialogue_key,
                    Body=f,
                    ContentType="audio/mpeg",
                )

        await loop.run_in_executor(None, _upload_dialogue)

        # ── Step 5: Mix dialogue + accompaniment ──────────────────────────
        output_key = f"dubs/{job_id}/final_mix.m4a"
        mixer = AudioMixer(
            output_bucket=settings.s3_bucket,
            s3_endpoint=str(settings.s3_endpoint_url) if settings.s3_endpoint_url else None,
        )
        mix_result = await mixer.mix_async(
            dialogue_key=dialogue_key,
            source_key=source_key or dialogue_key,
            output_key=output_key,
            music_keys=[accompaniment_key] if accompaniment_key else None,
            target_loudness_lufs=-14.0,
            s3_access_key=settings.s3_access_key or "",
            s3_secret_key=settings.s3_secret_key or "",
            ffmpeg_path=ffmpeg,
        )
        log.info("Mix complete for job %s: output=%s", job_id, output_key)

        # ── Step 6: Run QA ────────────────────────────────────────────────
        qa = AudioQa()
        qa_result = await qa.evaluate(
            output_key,
            s3_bucket=settings.s3_bucket,
            s3_endpoint=str(settings.s3_endpoint_url) if settings.s3_endpoint_url else None,
            s3_access_key=settings.s3_access_key or "",
            s3_secret_key=settings.s3_secret_key or "",
            ffmpeg_path=ffmpeg,
        )
        log.info(
            "QA for job %s: passed=%s issues=%s", job_id, qa_result.passed, qa_result.issues
        )

    # ── Step 7: Persist results + advance workflow ────────────────────────
    async with UnitOfWork(session_factory) as uow:
        mix = await uow.session.get(AudioMixVersion, mix_version_id)
        if mix:
            mix.status = "completed"
            mix.output_asset_reference = output_key
            mix.mix_plan = {
                "tts_segments": len(tts_results),
                "separation_method": separation_method,
                "accompaniment_key": accompaniment_key,
                "dialogue_key": dialogue_key,
                **mix_result,
            }
            mix.stems = {
                "accompaniment": accompaniment_key,
            }

        qa_record = AudioQaResult(
            organization_id=organization_id,
            audio_mix_version_id=mix_version_id,
            clipping_detected=qa_result.clipping_detected,
            silence_detected=qa_result.silence_detected,
            cut_words_detected=qa_result.cut_words_detected,
            loudness_lufs=int(qa_result.loudness_lufs * 1000) if qa_result.loudness_lufs else None,
            issues=qa_result.issues,
            passed=qa_result.passed,
        )
        uow.session.add(qa_record)

        job = await uow.session.get(LocalizationJob, job_id)
        if job:
            job.state = WorkflowState.DUBBING_RUNNING  # remains DUBBING_RUNNING; frontend polls

        await uow.session.flush()

    return {
        "status": "completed",
        "mix_version_id": str(mix_version_id),
        "output_key": output_key,
        "qa_passed": qa_result.passed,
        "qa_issues": qa_result.issues,
        "separation_method": separation_method,
    }


def _assemble_dialogue_track(
    segments: list[tuple[float | None, float | None, Path]],
    output_path: Path,
    ffmpeg: str,
) -> None:
    """
    Concatenate TTS segment audio files into one continuous track.
    If timing info is available, insert silence between segments to preserve
    relative positions. Otherwise simple concatenation.
    """
    import subprocess

    has_timing = all(start is not None for start, _, _ in segments)

    if has_timing:
        # Build a filter_complex that places each segment at its start offset
        # with silence filling gaps.
        inputs = []
        filters = []
        for i, (start, end, path) in enumerate(segments):
            inputs += ["-i", str(path)]
            # Pad the segment with silence before it to position it correctly
            delay_ms = int((start or 0) * 1000)
            filters.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[s{i}]")

        mix_inputs = "".join(f"[s{i}]" for i in range(len(segments)))
        filters.append(f"{mix_inputs}amix=inputs={len(segments)}:duration=longest:normalize=0[out]")
        filter_str = ";".join(filters)

        cmd = [ffmpeg, "-y"]
        cmd += inputs
        cmd += ["-filter_complex", filter_str, "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "192k", str(output_path)]
    else:
        # Simple concatenation via concat demuxer
        concat_list = output_path.parent / "concat.txt"
        with concat_list.open("w") as f:
            for _, _, path in segments:
                f.write(f"file '{path}'\n")
        cmd = [
            ffmpeg, "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c:a", "libmp3lame", "-b:a", "192k", str(output_path),
        ]

    result = subprocess.run(cmd, capture_output=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg assemble failed: {result.stderr.decode()[-500:]}")
