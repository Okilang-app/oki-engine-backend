"""Dashboard query builders returning SQLAlchemy select objects."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from oki.analytics.models import (
    CostLedgerEntries,
    OkiConversionEvents,
    YoutubeMetricPoints,
)
from oki.creators.models import Creator
from oki.jobs.models import LocalizationJob


def creator_metrics_query(organization_id: UUID | None = None):
    """Build a select statement for creator aggregate metrics.

    Returns:
        A SQLAlchemy Select object that aggregates by creator.
    """
    stmt = (
        select(
            Creator.id.label("creator_id"),
            func.coalesce(func.sum(YoutubeMetricPoints.value), 0).label("total_views"),
            func.coalesce(func.sum(OkiConversionEvents.value), 0).label("total_revenue"),
        )
        .outerjoin(
            OkiConversionEvents,
            Creator.id == OkiConversionEvents.attributed_creator_id,
        )
        .outerjoin(
            YoutubeMetricPoints,
            Creator.id == YoutubeMetricPoints.organization_id,
        )
        .group_by(Creator.id)
    )
    if organization_id is not None:
        stmt = stmt.where(Creator.organization_id == organization_id)
    return stmt


def video_metrics_query(organization_id: UUID | None = None):
    """Build a select statement for video aggregate metrics.

    Returns:
        A SQLAlchemy Select object that aggregates by video.
    """
    stmt = (
        select(
            YoutubeMetricPoints.video_id.label("video_id"),
            func.coalesce(func.sum(YoutubeMetricPoints.value), 0).label("views"),
            func.literal(0.0).label("watch_time"),
            func.literal(0.0).label("ctr"),
            YoutubeMetricPoints.dimensions["language"].label("language"),
        )
        .where(YoutubeMetricPoints.metric_type == "views")
        .group_by(YoutubeMetricPoints.video_id, YoutubeMetricPoints.dimensions)
    )
    if organization_id is not None:
        stmt = stmt.where(YoutubeMetricPoints.organization_id == organization_id)
    return stmt


def language_metrics_query(organization_id: UUID | None = None):
    """Build a select statement for language breakdown metrics.

    Returns:
        A SQLAlchemy Select object that aggregates by language.
    """
    stmt = (
        select(
            YoutubeMetricPoints.dimensions["language"].label("language_code"),
            func.coalesce(func.sum(YoutubeMetricPoints.value), 0).label("total_views"),
            func.coalesce(func.sum(OkiConversionEvents.value), 0).label("total_revenue"),
        )
        .outerjoin(
            OkiConversionEvents,
            YoutubeMetricPoints.organization_id == OkiConversionEvents.organization_id,
        )
        .group_by(YoutubeMetricPoints.dimensions["language"])
    )
    if organization_id is not None:
        stmt = stmt.where(YoutubeMetricPoints.organization_id == organization_id)
    return stmt


def campaign_metrics_query(organization_id: UUID | None = None):
    """Build a select statement for campaign aggregate metrics.

    Returns:
        A SQLAlchemy Select object that aggregates by campaign.
    """
    stmt = (
        select(
            OkiConversionEvents.attributed_campaign_id.label("campaign_id"),
            func.count(OkiConversionEvents.id).label("impressions"),
            func.coalesce(func.count(OkiConversionEvents.id), 0).label("conversions"),
            func.coalesce(func.sum(CostLedgerEntries.amount), Decimal("0.00")).label("cost"),
            func.literal(0.0).label("roi"),
        )
        .outerjoin(
            CostLedgerEntries,
            OkiConversionEvents.attributed_campaign_id == CostLedgerEntries.description,
        )
        .group_by(OkiConversionEvents.attributed_campaign_id)
    )
    if organization_id is not None:
        stmt = stmt.where(OkiConversionEvents.organization_id == organization_id)
    return stmt
