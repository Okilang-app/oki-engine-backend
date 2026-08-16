from dataclasses import dataclass
from typing import Protocol

from oki.api.errors import ProblemException
from oki.jobs.enums import WorkflowEvent, WorkflowState


class WorkflowJob(Protocol):
    state: WorkflowState
    resumable_state: WorkflowState | None


class InvalidTransition(ProblemException):
    def __init__(self, state: WorkflowState, event: WorkflowEvent, detail: str | None = None) -> None:
        super().__init__(
            status_code=409,
            code="invalid_workflow_transition",
            title="Invalid workflow transition",
            detail=detail or f"Event {event.value} is not allowed from {state.value}.",
        )
        self.state = state
        self.event = event


class GuardRejected(ProblemException):
    def __init__(self, state: WorkflowState, event: WorkflowEvent, detail: str | None = None) -> None:
        super().__init__(
            status_code=409,
            code="workflow_guard_rejected",
            title="Workflow guard rejected",
            detail=detail or f"The guard rejected {event.value} from {state.value}.",
        )
        self.state = state
        self.event = event


@dataclass(frozen=True, slots=True)
class TransitionDecision:
    from_state: WorkflowState
    to_state: WorkflowState
    event: WorkflowEvent
    guard_result: bool
    prior_resumable_state: WorkflowState | None


class WorkflowStateMachine:
    """The authoritative pure transition policy for localization jobs."""

    PRIMARY_TRANSITIONS = {
        (WorkflowState.CREATOR_LEAD, WorkflowEvent.REQUEST_RIGHTS): WorkflowState.RIGHTS_PENDING,
        (WorkflowState.RIGHTS_PENDING, WorkflowEvent.APPROVE_RIGHTS): WorkflowState.RIGHTS_APPROVED,
        (WorkflowState.RIGHTS_APPROVED, WorkflowEvent.REQUEST_SOURCE): WorkflowState.SOURCE_REQUESTED,
        (WorkflowState.SOURCE_REQUESTED, WorkflowEvent.RECORD_SOURCE_UPLOAD): WorkflowState.SOURCE_UPLOADED,
        (WorkflowState.SOURCE_UPLOADED, WorkflowEvent.VALIDATE_SOURCE): WorkflowState.SOURCE_VALIDATED,
        (WorkflowState.SOURCE_VALIDATED, WorkflowEvent.START_ANALYSIS): WorkflowState.ANALYSIS_RUNNING,
        (WorkflowState.ANALYSIS_RUNNING, WorkflowEvent.REQUIRE_AD_REVIEW): WorkflowState.AD_REVIEW_REQUIRED,
        (WorkflowState.AD_REVIEW_REQUIRED, WorkflowEvent.START_TRANSLATION): WorkflowState.TRANSLATION_RUNNING,
        (WorkflowState.TRANSLATION_RUNNING, WorkflowEvent.REQUEST_TRANSLATION_REVIEW): WorkflowState.TRANSLATION_REVIEW,
        (WorkflowState.TRANSLATION_REVIEW, WorkflowEvent.START_DUBBING): WorkflowState.DUBBING_RUNNING,
        (WorkflowState.DUBBING_RUNNING, WorkflowEvent.REQUEST_AUDIO_REVIEW): WorkflowState.AUDIO_REVIEW,
        (WorkflowState.AUDIO_REVIEW, WorkflowEvent.START_RENDER): WorkflowState.RENDER_RUNNING,
        (WorkflowState.RENDER_RUNNING, WorkflowEvent.REQUEST_INTERNAL_QA): WorkflowState.INTERNAL_QA,
        (WorkflowState.INTERNAL_QA, WorkflowEvent.REQUEST_CREATOR_REVIEW): WorkflowState.CREATOR_REVIEW,
        (WorkflowState.CREATOR_REVIEW, WorkflowEvent.MARK_PUBLISH_READY): WorkflowState.PUBLISH_READY,
        (WorkflowState.PUBLISH_READY, WorkflowEvent.UPLOAD_PRIVATE): WorkflowState.UPLOADED_PRIVATE,
        (WorkflowState.UPLOADED_PRIVATE, WorkflowEvent.COMPLETE_PLATFORM_CHECK): WorkflowState.PLATFORM_CHECK,
        (WorkflowState.PLATFORM_CHECK, WorkflowEvent.PUBLISH_APPROVED): WorkflowState.PUBLISHED,
        (WorkflowState.PUBLISHED, WorkflowEvent.START_PERFORMANCE_REVIEW): WorkflowState.PERFORMANCE_REVIEW,
        (WorkflowState.PERFORMANCE_REVIEW, WorkflowEvent.ARCHIVE): WorkflowState.ARCHIVED,
    }
    TERMINAL_STATES = {
        WorkflowState.ARCHIVED,
        WorkflowState.CANCELLED,
        WorkflowState.RIGHTS_REVOKED,
    }

    def transition(
        self,
        job: WorkflowJob,
        event: WorkflowEvent,
        *,
        guard_result: bool = True,
        actor_type: str = "system",
    ) -> TransitionDecision:
        source = job.state
        if source in self.TERMINAL_STATES:
            raise InvalidTransition(source, event)

        if event is WorkflowEvent.CANCEL:
            return self._apply(job, event, WorkflowState.CANCELLED, guard_result)
        if event is WorkflowEvent.REVOKE_RIGHTS:
            return self._apply(job, event, WorkflowState.RIGHTS_REVOKED, guard_result)

        if event in {WorkflowEvent.BLOCK, WorkflowEvent.FAIL}:
            if source in {WorkflowState.BLOCKED, WorkflowState.FAILED}:
                raise InvalidTransition(source, event)
            if not guard_result:
                raise GuardRejected(source, event)
            target = WorkflowState.BLOCKED if event is WorkflowEvent.BLOCK else WorkflowState.FAILED
            job.state = target
            job.resumable_state = source
            return TransitionDecision(source, target, event, True, source)

        if event in {WorkflowEvent.RESUME, WorkflowEvent.RETRY}:
            expected = (
                WorkflowState.BLOCKED if event is WorkflowEvent.RESUME else WorkflowState.FAILED
            )
            if source is not expected or job.resumable_state is None:
                raise InvalidTransition(source, event)
            if not guard_result:
                raise GuardRejected(source, event)
            target = job.resumable_state
            job.state = target
            job.resumable_state = None
            return TransitionDecision(source, target, event, True, target)

        target = self.PRIMARY_TRANSITIONS.get((source, event))
        if target is None:
            raise InvalidTransition(source, event)
        if event is WorkflowEvent.PUBLISH_APPROVED and actor_type != "employee":
            raise GuardRejected(
                source,
                event,
                "Public release requires distinct employee authorization after platform checks.",
            )
        return self._apply(job, event, target, guard_result)

    @staticmethod
    def _apply(
        job: WorkflowJob,
        event: WorkflowEvent,
        target: WorkflowState,
        guard_result: bool,
    ) -> TransitionDecision:
        source = job.state
        if not guard_result:
            raise GuardRejected(source, event)
        prior_resumable_state = job.resumable_state
        job.state = target
        job.resumable_state = None
        return TransitionDecision(source, target, event, True, prior_resumable_state)
