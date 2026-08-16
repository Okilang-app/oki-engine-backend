from uuid import UUID
from typing import NoReturn


from oki.api.errors import ForbiddenProblem
from oki.identity.enums import Action
from oki.identity.schemas import Principal, PrincipalMembership, ResourceScope


class Authorizer:
    """Apply tenant-local action RBAC and creator/project resource scope."""

    def require(
        self,
        principal: Principal,
        action: Action,
        resource: ResourceScope,
    ) -> None:
        membership = self._membership_for(principal, resource.organization_id)
        if membership is None:
            self._deny_scope()

        if membership.is_creator:
            creator_organization_id = (
                resource.creator_organization_id or resource.organization_id
            )
            if creator_organization_id not in membership.creator_organization_ids:
                self._deny_scope()
            if resource.project_id is not None and resource.project_id not in membership.project_ids:
                self._deny_scope()

        if action not in membership.actions:
            raise ForbiddenProblem(
                code="action_denied",
                detail="The authenticated identity is not permitted to perform this action.",
            )

    @staticmethod
    def _membership_for(
        principal: Principal,
        organization_id: UUID,
    ) -> PrincipalMembership | None:
        return next(
            (
                membership
                for membership in principal.memberships
                if membership.organization_id == organization_id
            ),
            None,
        )

    @staticmethod
    def _deny_scope() -> NoReturn:
        raise ForbiddenProblem(
            code="resource_scope_denied",
            detail="The requested resource is outside the authenticated identity's scope.",
        )
