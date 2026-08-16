from collections.abc import Awaitable, Callable
from typing import Protocol

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from oki.api.errors import ProblemException, UnauthorizedProblem
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope


class PrincipalVerifier(Protocol):
    async def verify(self, token: str) -> Principal: ...


_bearer = HTTPBearer(auto_error=False)
_authorizer = Authorizer()


async def current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    """Authenticate one bearer access token through the application verifier."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedProblem(
            code="missing_access_token",
            detail="A bearer access token is required.",
        )
    verifier: PrincipalVerifier | None = getattr(request.app.state, "token_verifier", None)
    if verifier is None:
        raise ProblemException(
            status_code=503,
            code="identity_service_unavailable",
            title="Identity service unavailable",
            detail="The identity verifier is not available.",
            retryable=True,
        )
    return await verifier.verify(credentials.credentials)


def request_resource_scope(request: Request) -> ResourceScope:
    """Return a scope established from an authoritative resource lookup."""

    scope = getattr(request.state, "resource_scope", None)
    if not isinstance(scope, ResourceScope):
        raise ProblemException(
            status_code=500,
            code="resource_scope_missing",
            title="Resource scope missing",
            detail="The protected endpoint did not establish an authorization scope.",
        )
    return scope


ResourceDependency = Callable[..., ResourceScope | Awaitable[ResourceScope]]


def require_action(
    action: Action,
    resource_dependency: ResourceDependency = request_resource_scope,
) -> Callable[..., Awaitable[Principal]]:
    """Build a FastAPI dependency enforcing an action on an authoritative scope."""

    async def dependency(
        principal: Principal = Depends(current_principal),
        resource: ResourceScope = Depends(resource_dependency),
    ) -> Principal:
        _authorizer.require(principal, action, resource)
        return principal

    return dependency
