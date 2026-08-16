from typing import Annotated

from fastapi import APIRouter, Depends

from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal, PrincipalResponse

router = APIRouter(prefix="/api/identity", tags=["identity"])


@router.get("/me", response_model=PrincipalResponse)
async def read_current_identity(
    principal: Annotated[Principal, Depends(current_principal)],
) -> PrincipalResponse:
    """Return the authenticated subject's local memberships and grants."""

    return PrincipalResponse.from_principal(principal)
