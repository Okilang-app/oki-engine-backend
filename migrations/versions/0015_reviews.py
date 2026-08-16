"""Create review packages, versions, assignments, comments, decisions, and approval presets.

Revision ID: 0015_reviews
Revises: 0014_renders
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0015_reviews"
down_revision: str | None = "0014_renders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_NO_DELETE_TABLES = (
    "review_packages",
    "review_package_versions",
    "creator_approval_presets",
)
APPEND_ONLY_TABLES = (
    "review_assignments",
    "review_comments",
    "review_decisions",
)


def _id_column() -> sa.Column[object]:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuidv7()"))


def _created_at_column() -> sa.Column[object]:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"))


def _mutable_columns() -> tuple[sa.Column[object], ...]:
    return (
        _created_at_column(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )


def _organization_column() -> sa.Column[object]:
    return sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)


def _actor_column(name: str = "created_by_user_id") -> sa.Column[object]:
    return sa.Column(name, postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "review_packages",
        _id_column(),
        _organization_column(),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        _actor_column(),
        *_mutable_columns(),
        sa.Index("ix_review_packages_job", "job_id", "created_at"),
    )

    op.create_table(
        "review_package_versions",
        _id_column(),
        _organization_column(),
        sa.Column("package_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("review_packages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("canonical_hash", sa.String(64), nullable=False),
        sa.Column("material_changed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        _actor_column(),
        *_mutable_columns(),
        sa.UniqueConstraint("package_id", "version_number", name="uq_review_package_versions_number"),
        sa.Index("ix_review_package_versions_package", "package_id", "version_number"),
    )

    op.create_table(
        "review_assignments",
        _id_column(),
        _organization_column(),
        sa.Column("package_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("review_package_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assignee_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        sa.Index("ix_review_assignments_version", "package_version_id", "assigned_at"),
    )

    op.create_table(
        "review_comments",
        _id_column(),
        _organization_column(),
        sa.Column("package_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("review_package_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("line_reference", sa.String(255), nullable=True),
        _created_at_column(),
        sa.Index("ix_review_comments_version", "package_version_id", "created_at"),
    )

    op.create_table(
        "review_decisions",
        _id_column(),
        _organization_column(),
        sa.Column("package_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("review_package_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        _created_at_column(),
        sa.CheckConstraint("decision IN ('approved', 'approved_with_comments', 'changes_requested', 'rejected')", name="ck_review_decisions_decision"),
        sa.Index("ix_review_decisions_version", "package_version_id", "decided_at"),
    )

    op.create_table(
        "creator_approval_presets",
        _id_column(),
        _organization_column(),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("creators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("language_code", sa.String(16), nullable=False),
        sa.Column("always_require_approval", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("auto_approve_up_to_version", sa.Integer(), nullable=True),
        _actor_column(),
        *_mutable_columns(),
        sa.UniqueConstraint("organization_id", "creator_id", "language_code", name="uq_creator_approval_presets_org_creator_lang"),
        sa.Index("ix_creator_approval_presets_creator", "creator_id", "language_code"),
    )

    for table in MUTABLE_NO_DELETE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APPLICATION_ROLE}")
    for table in APPEND_ONLY_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APPLICATION_ROLE}")


def downgrade() -> None:
    op.drop_table("creator_approval_presets")
    op.drop_table("review_decisions")
    op.drop_table("review_comments")
    op.drop_table("review_assignments")
    op.drop_table("review_package_versions")
    op.drop_table("review_packages")
