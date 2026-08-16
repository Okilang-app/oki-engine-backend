from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Table,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from oki.db.base import Base
from oki.db.mixins import TimestampMixin, VersionMixin
from oki.jobs.enums import (
    DeadLetterStatus,
    IdempotencyStatus,
    TaskGroup,
    TaskRunStatus,
    WorkflowEvent,
    WorkflowState,
)

# Stage 0 foundation owns the organizations schema through Alembic rather than
# an ORM identity model. Register only its key so SQLAlchemy can resolve the
# workflow models' database-enforced foreign keys during ORM flush ordering.
ORGANIZATIONS_TABLE = Table(
    "organizations",
    Base.metadata,
    Column("id", PostgreSQLUUID(as_uuid=True), primary_key=True),
)


def _enum_values(enum_type: type[Any]) -> list[str]:
    return [member.value for member in enum_type]


WORKFLOW_STATE_TYPE = Enum(
    WorkflowState,
    name="workflow_state",
    values_callable=_enum_values,
)
WORKFLOW_EVENT_TYPE = Enum(
    WorkflowEvent,
    name="workflow_event",
    values_callable=_enum_values,
)
TASK_GROUP_TYPE = Enum(TaskGroup, name="task_group", values_callable=_enum_values)
TASK_RUN_STATUS_TYPE = Enum(
    TaskRunStatus,
    name="task_run_status",
    values_callable=_enum_values,
)
DEAD_LETTER_STATUS_TYPE = Enum(
    DeadLetterStatus,
    name="dead_letter_status",
    values_callable=_enum_values,
)
IDEMPOTENCY_STATUS_TYPE = Enum(
    IdempotencyStatus,
    native_enum=False,
    create_constraint=False,
    values_callable=_enum_values,
)

NONTERMINAL_PRIMARY_STATES = tuple(
    state.value
    for state in WorkflowState
    if state
    not in {
        WorkflowState.ARCHIVED,
        WorkflowState.BLOCKED,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
        WorkflowState.RIGHTS_REVOKED,
    }
)
RESUMABLE_STATE_INVARIANT = (
    "((state IN ('BLOCKED', 'FAILED') AND resumable_state IS NOT NULL AND resumable_state IN ("
    + ", ".join(f"'{state}'" for state in NONTERMINAL_PRIMARY_STATES)
    + ")) OR (state NOT IN ('BLOCKED', 'FAILED') AND resumable_state IS NULL))"
)


