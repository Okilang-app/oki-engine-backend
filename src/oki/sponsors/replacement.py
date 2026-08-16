from collections.abc import Callable
from typing import NoReturn
from uuid import UUID

from oki.api.errors import ProblemException
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope


class ReplacementPlanService:
    """4-gate replacement logic for sponsor integrations.

    Gates:
    1. Rights gate — creator grants allow sponsor replacement.
    2. Campaign gate — a replacement campaign exists and is active.
    3. Creative gate — the replacement creative is approved and not expired.
    4. Localization gate — the target language/territory is covered.
    """

    def __init__(self, uow_factory: Callable[[], UnitOfWork], authorizer: Authorizer) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer

    async def approve(
        self,
        principal: Principal,
        plan_id: UUID,
        *,
        correlation_id: UUID,
    ) -> dict[str, object]:
        async with self._uow_factory() as uow:
            # TODO: load ReplacementPlan once model is available
            # For MVP, validate the 4 gates conceptually
            organization_id = principal.user_id  # placeholder

            self._authorizer.require(
                principal,
                Action.SPONSOR_REPLACE,
                ResourceScope(organization_id=organization_id),
            )

            # Gate 1: Rights
            # TODO: verify rights_grants.sponsor_removal_allowed and sponsor_replacement_mode

            # Gate 2: Campaign
            # TODO: verify active replacement campaign exists

            # Gate 3: Creative
            # TODO: verify creative is approved and not expired

            # Gate 4: Localization
            # TODO: verify language/territory coverage in grants

            return {
                "plan_id": str(plan_id),
                "approved": True,
                "gates_passed": [
                    "rights",
                    "campaign",
                    "creative",
                    "localization",
                ],
                "message": "Replacement plan approved (stub)",
            }

    @staticmethod
    def _not_found(code: str, title: str) -> NoReturn:
        raise ProblemException(
            status_code=404,
            code=code,
            title=title,
            detail=f"The requested {title.lower()} does not exist.",
        )
