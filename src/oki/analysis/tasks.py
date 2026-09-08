"""Analysis pipeline tasks — wired to real providers."""
from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path
from uuid import UUID

_SYSTEM_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def _make_uow_factory():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from oki.config import Settings
    from oki.db.uow import UnitOfWork

    settings = Settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return lambda: UnitOfWork(session_factory), engine, settings


async def transcription_task(job_id: UUID, asset_id: UUID) -> dict:
    """Transcribe asset audio via Whisper and persist transcript segments."""
    uow_factory, engine, settings = _make_uow_factory()
    try:
        from sqlalchemy import select
        from oki.assets.models import SourceAsset
        from oki.analysis.models import TranscriptSegments, TranscriptWords
        from oki.analysis.enums import AnalysisStatus, SegmentType
        from oki.providers.openai_transcription import OpenAITranscriptionClient
        import boto3

        async with uow_factory() as uow:
            asset = await uow.session.get(SourceAsset, asset_id)
            if asset is None or not asset.storage_key:
                return {"task": "transcription", "status": "skipped", "reason": "no_asset"}

            # Check idempotency
            existing = await uow.session.scalar(
                select(TranscriptSegments).where(
                    TranscriptSegments.asset_id == asset_id,
                    TranscriptSegments.job_id == job_id,
                ).limit(1)
            )
            if existing is not None:
                return {"task": "transcription", "status": "already_done"}

            org_id = asset.organization_id
            storage_key = asset.storage_key
            duration = float(asset.duration_seconds) if asset.duration_seconds else 0.0

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            video_path = tmp / "source.mp4"
            audio_path = tmp / "audio.m4a"

            loop = asyncio.get_running_loop()

            def _download():
                s3 = boto3.client(
                    "s3",
                    endpoint_url=settings.s3_endpoint_url or None,
                    aws_access_key_id=settings.s3_access_key or "",
                    aws_secret_access_key=settings.s3_secret_key or "",
                )
                resp = s3.get_object(Bucket=settings.s3_bucket, Key=storage_key)
                video_path.write_bytes(resp["Body"].read())

            await loop.run_in_executor(None, _download)

            await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [settings.ffmpeg_path, "-i", str(video_path), "-vn", "-c:a", "copy", "-y", str(audio_path)],
                    capture_output=True, check=True,
                ),
            )

            if duration == 0.0:
                try:
                    r = await loop.run_in_executor(
                        None,
                        lambda: subprocess.run(
                            [settings.ffprobe_path, "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
                            capture_output=True, text=True, timeout=30,
                        ),
                    )
                    duration = float(r.stdout.strip())
                except Exception:
                    duration = 60.0

            client = OpenAITranscriptionClient(settings)
            result = await client.transcribe(audio_path, duration_seconds=duration)

        segments_created = 0
        async with uow_factory() as uow:
            for seg_data in result.get("segments", []):
                seg = TranscriptSegments(
                    organization_id=org_id,
                    asset_id=asset_id,
                    job_id=job_id,
                    start_time=Decimal(str(seg_data.get("start", 0.0))),
                    end_time=Decimal(str(seg_data.get("end", 0.0))),
                    text=seg_data.get("text", "").strip(),
                    language_code=result.get("language", "auto")[:16],
                    segment_type=SegmentType.SPEECH,
                    confidence=Decimal("0.95"),
                    status=AnalysisStatus.COMPLETED,
                    created_by_user_id=_SYSTEM_USER_ID,
                )
                uow.session.add(seg)
                await uow.session.flush()
                segments_created += 1

                for word in seg_data.get("words", []):
                    uow.session.add(TranscriptWords(
                        segment_id=seg.id,
                        start_time=Decimal(str(word.get("start", 0.0))),
                        end_time=Decimal(str(word.get("end", 0.0))),
                        text=str(word.get("word", ""))[:500],
                        confidence=Decimal("0.90"),
                    ))

        return {"task": "transcription", "status": "completed", "segments_created": segments_created}
    finally:
        await engine.dispose()


async def diarization_task(job_id: UUID, asset_id: UUID) -> dict:
    """Assign speakers to transcript segments using silence-gap heuristic."""
    uow_factory, engine, settings = _make_uow_factory()
    try:
        from sqlalchemy import select
        from oki.analysis.models import Speakers, TranscriptSegments

        async with uow_factory() as uow:
            segments = list(await uow.session.scalars(
                select(TranscriptSegments)
                .where(
                    TranscriptSegments.asset_id == asset_id,
                    TranscriptSegments.job_id == job_id,
                )
                .order_by(TranscriptSegments.start_time)
                .with_for_update()
            ))
            if not segments:
                return {"task": "diarization", "status": "skipped", "reason": "no_segments"}

            # Check idempotency
            if segments[0].speaker_id is not None:
                return {"task": "diarization", "status": "already_done"}

            org_id = segments[0].organization_id
            speakers_by_label: dict[str, UUID] = {}
            speaker_counter = 1
            current_label = "SPEAKER_1"
            prev_end = 0.0

            for seg in segments:
                gap = float(seg.start_time) - prev_end
                if gap > 0.8 and prev_end > 0.0:
                    speaker_counter = (speaker_counter % 2) + 1
                    current_label = f"SPEAKER_{speaker_counter}"

                if current_label not in speakers_by_label:
                    sp = Speakers(
                        organization_id=org_id,
                        asset_id=asset_id,
                        job_id=job_id,
                        speaker_label=current_label,
                        confidence=Decimal("0.75"),
                        sample_count=1,
                        created_by_user_id=_SYSTEM_USER_ID,
                    )
                    uow.session.add(sp)
                    await uow.session.flush()
                    speakers_by_label[current_label] = sp.id

                seg.speaker_id = speakers_by_label[current_label]
                prev_end = float(seg.end_time)

        return {"task": "diarization", "status": "completed", "speakers_detected": len(speakers_by_label)}
    finally:
        await engine.dispose()


async def scene_detection_task(job_id: UUID, asset_id: UUID) -> dict:
    """Detect scene changes via FFprobe and persist Scenes rows."""
    uow_factory, engine, settings = _make_uow_factory()
    try:
        from sqlalchemy import select
        from oki.assets.models import SourceAsset
        from oki.analysis.models import Scenes
        import boto3

        async with uow_factory() as uow:
            asset = await uow.session.get(SourceAsset, asset_id)
            if asset is None or not asset.storage_key:
                return {"task": "scene_detection", "status": "skipped", "reason": "no_asset"}

            existing = await uow.session.scalar(
                select(Scenes).where(
                    Scenes.asset_id == asset_id,
                    Scenes.job_id == job_id,
                ).limit(1)
            )
            if existing is not None:
                return {"task": "scene_detection", "status": "already_done"}

            org_id = asset.organization_id
            storage_key = asset.storage_key
            duration = float(asset.duration_seconds) if asset.duration_seconds else 0.0

        loop = asyncio.get_running_loop()

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "source.mp4"

            def _download():
                s3 = boto3.client(
                    "s3",
                    endpoint_url=settings.s3_endpoint_url or None,
                    aws_access_key_id=settings.s3_access_key or "",
                    aws_secret_access_key=settings.s3_secret_key or "",
                )
                resp = s3.get_object(Bucket=settings.s3_bucket, Key=storage_key)
                video_path.write_bytes(resp["Body"].read())

            await loop.run_in_executor(None, _download)

            # Parse scene change timestamps from ffmpeg scdet filter output
            def _detect_scenes():
                r = subprocess.run(
                    [
                        settings.ffmpeg_path, "-i", str(video_path),
                        "-vf", "select='gt(scene,0.3)',showinfo",
                        "-vsync", "vfr", "-f", "null", "-",
                    ],
                    capture_output=True, text=True, timeout=300,
                )
                timestamps: list[float] = []
                for line in r.stderr.splitlines():
                    if "pts_time:" in line:
                        try:
                            part = line.split("pts_time:")[1].split()[0]
                            timestamps.append(float(part))
                        except (IndexError, ValueError):
                            pass
                return timestamps

            scene_times = await loop.run_in_executor(None, _detect_scenes)

        # Build scenes from change timestamps
        boundaries = [0.0] + scene_times + [duration if duration > 0 else None]
        scenes_data = []
        for i in range(len(boundaries) - 1):
            start = boundaries[i]
            end = boundaries[i + 1]
            if end is None:
                continue
            scenes_data.append({"start": start, "end": end, "label": f"Scene {i + 1}"})

        if not scenes_data and duration > 0:
            scenes_data = [{"start": 0.0, "end": duration, "label": "Scene 1"}]

        async with uow_factory() as uow:
            for sc in scenes_data:
                uow.session.add(Scenes(
                    organization_id=org_id,
                    asset_id=asset_id,
                    job_id=job_id,
                    start_time=Decimal(str(sc["start"])),
                    end_time=Decimal(str(sc["end"])),
                    scene_label=sc["label"],
                    confidence=Decimal("0.80"),
                ))

        return {"task": "scene_detection", "status": "completed", "scenes_detected": len(scenes_data)}
    finally:
        await engine.dispose()


async def ocr_task(job_id: UUID, asset_id: UUID) -> dict:
    """Extract on-screen text from video frames via GPT-4o vision."""
    uow_factory, engine, settings = _make_uow_factory()
    try:
        from sqlalchemy import select
        from oki.assets.models import SourceAsset
        from oki.analysis.models import OcrSpans
        from oki.providers.factory import create_openai_client
        import boto3

        client_gpt = create_openai_client(settings)
        if client_gpt is None:
            return {"task": "ocr", "status": "skipped", "reason": "no_openai_configured"}

        async with uow_factory() as uow:
            asset = await uow.session.get(SourceAsset, asset_id)
            if asset is None or not asset.storage_key:
                return {"task": "ocr", "status": "skipped", "reason": "no_asset"}

            existing = await uow.session.scalar(
                select(OcrSpans).where(
                    OcrSpans.asset_id == asset_id,
                    OcrSpans.job_id == job_id,
                ).limit(1)
            )
            if existing is not None:
                return {"task": "ocr", "status": "already_done"}

            org_id = asset.organization_id
            storage_key = asset.storage_key
            duration = float(asset.duration_seconds) if asset.duration_seconds else 60.0

        loop = asyncio.get_running_loop()
        model = settings.azure_gpt_deployment if settings.azure_openai_endpoint else "gpt-4o-mini"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            video_path = tmp / "source.mp4"

            def _download():
                s3 = boto3.client(
                    "s3",
                    endpoint_url=settings.s3_endpoint_url or None,
                    aws_access_key_id=settings.s3_access_key or "",
                    aws_secret_access_key=settings.s3_secret_key or "",
                )
                resp = s3.get_object(Bucket=settings.s3_bucket, Key=storage_key)
                video_path.write_bytes(resp["Body"].read())

            await loop.run_in_executor(None, _download)

            # Extract 1 frame every 30 seconds
            interval = 30
            frame_times = list(range(0, int(duration), interval)) or [0]
            spans_created = 0

            for t in frame_times:
                frame_path = tmp / f"frame_{t:06d}.jpg"

                def _extract(ts=t, fp=frame_path):
                    subprocess.run(
                        [settings.ffmpeg_path, "-ss", str(ts), "-i", str(video_path),
                         "-frames:v", "1", "-q:v", "2", "-y", str(fp)],
                        capture_output=True, check=False,
                    )

                await loop.run_in_executor(None, _extract)
                if not frame_path.exists():
                    continue

                img_b64 = base64.b64encode(frame_path.read_bytes()).decode()
                try:
                    resp = await client_gpt.chat.completions.create(
                        model=model,
                        messages=[{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Extract any on-screen text visible in this video frame. Return JSON: {\"texts\": [{\"text\": \"...\", \"confidence\": 0.9}]}. Return empty texts array if none."},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}", "detail": "low"}},
                            ],
                        }],
                        max_completion_tokens=500,
                        temperature=0,
                        response_format={"type": "json_object"},
                    )
                    content = resp.choices[0].message.content or "{}"
                    parsed = json.loads(content)
                    for item in parsed.get("texts", []):
                        text_val = str(item.get("text", "")).strip()
                        if not text_val:
                            continue
                        conf = float(item.get("confidence", 0.8))
                        async with uow_factory() as uow:
                            uow.session.add(OcrSpans(
                                organization_id=org_id,
                                asset_id=asset_id,
                                job_id=job_id,
                                start_time=Decimal(str(t)),
                                end_time=Decimal(str(min(t + interval, duration))),
                                text=text_val[:2000],
                                bounding_box={},
                                confidence=Decimal(str(min(1.0, max(0.0, conf)))),
                            ))
                        spans_created += 1
                except Exception:
                    pass

        return {"task": "ocr", "status": "completed", "spans_detected": spans_created}
    finally:
        await engine.dispose()


