from collections.abc import Callable
from typing import NoReturn
from uuid import UUID

from sqlalchemy import select

from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.voices.models import VoiceProfile


class VoiceService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], authorizer: Authorizer) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer

    async def list_profiles(
        self,
        principal: Principal,
    ) -> list[VoiceProfile]:
        async with self._uow_factory() as uow:
            # Service-scoped read: list across all authorized organizations
            org_ids = [
                m.organization_id for m in principal.memberships
                if Action.CREATOR_READ in m.actions
            ]
            if not org_ids:
                self._authorizer.require(
                    principal, Action.CREATOR_READ, ResourceScope(organization_id=UUID(int=0))
                )
            result = await uow.session.scalars(
                select(VoiceProfile)
                .where(VoiceProfile.organization_id.in_(org_ids))
                .order_by(VoiceProfile.name)
            )
            return list(result)

    async def get_profile(
        self,
        principal: Principal,
        profile_id: UUID,
    ) -> VoiceProfile:
        async with self._uow_factory() as uow:
            profile = await uow.session.get(VoiceProfile, profile_id)
            if profile is None:
                self._not_found("voice_profile_not_found", "Voice profile not found")
            self._authorizer.require(
                principal,
                Action.CREATOR_READ,
                ResourceScope(organization_id=profile.organization_id),
            )
            return profile

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
