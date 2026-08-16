from collections.abc import Callable
from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID

from sqlalchemy import select

from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.campaigns.enums import CreativeStatus
from oki.campaigns.models import AttributionKey, Campaign, Creative


class CampaignService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], authorizer: Authorizer) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer

    async def list_campaigns(
        self,
        principal: Principal,
    ) -> list[Campaign]:
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
                select(Campaign)
                .where(Campaign.organization_id.in_(org_ids))
                .order_by(Campaign.starts_at.desc())
            )
            return list(result)

    async def get_campaign_creatives(
        self,
        principal: Principal,
        campaign_id: UUID,
    ) -> list[Creative]:
        async with self._uow_factory() as uow:
            campaign = await uow.session.get(Campaign, campaign_id)
            if campaign is None:
                self._not_found("campaign_not_found", "Campaign not found")

            self._authorizer.require(
                principal,
                Action.CREATOR_READ,
                ResourceScope(organization_id=campaign.organization_id),
            )

            result = await uow.session.scalars(
                select(Creative)
                .where(Creative.campaign_id == campaign_id)
                .order_by(Creative.name)
            )
            return list(result)

    async def check_creative_eligibility(
        self,
        principal: Principal,
        creative_id: UUID,
        *,
        now: datetime | None = None,
    ) -> Creative:
        """Return the creative if eligible, otherwise raise.

        Expired creatives are rejected.
        """
        if now is None:
            now = datetime.now(UTC)

        async with self._uow_factory() as uow:
            creative = await uow.session.get(Creative, creative_id)
            if creative is None:
                self._not_found("creative_not_found", "Creative not found")

            self._authorizer.require(
                principal,
                Action.CREATOR_READ,
                ResourceScope(organization_id=creative.organization_id),
            )

            if creative.expires_at is not None and creative.expires_at < now:
                raise ProblemException(
                    status_code=409,
                    code="creative_expired",
                    title="Creative expired",
                    detail="The creative has expired and cannot be used.",
                )

            if creative.status not in {CreativeStatus.APPROVED, CreativeStatus.DRAFT}:
                raise ProblemException(
                    status_code=409,
                    code="creative_not_usable",
                    title="Creative not usable",
                    detail=f"Creative status is {creative.status.value}.",
                )

            return creative

    @staticmethod
    def _scope(organization_id: UUID) -> ResourceScope:
        return ResourceScope(
            organization_id=organization_id,
            creator_organization_id=organization_id,
        )

    @staticmethod
    def _not_found(code: str, title: str) -> NoReturn:
        raise ProblemException(
            status_code=404,
            code=code,
            title=title,
            detail=f"The requested {title.lower()} does not exist.",
        )


class AttributionKeyService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], authorizer: Authorizer) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer

    async def issue(
        self,
        principal: Principal,
        campaign_id: UUID,
        creative_id: UUID,
        key_type: str,
        key_value: str,
        *,
        expires_at: datetime | None = None,
    ) -> AttributionKey:
        """Issue a new attribution key for a creative."""
        async with self._uow_factory() as uow:
            creative = await uow.session.get(Creative, creative_id)
            if creative is None or creative.campaign_id != campaign_id:
                raise ProblemException(
                    status_code=404,
                    code="creative_not_found",
                    title="Creative not found",
                    detail="The creative does not exist in this campaign.",
                )

            self._authorizer.require(
                principal,
                Action.CREATOR_READ,
                ResourceScope(organization_id=creative.organization_id),
            )

            key = AttributionKey(
                organization_id=creative.organization_id,
                campaign_id=campaign_id,
                creative_id=creative_id,
                key_type=key_type,
                key_value=key_value,
                expires_at=expires_at,
            )
            uow.session.add(key)
            await uow.session.flush()
            return key