async def sponsor_candidate_detection_task(job_id: UUID, asset_id: UUID) -> dict:
    """Detect sponsor segments from transcript using SponsorBlock-ML."""
    uow_factory, engine, settings = _make_uow_factory()
    try:
        from decimal import Decimal
        from sqlalchemy import select
        from oki.analysis.models import TranscriptSegments
        from oki.sponsors.models import AdSegments, AdSegmentEvidence
        from oki.sponsors.enums import DetectionReason, ReplacementType, SponsorStatus
        from oki.providers.sponsorblock_ml import SponsorBlockMLDetector

        async with uow_factory() as uow:
            segments = list(await uow.session.scalars(
                select(TranscriptSegments)
                .where(
                    TranscriptSegments.asset_id == asset_id,
                    TranscriptSegments.job_id == job_id,
                )
                .order_by(TranscriptSegments.start_time)
            ))
            if not segments:
                return {"task": "sponsor_detection", "status": "skipped", "reason": "no_segments"}

            existing = await uow.session.scalar(
                select(AdSegments).where(
                    AdSegments.asset_id == asset_id,
                    AdSegments.job_id == job_id,
                ).limit(1)
            )
            if existing is not None:
                return {"task": "sponsor_detection", "status": "already_done"}

            org_id = segments[0].organization_id
            transcript_for_ml = [
                {"start": float(s.start_time), "end": float(s.end_time), "text": s.text}
                for s in segments
            ]

        try:
            detector = SponsorBlockMLDetector()
            predictions = detector.detect(transcript_for_ml)
        except Exception:
            predictions = []

        if not predictions:
            from oki.sponsors.detection import SPONSOR_KEYWORDS
            from oki.providers.sponsorblock_ml import _merge_predictions
            from types import SimpleNamespace
            keyword_hits = [
                {"start": s["start"], "end": s["end"], "category": "sponsor", "text": s["text"]}
                for s in transcript_for_ml
                if any(kw in s["text"].lower() for kw in SPONSOR_KEYWORDS)
            ]
            for m in _merge_predictions(keyword_hits):
                if m["end"] - m["start"] >= 3.0:
                    predictions.append(SimpleNamespace(**m))

        candidates = 0
        for match in predictions:
            async with uow_factory() as uow:
                seg_list = list(await uow.session.scalars(
                    select(TranscriptSegments)
                    .where(TranscriptSegments.asset_id == asset_id, TranscriptSegments.job_id == job_id)
                ))
                closest_seg = min(
                    seg_list,
                    key=lambda s: abs(((float(s.start_time) + float(s.end_time)) / 2) - ((match.start + match.end) / 2)),
                    default=None,
                )
                ad_seg = AdSegments(
                    organization_id=org_id,
                    asset_id=asset_id,
                    job_id=job_id,
                    start_time=Decimal(str(match.start)),
                    end_time=Decimal(str(match.end)),
                    sponsor_name=getattr(match, "category", None) if getattr(match, "category", "sponsor") != "sponsor" else None,
                    status=SponsorStatus.DETECTED,
                    replacement_type=None,
                    reason_note=None,
                    reviewed_by_user_id=None,
                    reviewed_at=None,
                    proposed_replacement_ad_id=None,
                    proposed_at=None,
                )
                uow.session.add(ad_seg)
                await uow.session.flush()
                uow.session.add(AdSegmentEvidence(
                    organization_id=org_id,
                    ad_segment_id=ad_seg.id,
                    evidence_type="ml_transformer",
                    source_segment_id=closest_seg.id if closest_seg else None,
                    confidence=Decimal("0.80"),
                ))
            candidates += 1

        return {"task": "sponsor_detection", "status": "completed", "candidates_detected": candidates}
    finally:
        await engine.dispose()


