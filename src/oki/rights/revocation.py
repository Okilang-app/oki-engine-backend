from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from oki.db.uow import UnitOfWork
from oki.jobs.enums import WorkflowEvent, WorkflowState
from oki.jobs.models import LocalizationJob, OutboxEvent, WorkflowTransition
from oki.jobs.state_machine import WorkflowStateMachine
from oki.rights.models import (
    AuditEvent,
    RightsAgreement,
    RightsAgreementVersion,
)


class RevocationService:
    """Propagates agreement revocation to affected active jobs atomically."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        state_machine: WorkflowStateMachine | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._state_machine = state_machine or WorkflowStateMachine()
        self._clock = clock or (lambda: datetime.now(UTC))

    async def propagate(self, agreement_version_id: UUID) -> int:
        """Set all active jobs for the creator to RIGHTS_REVOKED.

        Returns the number of jobs affected.
        """
        async with self._uow_factory() as uow:
            version = await uow.session.get(RightsAgreementVersion, agreement_version_id)
            if version is None:
                return 0

            agreement = await uow.session.get(RightsAgreement, version.agreement_id)
            if agreement is None:
                return 0

            jobs = list(
                await uow.session.scalars(
                    select(LocalizationJob)
                    .where(
                        LocalizationJob.organization_id == agreement.organization_id,
                        LocalizationJob.state.not_in(
                            {
                                WorkflowState.ARCHIVED.value,
                                WorkflowState.CANCELLED.value,
                                WorkflowState.RIGHTS_REVOKED.value,
                            }
                        ),
                    )
                    .with_for_update()
                )
            )

            affected = 0
            for job in jobs:
                source = job.state
                event = WorkflowEvent.REVOKE_RIGHTS
                try:
                    self._state_machine.transition(
                        job,
                        event,
                        guard_result=True,
                        actor_type="system",
                    )
                except Exception:
                    event = WorkflowEvent.CANCEL
                    try:
                        self._state_machine.transition(
                            job,
                            event,
                            guard_result=True,
                            actor_type="system",
                        )
                    except Exception:
                        continue

                uow.session.add(
                    WorkflowTransition(
                        organization_id=job.organization_id,
                        job_id=job.id,
                        from_state=source,
                        to_state=job.state,
                        event=event,
                        actor_type="system",
                        actor_id="oki.rights.revocation",
                        guard_result=True,
                        guard_details={
                            "agreement_version_id": str(agreement_version_id)
                        },
                        reason="Agreement version revoked; job rights cancelled.",
                        correlation_id=UUID(int=0),
                    )
                )

                uow.session.add(
                    OutboxEvent(
                        organization_id=job.organization_id,
                        aggregate_type="localization_job",
                        aggregate_id=job.id,
                        event_type="workflow.revoked",
                        payload={
                            "job_id": str(job.id),
                            "from_state": source.value,
                            "to_state": job.state.value,
                            "agreement_version_id": str(agreement_version_id),
                        },
                        headers={},
                    )
                )

                uow.session.add(
                    AuditEvent(
                        organization_id=job.organization_id,
                        actor_user_id=None,
                        subject="oki.rights.revocation",
                        entity_type="localization_job",
                        entity_id=job.id,
                        action="job.revoked",
                        previous_values={"state": source.value},
                        new_values={
                            "state": job.state.value,
                            "agreement_version_id": str(agreement_version_id),
                        },
                        reason="Agreement version revoked; job rights cancelled.",
                        correlation_id=UUID(int=0),
                        request_metadata={},
                    )
                )

                affected += 1

            return affected
