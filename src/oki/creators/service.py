from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from oki.api.errors import ProblemException
from oki.creators.models import (
    ChannelOwnershipEvidence,
    Creator,
    CreatorBrandGuide,
    CreatorChannel,
    CreatorRestriction,
)
from oki.creators.schemas import CreatorCreate
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.jobs.models import OutboxEvent
from oki.rights.enums import ConsentDecision
from oki.rights.models import AuditEvent


@dataclass(frozen=True, slots=True)
class CreatorDetails:
    creator: Creator
    channels: tuple[tuple[CreatorChannel, tuple[ChannelOwnershipEvidence, ...]], ...]
    brand_guides: tuple[CreatorBrandGuide, ...]
    restrictions: tuple[CreatorRestriction, ...]


def add_mutation_evidence(
    uow: UnitOfWork,
    *,
    principal: Principal,
    organization_id: UUID,
    entity_type: str,
    entity_id: UUID,
    action: str,
    correlation_id: UUID,
    new_values: dict[str, object],
    previous_values: dict[str, object] | None = None,
    reason: str | None = None,
) -> None:
    """Stage audit and outbox rows in the caller's transaction."""

    uow.session.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=principal.user_id,
            subject=principal.subject,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            previous_values=previous_values,
            new_values=new_values,
            reason=reason,
            correlation_id=correlation_id,
            request_metadata={},
        )
    )
    uow.session.add(
        OutboxEvent(
            organization_id=organization_id,
            aggregate_type=entity_type,
            aggregate_id=entity_id,
            event_type=action,
            payload=new_values,
            headers={
                "correlation_id": str(correlation_id),
                "actor_user_id": str(principal.user_id),
                "subject": principal.subject,
            },
        )
    )