async def music_silence_task(job_id: UUID, asset_id: UUID) -> dict:
    """Detect music and silence regions using ffmpeg energy/silence filters."""
    uow_factory, engine, settings = _make_uow_factory()
    try:
        from sqlalchemy import select
        from oki.assets.models import SourceAsset
        from oki.analysis.models import Scenes
        import boto3

        async with uow_factory() as uow:
            asset = await uow.session.get(SourceAsset, asset_id)
            if asset is None or not asset.storage_key:
                return {"task": "music_silence", "status": "skipped", "reason": "no_asset"}
            existing = await uow.session.scalar(
                select(Scenes).where(
                    Scenes.asset_id == asset_id,
                    Scenes.job_id == job_id,
                    Scenes.scene_label.like("music%"),
                ).limit(1)
            )
            if existing is not None:
                return {"task": "music_silence", "status": "already_done"}
            org_id = asset.organization_id
            storage_key = asset.storage_key
            duration = float(asset.duration_seconds) if asset.duration_seconds else 0.0

        loop = asyncio.get_running_loop()

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "source.mp4"
            audio_path = Path(tmpdir) / "audio.wav"

            def _download():
                s3 = boto3.client(
                    "s3",
                    endpoint_url=settings.s3_endpoint_url or None,
                    aws_access_key_id=settings.s3_access_key or "",
                    aws_secret_access_key=settings.s3_secret_key or "",
                )
                resp = s3.get_object(Bucket=settings.s3_bucket, Key=storage_key)
                video_path.write_bytes(resp["Body"].read())

            await loop.run_in_executor(None, _download)
            await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [settings.ffmpeg_path, "-i", str(video_path), "-vn", "-ar", "16000",
                     "-ac", "1", "-y", str(audio_path)],
                    capture_output=True, check=True,
                ),
            )

            def _detect_silence():
                r = subprocess.run(
                    [settings.ffmpeg_path, "-i", str(audio_path),
                     "-af", "silencedetect=noise=-35dB:d=0.5",
                     "-f", "null", "-"],
                    capture_output=True, text=True, timeout=300,
                )
                silences: list[dict] = []
                start = None
                for line in r.stderr.splitlines():
                    if "silence_start" in line:
                        try:
                            start = float(line.split("silence_start:")[1].strip())
                        except (IndexError, ValueError):
                            pass
                    elif "silence_end" in line and start is not None:
                        try:
                            end = float(line.split("silence_end:")[1].split("|")[0].strip())
                            silences.append({"start": start, "end": end, "type": "silence"})
                            start = None
                        except (IndexError, ValueError):
                            pass
                return silences

            silence_regions = await loop.run_in_executor(None, _detect_silence)

        regions_saved = 0
        async with uow_factory() as uow:
            for region in silence_regions:
                uow.session.add(Scenes(
                    organization_id=org_id,
                    asset_id=asset_id,
                    job_id=job_id,
                    start_time=Decimal(str(region["start"])),
                    end_time=Decimal(str(region["end"])),
                    scene_label=f"silence:{region['start']:.1f}-{region['end']:.1f}",
                    confidence=Decimal("0.90"),
                ))
                regions_saved += 1

        return {"task": "music_silence", "status": "completed", "regions_detected": regions_saved}
    finally:
        await engine.dispose()


