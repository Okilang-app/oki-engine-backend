from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from oki.db.base import Base
from oki.creators.models import CreatedAtMixin
from oki.db.mixins import TimestampMixin
from oki.identity import models as _identity_models  # noqa: F401
from oki.jobs import models as _jobs_models  # noqa: F401


class YoutubeMetricPoints(TimestampMixin, Base):
    __tablename__ = "youtube_metric_points"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    video_id: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_type: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_youtube_metric_points_org_video_metric",
            organization_id,
            video_id,
            metric_type,
        ),
        Index(
            "ix_youtube_metric_points_captured_at",
            captured_at,
        ),
    )


class OkiConversionEvents(TimestampMixin, Base):
    __tablename__ = "oki_conversion_events"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    attributed_creator_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("creators.id", ondelete="SET NULL"),
        nullable=True,
    )
    attributed_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("localization_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    attributed_language: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    attributed_campaign_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_oki_conversion_events_org_type",
            organization_id,
            event_type,
        ),
        Index(
            "ix_oki_conversion_events_occurred_at",
            occurred_at,
        ),
    )


class AttributionLinks(CreatedAtMixin, Base):
    __tablename__ = "attribution_links"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("oki_conversion_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    link_token: Mapped[str] = mapped_column(String(512), nullable=False)
    landing_url: Mapped[str] = mapped_column(String(2048), nullable=False)

    __table_args__ = (
        Index(
            "ix_attribution_links_event_id",
            event_id,
        ),
        Index(
            "ix_attribution_links_link_token",
            link_token,
        ),
    )


class MetricIngestionRuns(TimestampMixin, Base):
    __tablename__ = "metric_ingestion_runs"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    records_processed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "ix_metric_ingestion_runs_org_status",
            organization_id,
            status,
        ),
    )


class CostLedgerEntries(TimestampMixin, Base):
    __tablename__ = "cost_ledger_entries"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("localization_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    cost_category: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=19, scale=4),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    incurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "ix_cost_ledger_entries_org_job",
            organization_id,
            job_id,
        ),
        Index(
            "ix_cost_ledger_entries_incurred_at",
            incurred_at,
        ),
    )