class Project(TimestampMixin, VersionMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_organization_state", "organization_id", "state"),
        CheckConstraint(
            RESUMABLE_STATE_INVARIANT,
            name="ck_projects_resumable_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[WorkflowState] = mapped_column(
        WORKFLOW_STATE_TYPE,
        nullable=False,
        default=WorkflowState.CREATOR_LEAD,
        server_default=WorkflowState.CREATOR_LEAD.value,
    )
    resumable_state: Mapped[WorkflowState | None] = mapped_column(
        WORKFLOW_STATE_TYPE,
        nullable=True,
    )


class LocalizationJob(TimestampMixin, VersionMixin, Base):
    __tablename__ = "localization_jobs"
    __table_args__ = (
        Index("ix_localization_jobs_organization_state", "organization_id", "state"),
        Index("ix_localization_jobs_project", "project_id"),
        CheckConstraint(
            RESUMABLE_STATE_INVARIANT,
            name="ck_localization_jobs_resumable_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    state: Mapped[WorkflowState] = mapped_column(
        WORKFLOW_STATE_TYPE,
        nullable=False,
        default=WorkflowState.CREATOR_LEAD,
        server_default=WorkflowState.CREATOR_LEAD.value,
    )
    resumable_state: Mapped[WorkflowState | None] = mapped_column(
        WORKFLOW_STATE_TYPE,
        nullable=True,
    )


class WorkflowTransition(Base):
    __tablename__ = "workflow_transitions"
    __table_args__ = (
        Index("ix_workflow_transitions_job_created", "job_id", "created_at"),
        CheckConstraint("actor_type IN ('system', 'employee', 'creator')", name="ck_workflow_transition_actor_type"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("localization_jobs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    from_state: Mapped[WorkflowState] = mapped_column(WORKFLOW_STATE_TYPE, nullable=False)
    to_state: Mapped[WorkflowState] = mapped_column(WORKFLOW_STATE_TYPE, nullable=False)
    event: Mapped[WorkflowEvent] = mapped_column(WORKFLOW_EVENT_TYPE, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    guard_result: Mapped[bool] = mapped_column(Boolean, nullable=False)
    guard_details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    prior_resumable_state: Mapped[WorkflowState | None] = mapped_column(
        WORKFLOW_STATE_TYPE,
        nullable=True,
    )
    hatchet_workflow_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hatchet_task_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class TaskRun(TimestampMixin, VersionMixin, Base):
    __tablename__ = "task_runs"
    __table_args__ = (
        Index("ix_task_runs_job_status", "job_id", "status"),
        UniqueConstraint("hatchet_task_run_id", name="uq_task_runs_hatchet_task_run_id"),
        CheckConstraint("attempt > 0", name="ck_task_runs_attempt_positive"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("localization_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_name: Mapped[str] = mapped_column(String(150), nullable=False)
    task_group: Mapped[TaskGroup] = mapped_column(TASK_GROUP_TYPE, nullable=False)
    provider_key: Mapped[str | None] = mapped_column(String(150), nullable=True)
    creator_key: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[TaskRunStatus] = mapped_column(
        TASK_RUN_STATUS_TYPE,
        nullable=False,
        default=TaskRunStatus.PENDING,
        server_default=TaskRunStatus.PENDING.value,
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    hatchet_workflow_run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    hatchet_task_run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class TaskCheckpoint(TimestampMixin, VersionMixin, Base):
    __tablename__ = "task_checkpoints"
    __table_args__ = (
        UniqueConstraint("task_run_id", "checkpoint_key", name="uq_task_checkpoint_key"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("task_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    checkpoint_key: Mapped[str] = mapped_column(String(150), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class DeadLetter(TimestampMixin, VersionMixin, Base):
    __tablename__ = "dead_letters"
    __table_args__ = (
        Index("ix_dead_letters_organization_status", "organization_id", "status"),
        CheckConstraint("attempts > 0", name="ck_dead_letters_attempts_positive"),
        UniqueConstraint("task_run_id", name="uq_dead_letters_task_run"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("localization_jobs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    task_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("task_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    task_name: Mapped[str] = mapped_column(String(150), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    error_type: Mapped[str] = mapped_column(String(255), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DeadLetterStatus] = mapped_column(
        DEAD_LETTER_STATUS_TYPE,
        nullable=False,
        default=DeadLetterStatus.PENDING,
        server_default=DeadLetterStatus.PENDING.value,
    )
    disposition_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    hatchet_workflow_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hatchet_task_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class OutboxEvent(TimestampMixin, VersionMixin, Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_outbox_events_attempts_nonnegative"),
        Index(
            "ix_outbox_events_pending",
            "available_at",
            postgresql_where=text("published_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(150), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    headers: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProviderUsage(TimestampMixin, VersionMixin, Base):
    __tablename__ = "provider_usage"
    __table_args__ = (
        UniqueConstraint("provider", "provider_request_id", name="uq_provider_usage_request"),
        Index("ix_provider_usage_job_created", "job_id", "created_at"),
        CheckConstraint("input_units >= 0", name="ck_provider_usage_input_nonnegative"),
        CheckConstraint("output_units >= 0", name="ck_provider_usage_output_nonnegative"),
        CheckConstraint("cost_amount >= 0", name="ck_provider_usage_cost_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("localization_jobs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    task_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("task_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    operation: Mapped[str] = mapped_column(String(150), nullable=False)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_request_id: Mapped[str] = mapped_column(String(255), nullable=False)
    input_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    output_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    cost_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    usage_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IdempotencyRecord(TimestampMixin, VersionMixin, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "scope",
            "idempotency_key",
            name="uq_idempotency_records_scope_key",
        ),
        Index("ix_idempotency_records_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(String(150), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[IdempotencyStatus] = mapped_column(IDEMPOTENCY_STATUS_TYPE, nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
