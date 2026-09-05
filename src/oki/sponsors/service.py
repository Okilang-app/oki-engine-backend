from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import select

from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.sponsors.enums import DetectionReason, ReplacementType, SponsorStatus
from oki.sponsors.models import AdSegmentEvidence, AdSegmentReviews, AdSegments
from oki.sponsors.schemas import (
    SponsorCandidateResponse,
    SponsorDecisionResponse,
    ManualSponsorCreateRequest,
    ManualSponsorUpdateRequest,
)
from oki.jobs.models import LocalizationJob
from oki.assets.models import SourceAsset


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SponsorDetectionService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], authorizer: Authorizer) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer

    async def detect(
        self,
        principal: Principal,
        job_id: UUID,
    ) -> list[SponsorCandidateResponse]:
        """Return sponsor candidates for a job from the database."""
        async with self._uow_factory() as uow:
            job = await uow.session.scalar(
                select(LocalizationJob)
                .where(LocalizationJob.id == job_id)
            )
            if job is None:
                self._not_found("job_not_found", "Localization job not found")
            organization_id = job.organization_id
            self._authorizer.require(
                principal,
                Action.PROJECT_READ,
                self._scope(organization_id),
            )

            ad_segments = await uow.session.scalars(
                select(AdSegments)
                .where(AdSegments.job_id == job_id)
                .order_by(AdSegments.start_time)
            )

            # Pre-fetch ad names for proposed replacements
            from oki.ads.models import InternalAd
            ad_ids = [seg.proposed_replacement_ad_id for seg in ad_segments if seg.proposed_replacement_ad_id]
            ad_map: dict[UUID, str] = {}
            if ad_ids:
                ads = await uow.session.scalars(
                    select(InternalAd).where(InternalAd.id.in_(ad_ids))
                )
                for ad in ads:
                    ad_map[ad.id] = ad.name

            # Re-query because generator was consumed
            ad_segments_all = list(await uow.session.scalars(
                select(AdSegments)
                .where(AdSegments.job_id == job_id)
                .order_by(AdSegments.start_time)
            ))

            # Load evidence in batch for detection reason + confidence
            seg_ids = [seg.id for seg in ad_segments_all]
            evidence_map: dict[UUID, AdSegmentEvidence] = {}
            if seg_ids:
                evidence_rows = await uow.session.scalars(
                    select(AdSegmentEvidence).where(AdSegmentEvidence.ad_segment_id.in_(seg_ids))
                )
                for ev in evidence_rows:
                    # manual evidence wins if present; otherwise keep first
                    if ev.ad_segment_id not in evidence_map or ev.evidence_type == DetectionReason.MANUAL:
                        evidence_map[ev.ad_segment_id] = ev

            candidates: list[SponsorCandidateResponse] = []
            for seg in ad_segments_all:
                ev = evidence_map.get(seg.id)
                candidates.append(
                    SponsorCandidateResponse(
                        id=seg.id,
                        job_id=seg.job_id,
                        asset_id=seg.asset_id,
                        start_time=float(seg.start_time),
                        end_time=float(seg.end_time),
                        sponsor_name=seg.sponsor_name,
                        status=seg.status.value,
                        detection_reason=ev.evidence_type if ev else DetectionReason.KEYWORD,
                        confidence=float(ev.confidence) if ev and ev.confidence is not None else None,
                        replacement_type=seg.replacement_type,
                        proposed_replacement_ad_id=seg.proposed_replacement_ad_id,
                        proposed_replacement_ad_name=ad_map.get(seg.proposed_replacement_ad_id),
                        created_at=seg.created_at,
                        updated_at=seg.updated_at,
                    )
                )
            return candidates

    @staticmethod
    def _not_found(code: str, title: str) -> NoReturn:
        raise ProblemException(
            status_code=404,
            code=code,
            title=title,
            detail=f"The requested {title.lower()} does not exist.",
        )

    @staticmethod
    def _scope(organization_id: UUID) -> ResourceScope:
        return ResourceScope(organization_id=organization_id)


