"""Ad service for replacement ad clips."""

from collections.abc import Callable
from typing import NoReturn
from uuid import UUID

from sqlalchemy import select

from oki.ads.models import InternalAd
from oki.ads.schemas import AdCreate
from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope


class AdService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], authorizer: Authorizer) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer

    async def list_ads(self, principal: Principal) -> list[InternalAd]:
        org_id = self._resolve_org(principal)
        self._authorizer.require(principal, Action.PROJECT_READ, self._scope(org_id))

        async with self._uow_factory() as uow:
            result = await uow.session.execute(
                select(InternalAd)
                .where(InternalAd.organization_id == org_id)
                .order_by(InternalAd.created_at.desc())
            )
            return list(result.scalars().all())

    async def create_ad(self, principal: Principal, payload: AdCreate) -> InternalAd:
        org_id = self._resolve_org(principal)
        self._authorizer.require(principal, Action.ASSET_CREATE, self._scope(org_id))

        async with self._uow_factory() as uow:
            ad = InternalAd(
                organization_id=org_id,
                name=payload.name,
                storage_key=payload.storage_key,
                duration_seconds=payload.duration_seconds,
                created_by_user_id=principal.user_id,
            )
            uow.session.add(ad)
            await uow.session.flush()
            await uow.session.refresh(ad)
            return ad

    async def get_ad(self, principal: Principal, ad_id: UUID) -> InternalAd:
        org_id = self._resolve_org(principal)
        self._authorizer.require(principal, Action.PROJECT_READ, self._scope(org_id))

        async with self._uow_factory() as uow:
            ad = await uow.session.get(InternalAd, ad_id)
            if ad is None or ad.organization_id != org_id:
                self._not_found("ad_not_found", "Ad not found")
            return ad

    async def delete_ad(self, principal: Principal, ad_id: UUID) -> None:
        org_id = self._resolve_org(principal)
        self._authorizer.require(principal, Action.ASSET_DELETE, self._scope(org_id))

        async with self._uow_factory() as uow:
            ad = await uow.session.get(InternalAd, ad_id)
            if ad is None:
                self._not_found("ad_not_found", "Ad not found")

            if ad.organization_id != org_id:
                self._not_found("ad_not_found", "Ad not found")

            await uow.session.delete(ad)

    @staticmethod
    def _resolve_org(principal: Principal) -> UUID:
        if not principal.memberships:
            raise ProblemException(
                status_code=403,
                code="no_membership",
                title="No organization membership",
                detail="User is not a member of any organization.",
            )
        return principal.memberships[0].organization_id

    @staticmethod
    def _scope(organization_id: UUID) -> ResourceScope:
        return ResourceScope(organization_id=organization_id)

    @staticmethod
    def _not_found(code: str, title: str) -> NoReturn:
        raise ProblemException(
            status_code=404,
            code=code,
            title=title,
            detail="The requested resource does not exist.",
        )
