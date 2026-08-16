"""Create the Stage 0 workflow kernel schema.

Revision ID: 0002_workflow_kernel
Revises: 0001_foundation
Create Date: 2026-08-14
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_workflow_kernel"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
MUTABLE_TABLES = (
    "projects",
    "localization_jobs",
    "task_runs",
    "task_checkpoints",
    "dead_letters",
    "provider_usage",
)
APPEND_ONLY_TABLES = ("workflow_transitions",)

WORKFLOW_STATES = (
    "CREATOR_LEAD",
    "RIGHTS_PENDING",
    "RIGHTS_APPROVED",
    "SOURCE_REQUESTED",
    "SOURCE_UPLOADED",
    "SOURCE_VALIDATED",
    "ANALYSIS_RUNNING",
    "AD_REVIEW_REQUIRED",
    "TRANSLATION_RUNNING",
    "TRANSLATION_REVIEW",
    "DUBBING_RUNNING",
    "AUDIO_REVIEW",
    "RENDER_RUNNING",
    "INTERNAL_QA",
    "CREATOR_REVIEW",
    "PUBLISH_READY",
    "UPLOADED_PRIVATE",
    "PLATFORM_CHECK",
    "PUBLISHED",
    "PERFORMANCE_REVIEW",
    "ARCHIVED",
    "BLOCKED",
    "FAILED",
    "CANCELLED",
    "RIGHTS_REVOKED",
)
WORKFLOW_EVENTS = (
    "REQUEST_RIGHTS",
    "APPROVE_RIGHTS",
    "REQUEST_SOURCE",
    "RECORD_SOURCE_UPLOAD",
    "VALIDATE_SOURCE",
    "START_ANALYSIS",
    "REQUIRE_AD_REVIEW",
    "START_TRANSLATION",
    "REQUEST_TRANSLATION_REVIEW",
    "START_DUBBING",
    "REQUEST_AUDIO_REVIEW",
    "START_RENDER",
    "REQUEST_INTERNAL_QA",
    "REQUEST_CREATOR_REVIEW",
    "MARK_PUBLISH_READY",
    "UPLOAD_PRIVATE",
    "COMPLETE_PLATFORM_CHECK",
    "PUBLISH_APPROVED",
    "START_PERFORMANCE_REVIEW",
    "ARCHIVE",
    "BLOCK",
    "FAIL",
    "RESUME",
    "RETRY",
    "CANCEL",
    "REVOKE_RIGHTS",
)
TASK_GROUPS = (
    "analysis",
    "translation",
    "dubbing",
    "audio",
    "render",
    "shorts",
    "publishing",
    "analytics",
    "notifications",
)
NONTERMINAL_PRIMARY_STATES = WORKFLOW_STATES[:-5]
RESUMABLE_STATE_INVARIANT = (
    "((state IN ('BLOCKED', 'FAILED') AND resumable_state IS NOT NULL AND resumable_state IN ("
    + ", ".join(f"'{state}'" for state in NONTERMINAL_PRIMARY_STATES)
    + ")) OR (state NOT IN ('BLOCKED', 'FAILED') AND resumable_state IS NULL))"
)


def _id_column() -> sa.Column[object]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("uuidv7()"),
    )


def _mutable_columns() -> tuple[sa.Column[object], ...]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )


def upgrade() -> None:
    bind = op.get_bind()
    workflow_state = postgresql.ENUM(*WORKFLOW_STATES, name="workflow_state", create_type=False)
    workflow_event = postgresql.ENUM(*WORKFLOW_EVENTS, name="workflow_event", create_type=False)
    task_group = postgresql.ENUM(*TASK_GROUPS, name="task_group", create_type=False)
    task_run_status = postgresql.ENUM(
        "pending", "running", "succeeded", "failed", "cancelled", "dead_lettered",
        name="task_run_status",
        create_type=False,
    )
    dead_letter_status = postgresql.ENUM(
        "pending", "replayed", "discarded",
        name="dead_letter_status",
        create_type=False,
    )
    for enum_type in (
        workflow_state,
        workflow_event,
        task_group,
        task_run_status,
        dead_letter_status,
    ):
        enum_type.create(bind, checkfirst=False)

    op.create_table(
        "projects",
        _id_column(),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "state", workflow_state, nullable=False, server_default="CREATOR_LEAD"
        ),
        sa.Column("resumable_state", workflow_state, nullable=True),
        *_mutable_columns(),
        sa.CheckConstraint(
            RESUMABLE_STATE_INVARIANT,
            name="ck_projects_resumable_state",
        ),
    )
    op.create_index(
        "ix_projects_organization_state", "projects", ["organization_id", "state"]
    )

    op.create_table(
        "localization_jobs",
        _id_column(),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "state", workflow_state, nullable=False, server_default="CREATOR_LEAD"
        ),
        sa.Column("resumable_state", workflow_state, nullable=True),
        *_mutable_columns(),
        sa.CheckConstraint(
            RESUMABLE_STATE_INVARIANT,
            name="ck_localization_jobs_resumable_state",
        ),
    )
    op.create_index(
        "ix_localization_jobs_organization_state",
        "localization_jobs",
        ["organization_id", "state"],
    )
    op.create_index(
        "ix_localization_jobs_project", "localization_jobs", ["project_id"]
    )

    op.create_table(
        "workflow_transitions",
        _id_column(),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("localization_jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("from_state", workflow_state, nullable=False),
        sa.Column("to_state", workflow_state, nullable=False),
        sa.Column("event", workflow_event, nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("guard_result", sa.Boolean(), nullable=False),
        sa.Column(
            "guard_details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prior_resumable_state", workflow_state, nullable=True),
        sa.Column("hatchet_workflow_run_id", sa.String(length=255), nullable=True),
        sa.Column("hatchet_task_run_id", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('system', 'employee', 'creator')",
            name="ck_workflow_transition_actor_type",
        ),
    )
    op.create_index(
        "ix_workflow_transitions_job_created",
        "workflow_transitions",
        ["job_id", "created_at"],
    )

    op.create_table(
        "task_runs",
        _id_column(),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("localization_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_name", sa.String(length=150), nullable=False),
        sa.Column("task_group", task_group, nullable=False),
        sa.Column("provider_key", sa.String(length=150), nullable=True),
        sa.Column("creator_key", sa.String(length=150), nullable=False),
        sa.Column(
            "status", task_run_status, nullable=False, server_default="pending"
        ),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("hatchet_workflow_run_id", sa.String(length=255), nullable=False),
        sa.Column("hatchet_task_run_id", sa.String(length=255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        *_mutable_columns(),
        sa.CheckConstraint("attempt > 0", name="ck_task_runs_attempt_positive"),
        sa.UniqueConstraint(
            "hatchet_task_run_id", name="uq_task_runs_hatchet_task_run_id"
        ),
    )
    op.create_index("ix_task_runs_job_status", "task_runs", ["job_id", "status"])

    op.create_table(
        "task_checkpoints",
        _id_column(),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("checkpoint_key", sa.String(length=150), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_mutable_columns(),
        sa.UniqueConstraint(
            "task_run_id", "checkpoint_key", name="uq_task_checkpoint_key"
        ),
    )

    op.create_table(
        "dead_letters",
        _id_column(),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("localization_jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "task_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("task_name", sa.String(length=150), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_type", sa.String(length=255), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "status", dead_letter_status, nullable=False, server_default="pending"
        ),
        sa.Column("disposition_reason", sa.Text(), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hatchet_workflow_run_id", sa.String(length=255), nullable=True),
        sa.Column("hatchet_task_run_id", sa.String(length=255), nullable=True),
        *_mutable_columns(),
        sa.CheckConstraint("attempts > 0", name="ck_dead_letters_attempts_positive"),
        sa.UniqueConstraint("task_run_id", name="uq_dead_letters_task_run"),
    )
    op.create_index(
        "ix_dead_letters_organization_status",
        "dead_letters",
        ["organization_id", "status"],
    )

    op.create_table(
        "provider_usage",
        _id_column(),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("localization_jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "task_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("operation", sa.String(length=150), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("provider_request_id", sa.String(length=255), nullable=False),
        sa.Column("input_units", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_units", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cost_amount", sa.Numeric(20, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "usage_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_mutable_columns(),
        sa.CheckConstraint("input_units >= 0", name="ck_provider_usage_input_nonnegative"),
        sa.CheckConstraint("output_units >= 0", name="ck_provider_usage_output_nonnegative"),
        sa.CheckConstraint("cost_amount >= 0", name="ck_provider_usage_cost_nonnegative"),
        sa.UniqueConstraint(
            "provider", "provider_request_id", name="uq_provider_usage_request"
        ),
    )
    op.create_index(
        "ix_provider_usage_job_created", "provider_usage", ["job_id", "created_at"]
    )

    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APPLICATION_ROLE}') THEN
                EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
                    {", ".join(MUTABLE_TABLES)} TO {APPLICATION_ROLE}';
                EXECUTE 'GRANT SELECT, INSERT ON TABLE
                    {", ".join(APPEND_ONLY_TABLES)} TO {APPLICATION_ROLE}';
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    for table_name in (
        "provider_usage",
        "dead_letters",
        "task_checkpoints",
        "task_runs",
        "workflow_transitions",
        "localization_jobs",
        "projects",
    ):
        op.drop_table(table_name)

    bind = op.get_bind()
    for name in (
        "dead_letter_status",
        "task_run_status",
        "task_group",
        "workflow_event",
        "workflow_state",
    ):
        postgresql.ENUM(name=name).drop(bind, checkfirst=False)