async def ner_task(job_id: UUID, asset_id: UUID) -> dict:
    """Extract named entities from transcript using GPT."""
    uow_factory, engine, settings = _make_uow_factory()
    try:
        from sqlalchemy import select
        from oki.analysis.models import TranscriptSegments
        from oki.providers.factory import create_openai_client

        client = create_openai_client(settings)
        if client is None:
            return {"task": "ner", "status": "skipped", "reason": "no_openai_configured"}

        async with uow_factory() as uow:
            segments = list(await uow.session.scalars(
                select(TranscriptSegments)
                .where(TranscriptSegments.asset_id == asset_id, TranscriptSegments.job_id == job_id)
                .order_by(TranscriptSegments.start_time)
            ))
            if not segments:
                return {"task": "ner", "status": "skipped", "reason": "no_segments"}
            org_id = segments[0].organization_id

        full_text = " ".join(s.text for s in segments[:50])[:4000]
        model = settings.azure_gpt_deployment if settings.azure_openai_endpoint else "gpt-4o-mini"

        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": (
                        "Extract named entities from this video transcript. "
                        "Return JSON: {\"entities\": [{\"text\": \"...\", \"type\": \"PERSON|ORG|PRODUCT|PLACE|BRAND\", \"confidence\": 0.9}]}\n\n"
                        f"{full_text}"
                    ),
                }],
                max_completion_tokens=1000,
                temperature=0,
                response_format={"type": "json_object"},
            )
            parsed = json.loads(resp.choices[0].message.content or "{}")
            entities = parsed.get("entities", [])
        except Exception:
            entities = []

        async with uow_factory() as uow:
            for seg in segments:
                seg_entities = [
                    e for e in entities
                    if e.get("text", "").lower() in seg.text.lower()
                ]
                if seg_entities and not seg.extra_data:
                    seg.extra_data = {"named_entities": seg_entities}
                elif seg_entities and isinstance(getattr(seg, "extra_data", None), dict):
                    seg.extra_data = {**(seg.extra_data or {}), "named_entities": seg_entities}

        return {"task": "ner", "status": "completed", "entities_found": len(entities)}
    finally:
        await engine.dispose()