class SponsorReviewService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], authorizer: Authorizer) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer

    async def adjust(
        self,
        principal: Principal,
        segment_id: UUID,
        boundaries_start: float | None = None,
        boundaries_end: float | None = None,
        reason: str | None = None,
    ) -> AdSegmentReviews:
        """Record an adjustment review on an ad segment."""
        async with self._uow_factory() as uow:
            ad_segment = await uow.session.get(AdSegments, segment_id)
            if ad_segment is None:
                self._not_found("ad_segment_not_found", "Ad segment not found")
            self._authorizer.require(
                principal,
                Action.SPONSOR_REPLACE,
                self._scope(ad_segment.organization_id),
            )
            if boundaries_start is not None:
                ad_segment.start_time = boundaries_start
            if boundaries_end is not None:
                ad_segment.end_time = boundaries_end
            review = AdSegmentReviews(
                organization_id=ad_segment.organization_id,
                ad_segment_id=ad_segment.id,
                decision="adjust",
                boundaries_start=boundaries_start,
                boundaries_end=boundaries_end,
                reason=reason,
                reviewed_by_user_id=principal.user_id,
            )
            uow.session.add(review)
            await uow.session.flush()
            return review

    async def approve(
        self,
        principal: Principal,
        segment_id: UUID,
        reason: str | None = None,
    ) -> AdSegments:
        """Approve a detected or proposed ad segment."""
        async with self._uow_factory() as uow:
            ad_segment = await uow.session.get(AdSegments, segment_id)
            if ad_segment is None:
                self._not_found("ad_segment_not_found", "Ad segment not found")
            self._authorizer.require(
                principal,
                Action.SPONSOR_REPLACE,
                self._scope(ad_segment.organization_id),
            )
            # If a replacement was proposed, approving becomes "replaced"
            if ad_segment.status == SponsorStatus.PROPOSED and ad_segment.proposed_replacement_ad_id:
                ad_segment.status = SponsorStatus.REPLACED
            else:
                ad_segment.status = SponsorStatus.CONFIRMED
            ad_segment.reviewed_by_user_id = principal.user_id
            ad_segment.reviewed_at = datetime.now(timezone.utc)
            review = AdSegmentReviews(
                organization_id=ad_segment.organization_id,
                ad_segment_id=ad_segment.id,
                decision="approve",
                boundaries_start=None,
                boundaries_end=None,
                reason=reason,
                reviewed_by_user_id=principal.user_id,
            )
            uow.session.add(review)
            await uow.session.flush()
            return ad_segment

    async def reject(
        self,
        principal: Principal,
        segment_id: UUID,
        reason: str | None = None,
    ) -> AdSegments:
        """Reject a detected ad segment."""
        async with self._uow_factory() as uow:
            ad_segment = await uow.session.get(AdSegments, segment_id)
            if ad_segment is None:
                self._not_found("ad_segment_not_found", "Ad segment not found")
            self._authorizer.require(
                principal,
                Action.SPONSOR_REPLACE,
                self._scope(ad_segment.organization_id),
            )
            ad_segment.status = SponsorStatus.REJECTED
            ad_segment.reviewed_by_user_id = principal.user_id
            ad_segment.reviewed_at = datetime.now(timezone.utc)
            review = AdSegmentReviews(
                organization_id=ad_segment.organization_id,
                ad_segment_id=ad_segment.id,
                decision="reject",
                boundaries_start=None,
                boundaries_end=None,
                reason=reason,
                reviewed_by_user_id=principal.user_id,
            )
            uow.session.add(review)
            await uow.session.flush()
            return ad_segment

    async def create_manual(
        self,
        principal: Principal,
        job_id: UUID,
        payload: ManualSponsorCreateRequest,
    ) -> AdSegments:
        """Create a manually-marked ad segment for a job."""
        async with self._uow_factory() as uow:
            job = await uow.session.get(LocalizationJob, job_id)
            if job is None:
                self._not_found("job_not_found", "Localization job not found")
            self._authorizer.require(
                principal,
                Action.SPONSOR_REPLACE,
                self._scope(job.organization_id),
            )
            asset = await uow.session.scalar(
                select(SourceAsset)
                .where(
                    (SourceAsset.localization_job_id == job_id)
                    | (SourceAsset.project_id == job.project_id)
                )
            )
            if asset is None:
                self._not_found("asset_not_found", "No source asset linked to this job")
            asset_id = asset.id

            segment = AdSegments(
                organization_id=job.organization_id,
                asset_id=asset_id,
                job_id=job_id,
                start_time=payload.start_time,
                end_time=payload.end_time,
                sponsor_name=payload.sponsor_name,
                status=SponsorStatus.CONFIRMED,
                replacement_type=payload.replacement_type,
                reviewed_by_user_id=principal.user_id,
                reviewed_at=datetime.now(timezone.utc),
            )
            uow.session.add(segment)
            await uow.session.flush()

            evidence = AdSegmentEvidence(
                organization_id=job.organization_id,
                ad_segment_id=segment.id,
                evidence_type=DetectionReason.MANUAL,
                confidence=None,
                evidence_data={"created_by": str(principal.user_id)},
            )
            uow.session.add(evidence)
            await uow.session.flush()
            return segment

    async def update_manual(
        self,
        principal: Principal,
        segment_id: UUID,
        payload: ManualSponsorUpdateRequest,
    ) -> AdSegments:
        """Update a manually-created ad segment."""
        async with self._uow_factory() as uow:
            segment = await uow.session.get(AdSegments, segment_id)
            if segment is None:
                self._not_found("ad_segment_not_found", "Ad segment not found")
            self._authorizer.require(
                principal,
                Action.SPONSOR_REPLACE,
                self._scope(segment.organization_id),
            )
            if payload.start_time is not None:
                segment.start_time = payload.start_time
            if payload.end_time is not None:
                segment.end_time = payload.end_time
            if payload.sponsor_name is not None:
                segment.sponsor_name = payload.sponsor_name
            if payload.replacement_type is not None:
                segment.replacement_type = payload.replacement_type
            segment.updated_at = datetime.now(timezone.utc)
            await uow.session.flush()
            return segment

    async def delete_manual(
        self,
        principal: Principal,
        segment_id: UUID,
    ) -> None:
        """Delete an ad segment (manual or auto-detected)."""
        async with self._uow_factory() as uow:
            segment = await uow.session.get(AdSegments, segment_id)
            if segment is None:
                self._not_found("ad_segment_not_found", "Ad segment not found")
            self._authorizer.require(
                principal,
                Action.SPONSOR_REPLACE,
                self._scope(segment.organization_id),
            )
            await uow.session.delete(segment)
            await uow.session.flush()

    @staticmethod
    def _not_found(code: str, title: str) -> NoReturn:
        raise ProblemException(
            status_code=404,
            code=code,
            title=title,
            detail=f"The requested {title.lower()} does not exist.",
        )

    @staticmethod
    def _scope(organization_id: UUID) -> ResourceScope:
        return ResourceScope(organization_id=organization_id)



