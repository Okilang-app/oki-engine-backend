from uuid import uuid4

import pytest

from oki.jobs.enums import WorkflowEvent, WorkflowState
from oki.jobs.models import LocalizationJob
from oki.jobs.state_machine import GuardRejected, InvalidTransition, WorkflowStateMachine

PRIMARY_SEQUENCE = (
    (WorkflowState.CREATOR_LEAD, WorkflowEvent.REQUEST_RIGHTS, WorkflowState.RIGHTS_PENDING),
    (WorkflowState.RIGHTS_PENDING, WorkflowEvent.APPROVE_RIGHTS, WorkflowState.RIGHTS_APPROVED),
    (WorkflowState.RIGHTS_APPROVED, WorkflowEvent.REQUEST_SOURCE, WorkflowState.SOURCE_REQUESTED),
    (WorkflowState.SOURCE_REQUESTED, WorkflowEvent.RECORD_SOURCE_UPLOAD, WorkflowState.SOURCE_UPLOADED),
    (WorkflowState.SOURCE_UPLOADED, WorkflowEvent.VALIDATE_SOURCE, WorkflowState.SOURCE_VALIDATED),
    (WorkflowState.SOURCE_VALIDATED, WorkflowEvent.START_ANALYSIS, WorkflowState.ANALYSIS_RUNNING),
    (WorkflowState.ANALYSIS_RUNNING, WorkflowEvent.REQUIRE_AD_REVIEW, WorkflowState.AD_REVIEW_REQUIRED),
    (WorkflowState.AD_REVIEW_REQUIRED, WorkflowEvent.START_TRANSLATION, WorkflowState.TRANSLATION_RUNNING),
    (WorkflowState.TRANSLATION_RUNNING, WorkflowEvent.REQUEST_TRANSLATION_REVIEW, WorkflowState.TRANSLATION_REVIEW),
    (WorkflowState.TRANSLATION_REVIEW, WorkflowEvent.START_DUBBING, WorkflowState.DUBBING_RUNNING),
    (WorkflowState.DUBBING_RUNNING, WorkflowEvent.REQUEST_AUDIO_REVIEW, WorkflowState.AUDIO_REVIEW),
    (WorkflowState.AUDIO_REVIEW, WorkflowEvent.START_RENDER, WorkflowState.RENDER_RUNNING),
    (WorkflowState.RENDER_RUNNING, WorkflowEvent.REQUEST_INTERNAL_QA, WorkflowState.INTERNAL_QA),
    (WorkflowState.INTERNAL_QA, WorkflowEvent.REQUEST_CREATOR_REVIEW, WorkflowState.CREATOR_REVIEW),
    (WorkflowState.CREATOR_REVIEW, WorkflowEvent.MARK_PUBLISH_READY, WorkflowState.PUBLISH_READY),
    (WorkflowState.PUBLISH_READY, WorkflowEvent.UPLOAD_PRIVATE, WorkflowState.UPLOADED_PRIVATE),
    (WorkflowState.UPLOADED_PRIVATE, WorkflowEvent.COMPLETE_PLATFORM_CHECK, WorkflowState.PLATFORM_CHECK),
    (WorkflowState.PLATFORM_CHECK, WorkflowEvent.PUBLISH_APPROVED, WorkflowState.PUBLISHED),
    (WorkflowState.PUBLISHED, WorkflowEvent.START_PERFORMANCE_REVIEW, WorkflowState.PERFORMANCE_REVIEW),
    (WorkflowState.PERFORMANCE_REVIEW, WorkflowEvent.ARCHIVE, WorkflowState.ARCHIVED),
)


def make_job(state: WorkflowState) -> LocalizationJob:
    return LocalizationJob(
        id=uuid4(),
        organization_id=uuid4(),
        project_id=uuid4(),
        state=state,
    )


@pytest.mark.parametrize(("source", "event", "target"), PRIMARY_SEQUENCE)
def test_primary_sequence_is_explicit(
    source: WorkflowState,
    event: WorkflowEvent,
    target: WorkflowState,
) -> None:
    job = make_job(source)
    actor_type = "employee" if event is WorkflowEvent.PUBLISH_APPROVED else "system"

    decision = WorkflowStateMachine().transition(job, event, actor_type=actor_type)

    assert decision.from_state is source
    assert decision.to_state is target
    assert decision.event is event
    assert decision.guard_result is True
    assert job.state is target
    assert job.resumable_state is None


