from collections.abc import Callable
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import select, text

from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.analysis.models import (
    AnalysisRevisions,
    AudioRegions,
    NamedEntities,
    OcrSpans,
    SafetyLabels,
    Scenes,
    Speakers,
    TranscriptSegments,
    TranscriptWords,
)
from oki.analysis.schemas import TimelineItem, TimelineResponse
from oki.jobs.models import LocalizationJob


class AnalysisService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], authorizer: Authorizer) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer

    async def start(self, principal: Principal, analysis_id: UUID) -> dict[str, Any]:
        """Start analysis pipeline for the given localization job.

        TODO: wire to Hatchet task dispatch for transcription, diarization,
        scene detection, OCR, and sponsor candidate detection.
        """
        async with self._uow_factory() as uow:
            # Verify job exists via lightweight query
            job = await uow.session.scalar(
                select(LocalizationJob)
                .where(LocalizationJob.id == analysis_id)
            )
            if job is None:
                self._not_found("job_not_found", "Localization job not found")
            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                self._scope(principal, organization_id=job.organization_id),
            )
            return {
                "analysis_id": str(analysis_id),
                "status": "started",
                "tasks": [
                    "transcription",
                    "diarization",
                    "scene_detection",
                    "ocr",
                    "sponsor_candidate_detection",
                ],
            }

    async def get_timeline(self, principal: Principal, asset_id: UUID) -> TimelineResponse:
        """Return a unified timeline of segments, scenes, OCR, audio regions, and safety labels."""
        async with self._uow_factory() as uow:
            # Authorization scoped to asset (organization inferred from asset row)
            result = await uow.session.execute(
                text("select organization_id from source_assets where id = :id"),
                {"id": asset_id},
            )
            asset_org = result.scalar_one_or_none()
            if asset_org is None:
                self._not_found("asset_not_found", "Asset not found")
            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                self._scope(principal, organization_id=asset_org),
            )
            items: list[TimelineItem] = []

            segments = await uow.session.scalars(
                select(TranscriptSegments)
                .where(TranscriptSegments.asset_id == asset_id)
                .order_by(TranscriptSegments.start_time)
            )
            for seg in segments:
                items.append(
                    TimelineItem(
                        start_time=float(seg.start_time),
                        end_time=float(seg.end_time),
                        type="segment",
                        label=seg.text[:120],
                        data={
                            "segment_id": str(seg.id),
                            "language_code": seg.language_code,
                            "speaker_id": str(seg.speaker_id) if seg.speaker_id else None,
                            "confidence": float(seg.confidence) if seg.confidence else None,
                        },
                    )
                )

            scenes = await uow.session.scalars(
                select(Scenes)
                .where(Scenes.asset_id == asset_id)
                .order_by(Scenes.start_time)
            )
            for scene in scenes:
                items.append(
                    TimelineItem(
                        start_time=float(scene.start_time),
                        end_time=float(scene.end_time),
                        type="scene",
                        label=scene.scene_label,
                        data={
                            "scene_id": str(scene.id),
                            "description": scene.description,
                            "confidence": float(scene.confidence) if scene.confidence else None,
                        },
                    )
                )

            ocr_spans = await uow.session.scalars(
                select(OcrSpans)
                .where(OcrSpans.asset_id == asset_id)
                .order_by(OcrSpans.start_time)
            )
            for ocr in ocr_spans:
                items.append(
                    TimelineItem(
                        start_time=float(ocr.start_time),
                        end_time=float(ocr.end_time),
                        type="ocr",
                        label=ocr.text[:120],
                        data={
                            "ocr_id": str(ocr.id),
                            "bounding_box": ocr.bounding_box,
                            "confidence": float(ocr.confidence) if ocr.confidence else None,
                        },
                    )
                )

            audio_regions = await uow.session.scalars(
                select(AudioRegions)
                .where(AudioRegions.asset_id == asset_id)
                .order_by(AudioRegions.start_time)
            )
            for region in audio_regions:
                items.append(
                    TimelineItem(
                        start_time=float(region.start_time),
                        end_time=float(region.end_time),
                        type="audio_region",
                        label=region.region_type,
                        data={
                            "region_id": str(region.id),
                            "features": region.features,
                            "confidence": float(region.confidence) if region.confidence else None,
                        },
                    )
                )

            safety_labels = await uow.session.scalars(
                select(SafetyLabels)
                .where(SafetyLabels.asset_id == asset_id)
                .order_by(SafetyLabels.start_time)
            )
            for label in safety_labels:
                items.append(
                    TimelineItem(
                        start_time=float(label.start_time) if label.start_time else 0.0,
                        end_time=float(label.end_time) if label.end_time else 0.0,
                        type="safety_label",
                        label=label.label,
                        data={
                            "safety_id": str(label.id),
                            "severity": label.severity,
                            "description": label.description,
                            "confidence": float(label.confidence) if label.confidence else None,
                        },
                    )
                )

            # Sort by start_time
            items.sort(key=lambda i: (i.start_time, i.end_time))
            return TimelineResponse(asset_id=asset_id, items=items)

    async def get_timeline_by_job(
        self,
        principal: Principal,
        job_id: UUID,
    ) -> TimelineResponse:
        """Return a timeline for a job by querying transcript segments directly."""
        async with self._uow_factory() as uow:
            job = await uow.session.scalar(
                select(LocalizationJob)
                .where(LocalizationJob.id == job_id)
            )
            if job is None:
                self._not_found("job_not_found", "Localization job not found")
            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                self._scope(principal, organization_id=job.organization_id),
            )
            items: list[TimelineItem] = []
            segments = await uow.session.scalars(
                select(TranscriptSegments)
                .where(TranscriptSegments.job_id == job_id)
                .order_by(TranscriptSegments.start_time)
            )
            for seg in segments:
                items.append(
                    TimelineItem(
                        start_time=float(seg.start_time),
                        end_time=float(seg.end_time),
                        type="segment",
                        label=seg.text[:120],
                        data={
                            "segment_id": str(seg.id),
                            "language_code": seg.language_code,
                            "speaker_id": str(seg.speaker_id) if seg.speaker_id else None,
                            "confidence": float(seg.confidence) if seg.confidence else None,
                        },
                    )
                )
            items.sort(key=lambda i: (i.start_time, i.end_time))
            return TimelineResponse(asset_id=job_id, items=items)

    async def revise_transcript_segment(
        self,
        principal: Principal,
        segment_id: UUID,
        new_text: str,
        reason: str | None = None,
    ) -> AnalysisRevisions:
        """Record a transcript segment revision and update the segment text."""
        async with self._uow_factory() as uow:
            segment = await uow.session.scalar(
                select(TranscriptSegments)
                .where(TranscriptSegments.id == segment_id)
                .with_for_update()
            )
            if segment is None:
                self._not_found("segment_not_found", "Transcript segment not found")
            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                self._scope(principal, organization_id=segment.organization_id),
            )
            previous = {"text": segment.text}
            segment.text = new_text
            segment.version += 1
            revision = AnalysisRevisions(
                organization_id=segment.organization_id,
                asset_id=segment.asset_id,
                job_id=segment.job_id,
                segment_id=segment.id,
                revision_type="transcript_segment_text",
                previous_value=previous,
                new_value={"text": new_text, "reason": reason},
                created_by_user_id=principal.user_id,
            )
            uow.session.add(revision)
            await uow.session.flush()
            return revision

    @staticmethod
    def _scope(principal: Principal, *, organization_id: UUID | None = None) -> ResourceScope:
        return ResourceScope(
            organization_id=organization_id or principal.memberships[0].organization_id,
        )

    @staticmethod
    def _not_found(code: str, title: str) -> NoReturn:
        raise ProblemException(
            status_code=404,
            code=code,
            title=title,
            detail=f"The requested {title.lower()} does not exist.",
        )