class CreatorService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        authorizer: Authorizer,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer

    async def create(
        self,
        principal: Principal,
        payload: CreatorCreate,
        *,
        correlation_id: UUID,
    ) -> Creator:
        resource = ResourceScope(
            organization_id=payload.organization_id,
            creator_organization_id=payload.organization_id,
        )
        self._authorizer.require(principal, Action.CREATOR_CREATE, resource)

        async with self._uow_factory() as uow:
            existing = await uow.session.scalar(
                select(Creator.id).where(Creator.organization_id == payload.organization_id)
            )
            if existing is not None:
                raise ProblemException(
                    status_code=409,
                    code="creator_already_exists",
                    title="Creator already exists",
                    detail="This organization already has a creator record.",
                )

            creator = Creator(
                organization_id=payload.organization_id,
                legal_name=payload.legal_name,
                display_name=payload.display_name,
                primary_email=payload.primary_email,
                manager_name=payload.manager_name,
                manager_email=payload.manager_email,
                status=payload.status,
                created_by_user_id=principal.user_id,
            )
            uow.session.add(creator)
            await uow.session.flush()

            for channel_payload in payload.channels:
                channel = CreatorChannel(
                    organization_id=payload.organization_id,
                    creator_id=creator.id,
                    platform=channel_payload.platform,
                    external_channel_id=channel_payload.external_channel_id,
                    handle=channel_payload.handle,
                    canonical_url=str(channel_payload.canonical_url),
                    created_by_user_id=principal.user_id,
                )
                uow.session.add(channel)
                await uow.session.flush()
                for evidence_payload in channel_payload.ownership_evidence:
                    uow.session.add(
                        ChannelOwnershipEvidence(
                            organization_id=payload.organization_id,
                            creator_id=creator.id,
                            channel_id=channel.id,
                            method=evidence_payload.method,
                            decision=evidence_payload.decision,
                            evidence_reference=evidence_payload.evidence_reference,
                            evidence_sha256=evidence_payload.evidence_sha256.lower(),
                            observed_at=evidence_payload.observed_at,
                            decided_at=evidence_payload.decided_at,
                            reason=evidence_payload.reason,
                            decided_by_user_id=principal.user_id,
                        )
                    )

            for guide_payload in payload.brand_guides:
                uow.session.add(
                    CreatorBrandGuide(
                        organization_id=payload.organization_id,
                        creator_id=creator.id,
                        supersedes_brand_guide_id=None,
                        guide_reference=guide_payload.guide_reference,
                        guide_sha256=guide_payload.guide_sha256.lower(),
                        notes=guide_payload.notes,
                        effective_from=guide_payload.effective_from,
                        created_by_user_id=principal.user_id,
                    )
                )

            for restriction_payload in payload.restrictions:
                uow.session.add(
                    CreatorRestriction(
                        organization_id=payload.organization_id,
                        creator_id=creator.id,
                        supersedes_restriction_id=None,
                        restriction_type=restriction_payload.restriction_type,
                        description=restriction_payload.description,
                        effective_from=restriction_payload.effective_from,
                        expires_at=restriction_payload.expires_at,
                        created_by_user_id=principal.user_id,
                    )
                )

            add_mutation_evidence(
                uow,
                principal=principal,
                organization_id=payload.organization_id,
                entity_type="creator",
                entity_id=creator.id,
                action="creator.created",
                correlation_id=correlation_id,
                new_values={
                    "creator_id": str(creator.id),
                    "organization_id": str(payload.organization_id),
                    "channel_count": len(payload.channels),
                    "ownership_verified": any(
                        evidence.decision is ConsentDecision.GRANTED
                        for channel in payload.channels
                        for evidence in channel.ownership_evidence
                    ),
                },
            )
            await uow.session.flush()
            return creator

    async def list_creators(
        self,
        principal: Principal,
    ) -> list[Creator]:
        async with self._uow_factory() as uow:
            org_ids = [
                m.organization_id for m in principal.memberships
                if Action.CREATOR_READ in m.actions
            ]
            if not org_ids:
                self._authorizer.require(
                    principal, Action.CREATOR_READ, ResourceScope(organization_id=UUID(int=0))
                )
            result = await uow.session.scalars(
                select(Creator)
                .where(Creator.organization_id.in_(org_ids))
                .order_by(Creator.created_at.desc())
            )
            return list(result)

    async def get(self, principal: Principal, creator_id: UUID) -> Creator:
        async with self._uow_factory() as uow:
            creator = await uow.session.get(Creator, creator_id)
            if creator is None:
                self._not_found()
            self._authorizer.require(
                principal,
                Action.CREATOR_READ,
                ResourceScope(
                    organization_id=creator.organization_id,
                    creator_organization_id=creator.organization_id,
                ),
            )
            return creator

    async def get_details(self, principal: Principal, creator_id: UUID) -> CreatorDetails:
        async with self._uow_factory() as uow:
            creator = await uow.session.get(Creator, creator_id)
            if creator is None:
                self._not_found()
            self._authorizer.require(
                principal,
                Action.CREATOR_READ,
                ResourceScope(
                    organization_id=creator.organization_id,
                    creator_organization_id=creator.organization_id,
                ),
            )
            channels = tuple(
                await uow.session.scalars(
                    select(CreatorChannel)
                    .where(CreatorChannel.creator_id == creator.id)
                    .order_by(CreatorChannel.created_at)
                )
            )
            channel_details: list[tuple[CreatorChannel, tuple[ChannelOwnershipEvidence, ...]]] = []
            for channel in channels:
                evidence = tuple(
                    await uow.session.scalars(
                        select(ChannelOwnershipEvidence)
                        .where(ChannelOwnershipEvidence.channel_id == channel.id)
                        .order_by(ChannelOwnershipEvidence.decided_at)
                    )
                )
                channel_details.append((channel, evidence))
            brand_guides = tuple(
                await uow.session.scalars(
                    select(CreatorBrandGuide)
                    .where(CreatorBrandGuide.creator_id == creator.id)
                    .order_by(CreatorBrandGuide.effective_from)
                )
            )
            restrictions = tuple(
                await uow.session.scalars(
                    select(CreatorRestriction)
                    .where(CreatorRestriction.creator_id == creator.id)
                    .order_by(CreatorRestriction.effective_from)
                )
            )
            return CreatorDetails(
                creator=creator,
                channels=tuple(channel_details),
                brand_guides=brand_guides,
                restrictions=restrictions,
            )

    @staticmethod
    def _not_found() -> None:
        raise ProblemException(
            status_code=404,
            code="creator_not_found",
            title="Creator not found",
            detail="The requested creator does not exist.",
        )
