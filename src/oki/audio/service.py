from collections.abc import Callable
from typing import NoReturn
from uuid import UUID

from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
from oki.audio.models import AudioMixVersion


class AudioService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], authorizer: Authorizer) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer

    async def create_mix(
        self,
        principal: Principal,
        asset_id: UUID,
        *,
        correlation_id: UUID,
    ) -> AudioMixVersion:
        """Create a new audio mix version for an asset.

        TODO: load asset, run source separation, build mix plan, queue render.
        """
        async with self._uow_factory() as uow:
            # TODO: validate asset exists and user has rights
            # For MVP, create a pending mix version
            mix = AudioMixVersion(
                organization_id=principal.user_id,  # placeholder until asset lookup
                job_id=asset_id,  # placeholder: should be the localization job
                asset_id=asset_id,
                mix_plan={
                    "source_asset_id": str(asset_id),
                    "stems": {},
                    "steps": ["pending"],
                },
                stems={},
                status="pending",
            )
            uow.session.add(mix)
            await uow.session.flush()
            return mix

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
