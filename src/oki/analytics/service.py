from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select

from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.analytics.attribution import AttributionService
from oki.analytics.models import (
    CostLedgerEntries,
    MetricIngestionRuns,
    OkiConversionEvents,
    YoutubeMetricPoints,
)
from oki.analytics.oki_events import OkiEventIngestor
from oki.analytics.queries import (
    campaign_metrics_query,
    creator_metrics_query,
    language_metrics_query,
    video_metrics_query,
)
from oki.analytics.reports import DailyProductionReport, WeeklyManagementReport
from oki.analytics.youtube import YoutubeAnalyticsIngestor


class AnalyticsService:
    """Orchestrates analytics queries, ingestion, attribution, and reporting."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        authorizer: Authorizer,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer
        self.youtube_ingestor = YoutubeAnalyticsIngestor()
        self.oki_event_ingestor = OkiEventIngestor()
        self.attribution_service = AttributionService(uow_factory)
        self.daily_report = DailyProductionReport()
        self.weekly_report = WeeklyManagementReport()

    # ------------------------------------------------------------------ #
    # Dashboard queries
    # ------------------------------------------------------------------ #

    async def get_creator_metrics(
        self,
        principal: Principal,
        organization_id: UUID,
    ) -> list[dict[str, Any]]:
        self._authorizer.require(
            principal,
            Action.AUDIT_READ,
            self._scope(organization_id),
        )
        async with self._uow_factory() as uow:
            stmt = creator_metrics_query(organization_id)
            result = await uow.session.execute(stmt)
            rows = result.mappings().all()
            return [dict(row) for row in rows]

    async def get_video_metrics(
        self,
        principal: Principal,
        organization_id: UUID,
    ) -> list[dict[str, Any]]:
        self._authorizer.require(
            principal,
            Action.AUDIT_READ,
            self._scope(organization_id),
        )
        async with self._uow_factory() as uow:
            stmt = video_metrics_query(organization_id)
            result = await uow.session.execute(stmt)
            rows = result.mappings().all()
            return [dict(row) for row in rows]

    async def get_language_metrics(
        self,
        principal: Principal,
        organization_id: UUID,
    ) -> list[dict[str, Any]]:
        self._authorizer.require(
            principal,
            Action.AUDIT_READ,
            self._scope(organization_id),
        )
        async with self._uow_factory() as uow:
            stmt = language_metrics_query(organization_id)
            result = await uow.session.execute(stmt)
            rows = result.mappings().all()
            return [dict(row) for row in rows]

    async def get_campaign_metrics(
        self,
        principal: Principal,
        organization_id: UUID,
    ) -> list[dict[str, Any]]:
        self._authorizer.require(
            principal,
            Action.AUDIT_READ,
            self._scope(organization_id),
        )
        async with self._uow_factory() as uow:
            stmt = campaign_metrics_query(organization_id)
            result = await uow.session.execute(stmt)
            rows = result.mappings().all()
            return [dict(row) for row in rows]

    async def get_oki_conversions(
        self,
        principal: Principal,
        organization_id: UUID,
    ) -> list[OkiConversionEvents]:
        self._authorizer.require(
            principal,
            Action.AUDIT_READ,
            self._scope(organization_id),
        )
        async with self._uow_factory() as uow:
            stmt = (
                select(OkiConversionEvents)
                .where(OkiConversionEvents.organization_id == organization_id)
                .order_by(OkiConversionEvents.occurred_at.desc())
            )
            result = await uow.session.scalars(stmt)
            return result.all()

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _scope(organization_id: UUID) -> ResourceScope:
        return ResourceScope(
            organization_id=organization_id,
            creator_organization_id=organization_id,
        )

    @staticmethod
    def _not_found(code: str, title: str) -> None:
        raise ProblemException(
            status_code=404,
            code=code,
            title=title,
            detail=f"The requested {title.lower()} does not exist.",
        )
