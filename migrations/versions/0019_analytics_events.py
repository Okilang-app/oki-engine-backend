"""Create analytics tables: metric points, conversion events, attribution links, ingestion runs, cost ledger.

Revision ID: 0019_analytics_events
Revises: 0018_shorts
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0019_analytics_events"
down_revision: str | None = "0018_shorts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_NO_DELETE_TABLES = (
    "youtube_metric_points",
    "oki_conversion_events",
    "attribution_links",
    "metric_ingestion_runs",
    "cost_ledger_entries",
)
APPEND_ONLY_TABLES = ()


def _id_column() -> sa.Column[object]:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuidv7()"))


def _created_at_column() -> sa.Column[object]:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"))


def _organization_column() -> sa.Column[object]:
    return sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "youtube_metric_points",
        _id_column(),
        _organization_column(),
        sa.Column("video_id", sa.String(64), nullable=False),
        sa.Column("metric_type", sa.String(64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("dimensions", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        _created_at_column(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Index("ix_youtube_metric_points_org_video_metric", "organization_id", "video_id", "metric_type"),
        sa.Index("ix_youtube_metric_points_captured_at", "captured_at"),
    )

    op.create_table(
        "oki_conversion_events",
        _id_column(),
        _organization_column(),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("attributed_creator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creators.id", ondelete="SET NULL"), nullable=True),
        sa.Column("attributed_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("attributed_language", sa.String(16), nullable=True),
        sa.Column("attributed_campaign_id", sa.String(64), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(8), nullable=True),
        sa.Column("event_metadata", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        _created_at_column(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Index("ix_oki_conversion_events_org_type", "organization_id", "event_type"),
        sa.Index("ix_oki_conversion_events_occurred_at", "occurred_at"),
    )

    op.create_table(
        "attribution_links",
        _id_column(),
        _organization_column(),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("oki_conversion_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("link_token", sa.String(512), nullable=False),
        sa.Column("landing_url", sa.String(2048), nullable=False),
        _created_at_column(),
        sa.Index("ix_attribution_links_event_id", "event_id"),
        sa.Index("ix_attribution_links_link_token", "link_token"),
    )

    op.create_table(
        "metric_ingestion_runs",
        _id_column(),
        _organization_column(),
        sa.Column("run_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("records_processed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Index("ix_metric_ingestion_runs_org_status", "organization_id", "status"),
    )

    op.create_table(
        "cost_ledger_entries",
        _id_column(),
        _organization_column(),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("cost_category", sa.String(64), nullable=False),
        sa.Column("amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("incurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("description", sa.Text(), nullable=True),
        _created_at_column(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Index("ix_cost_ledger_entries_org_job", "organization_id", "job_id"),
        sa.Index("ix_cost_ledger_entries_incurred_at", "incurred_at"),
    )

    for table in MUTABLE_NO_DELETE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APPLICATION_ROLE}")


def downgrade() -> None:
    op.drop_table("cost_ledger_entries")
    op.drop_table("metric_ingestion_runs")
    op.drop_table("attribution_links")
    op.drop_table("oki_conversion_events")
    op.drop_table("youtube_metric_points")
