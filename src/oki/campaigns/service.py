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
from oki.campaigns.schemas import CampaignCreate, CampaignUpdate, CreativeCreate, CreativeUpdate


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

    async def create_campaign(
        self,
        principal: Principal,
        payload: CampaignCreate,
    ) -> Campaign:
        self._authorizer.require(
            principal,
            Action.CREATOR_CREATE,
            self._scope(payload.organization_id),
        )

        async with self._uow_factory() as uow:
            campaign = Campaign(
                organization_id=payload.organization_id,
                name=payload.name,
                description=payload.description,
                starts_at=payload.starts_at,
                ends_at=payload.ends_at,
                budget_currency=payload.budget_currency.upper(),
                budget_amount=payload.budget_amount,
                meta=payload.meta,
            )
            uow.session.add(campaign)
            await uow.session.flush()
            return campaign

    async def update_campaign(
        self,
        principal: Principal,
        campaign_id: UUID,
        payload: CampaignUpdate,
    ) -> Campaign:
        async with self._uow_factory() as uow:
            campaign = await uow.session.get(Campaign, campaign_id)
            if campaign is None:
                self._not_found("campaign_not_found", "Campaign not found")

            self._authorizer.require(
                principal,
                Action.CREATOR_CREATE,
                self._scope(campaign.organization_id),
            )

            if payload.name is not None:
                campaign.name = payload.name
            if payload.description is not None:
                campaign.description = payload.description
            if payload.starts_at is not None:
                campaign.starts_at = payload.starts_at
            if payload.ends_at is not None:
                campaign.ends_at = payload.ends_at
            if payload.budget_currency is not None:
                campaign.budget_currency = payload.budget_currency.upper()
            if payload.budget_amount is not None:
                campaign.budget_amount = payload.budget_amount
            if payload.meta is not None:
                campaign.meta = payload.meta

            await uow.session.flush()
            return campaign

    async def create_creative(
        self,
        principal: Principal,
        campaign_id: UUID,
        payload: CreativeCreate,
    ) -> Creative:
        async with self._uow_factory() as uow:
            campaign = await uow.session.get(Campaign, campaign_id)
            if campaign is None:
                self._not_found("campaign_not_found", "Campaign not found")

            self._authorizer.require(
                principal,
                Action.CREATOR_CREATE,
                self._scope(campaign.organization_id),
            )

            creative = Creative(
                organization_id=campaign.organization_id,
                campaign_id=campaign_id,
                name=payload.name,
                creative_type=payload.creative_type,
                status=CreativeStatus.DRAFT,
                language_code=payload.language_code,
                territory_code=payload.territory_code,
                sponsor_name=payload.sponsor_name,
                sponsor_product=payload.sponsor_product,
                script_text=payload.script_text,
                visual_reference_url=payload.visual_reference_url,
                expires_at=payload.expires_at,
                meta=payload.meta,
            )
            uow.session.add(creative)
            await uow.session.flush()
            return creative

    async def update_creative(
        self,
        principal: Principal,
        campaign_id: UUID,
        creative_id: UUID,
        payload: CreativeUpdate,
    ) -> Creative:
        async with self._uow_factory() as uow:
            creative = await uow.session.get(Creative, creative_id)
            if creative is None or creative.campaign_id != campaign_id:
                self._not_found("creative_not_found", "Creative not found")

            self._authorizer.require(
                principal,
                Action.CREATOR_CREATE,
                self._scope(creative.organization_id),
            )

            if payload.name is not None:
                creative.name = payload.name
            if payload.creative_type is not None:
                creative.creative_type = payload.creative_type
            if payload.language_code is not None:
                creative.language_code = payload.language_code
            if payload.territory_code is not None:
                creative.territory_code = payload.territory_code
            if payload.sponsor_name is not None:
                creative.sponsor_name = payload.sponsor_name
            if payload.sponsor_product is not None:
                creative.sponsor_product = payload.sponsor_product
            if payload.script_text is not None:
                creative.script_text = payload.script_text
            if payload.visual_reference_url is not None:
                creative.visual_reference_url = payload.visual_reference_url
            if payload.expires_at is not None:
                creative.expires_at = payload.expires_at
            if payload.meta is not None:
                creative.meta = payload.meta

            await uow.session.flush()
            return creative

    async def deactivate_creative(
        self,
        principal: Principal,
        campaign_id: UUID,
        creative_id: UUID,
    ) -> None:
        async with self._uow_factory() as uow:
            creative = await uow.session.get(Creative, creative_id)
            if creative is None or creative.campaign_id != campaign_id:
                self._not_found("creative_not_found", "Creative not found")

            self._authorizer.require(
                principal,
                Action.CREATOR_CREATE,
                self._scope(creative.organization_id),
            )

            creative.status = CreativeStatus.ARCHIVED
            await uow.session.flush()

    async def check_creative_eligibility(
        self,
        principal: Principal,
        creative_id: UUID,
    ) -> Creative:
        """Return the creative if it's usable (not expired and not rejected)."""
        async with self._uow_factory() as uow:
            creative = await uow.session.get(Creative, creative_id)
            if creative is None:
                self._not_found("creative_not_found", "Creative not found")

            if creative.status == CreativeStatus.REJECTED:
                raise ProblemException(
                    status_code=400,
                    code="creative_not_usable",
                    title="Creative not usable",
                    detail="This creative has been rejected.",
                )
            if creative.status == CreativeStatus.ARCHIVED:
                raise ProblemException(
                    status_code=400,
                    code="creative_not_usable",
                    title="Creative not usable",
                    detail="This creative has been archived.",
                )
            if creative.expires_at is not None and creative.expires_at < datetime.now(UTC):
                raise ProblemException(
                    status_code=400,
                    code="creative_expired",
                    title="Creative expired",
                    detail="This creative has expired.",
                )
            return creative

    @staticmethod
    def _scope(organization_id: UUID) -> ResourceScope:
        return ResourceScope(
            organization_id=organization_id,
            creator_organization_id=organization_id,
        )
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
