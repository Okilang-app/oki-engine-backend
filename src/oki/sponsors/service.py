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
from oki.sponsors.enums import DetectionReason, SponsorStatus
from oki.sponsors.models import AdSegmentEvidence, AdSegmentReviews, AdSegments
from oki.sponsors.schemas import SponsorCandidateResponse, SponsorDecisionResponse
from oki.jobs.models import LocalizationJob


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
            ad_segments = await uow.session.scalars(
                select(AdSegments)
                .where(AdSegments.job_id == job_id)
                .order_by(AdSegments.start_time)
            )

            candidates: list[SponsorCandidateResponse] = []
            for seg in ad_segments:
                candidates.append(
                    SponsorCandidateResponse(
                        id=seg.id,
                        job_id=seg.job_id,
                        asset_id=seg.asset_id,
                        start_time=float(seg.start_time),
                        end_time=float(seg.end_time),
                        sponsor_name=seg.sponsor_name,
                        status=seg.status.value,
                        detection_reason=DetectionReason.KEYWORD,
                        confidence=0.75,
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