def test_publication_cannot_skip_private_and_platform_checks() -> None:
    job = make_job(WorkflowState.PUBLISH_READY)

    with pytest.raises(InvalidTransition):
        WorkflowStateMachine().transition(job, WorkflowEvent.PUBLISH_APPROVED)

    assert job.state is WorkflowState.PUBLISH_READY


def test_publication_requires_employee_authorization() -> None:
    job = make_job(WorkflowState.PLATFORM_CHECK)

    with pytest.raises(GuardRejected, match="employee authorization"):
        WorkflowStateMachine().transition(
            job,
            WorkflowEvent.PUBLISH_APPROVED,
            actor_type="system",
        )

    assert job.state is WorkflowState.PLATFORM_CHECK


@pytest.mark.parametrize(
    ("exception_event", "exception_state", "resume_event"),
    [
        (WorkflowEvent.BLOCK, WorkflowState.BLOCKED, WorkflowEvent.RESUME),
        (WorkflowEvent.FAIL, WorkflowState.FAILED, WorkflowEvent.RETRY),
    ],
)
def test_exceptional_state_returns_only_to_recorded_resumable_state_after_guard(
    exception_event: WorkflowEvent,
    exception_state: WorkflowState,
    resume_event: WorkflowEvent,
) -> None:
    machine = WorkflowStateMachine()
    job = make_job(WorkflowState.TRANSLATION_RUNNING)

    exceptional = machine.transition(job, exception_event)

    assert exceptional.to_state is exception_state
    assert exceptional.prior_resumable_state is WorkflowState.TRANSLATION_RUNNING
    assert job.state is exception_state
    assert job.resumable_state is WorkflowState.TRANSLATION_RUNNING

    with pytest.raises(GuardRejected):
        machine.transition(job, resume_event, guard_result=False)
    assert job.state is exception_state
    assert job.resumable_state is WorkflowState.TRANSLATION_RUNNING

    resumed = machine.transition(job, resume_event, guard_result=True)
    assert resumed.from_state is exception_state
    assert resumed.to_state is WorkflowState.TRANSLATION_RUNNING
    assert resumed.prior_resumable_state is WorkflowState.TRANSLATION_RUNNING
    assert job.state is WorkflowState.TRANSLATION_RUNNING
    assert job.resumable_state is None


def test_blocked_cannot_retry_and_failed_cannot_resume() -> None:
    machine = WorkflowStateMachine()
    blocked = make_job(WorkflowState.BLOCKED)
    blocked.resumable_state = WorkflowState.ANALYSIS_RUNNING
    failed = make_job(WorkflowState.FAILED)
    failed.resumable_state = WorkflowState.RENDER_RUNNING

    with pytest.raises(InvalidTransition):
        machine.transition(blocked, WorkflowEvent.RETRY)
    with pytest.raises(InvalidTransition):
        machine.transition(failed, WorkflowEvent.RESUME)


@pytest.mark.parametrize("terminal", [WorkflowState.CANCELLED, WorkflowState.RIGHTS_REVOKED])
def test_terminal_exceptional_states_never_resume(terminal: WorkflowState) -> None:
    machine = WorkflowStateMachine()
    job = make_job(terminal)
    job.resumable_state = WorkflowState.ANALYSIS_RUNNING

    for event in WorkflowEvent:
        with pytest.raises(InvalidTransition):
            machine.transition(job, event, actor_type="employee")


@pytest.mark.parametrize("event", [WorkflowEvent.CANCEL, WorkflowEvent.REVOKE_RIGHTS])
def test_terminal_transition_discards_resumable_state(event: WorkflowEvent) -> None:
    job = make_job(WorkflowState.FAILED)
    job.resumable_state = WorkflowState.RENDER_RUNNING

    decision = WorkflowStateMachine().transition(job, event)

    expected = (
        WorkflowState.CANCELLED
        if event is WorkflowEvent.CANCEL
        else WorkflowState.RIGHTS_REVOKED
    )
    assert decision.to_state is expected
    assert decision.prior_resumable_state is WorkflowState.RENDER_RUNNING
    assert job.state is expected
    assert job.resumable_state is None
