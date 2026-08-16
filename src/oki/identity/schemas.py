from dataclasses import dataclass, field
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from oki.identity.enums import Action


@dataclass(frozen=True, slots=True)
class PrincipalMembership:
    """One tenant-local grant set for an authenticated user."""

    organization_id: UUID
    role_names: frozenset[str]
    actions: frozenset[Action]
    creator_organization_ids: frozenset[UUID] = field(default_factory=frozenset)
    project_ids: frozenset[UUID] = field(default_factory=frozenset)

    @property
    def is_creator(self) -> bool:
        return "creator" in self.role_names


@dataclass(frozen=True, slots=True)
class Principal:
    """A verified Keycloak subject with local, tenant-bounded grants."""

    subject: str
    user_id: UUID
    email: str
    display_name: str
    memberships: tuple[PrincipalMembership, ...]


@dataclass(frozen=True, slots=True)
class ResourceScope:
    """The local tenant, creator, and project owning a protected resource."""

    organization_id: UUID
    creator_organization_id: UUID | None = None
    project_id: UUID | None = None


class MembershipResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    roles: list[str]
    actions: list[Action]
    creator_organization_ids: list[UUID]
    project_ids: list[UUID]


class PrincipalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    user_id: UUID
    email: str
    display_name: str
    memberships: list[MembershipResponse]

    @classmethod
    def from_principal(cls, principal: Principal) -> "PrincipalResponse":
        return cls(
            subject=principal.subject,
            user_id=principal.user_id,
            email=principal.email,
            display_name=principal.display_name,
            memberships=[
                MembershipResponse(
                    organization_id=membership.organization_id,
                    roles=sorted(membership.role_names),
                    actions=sorted(membership.actions, key=str),
                    creator_organization_ids=sorted(
                        membership.creator_organization_ids,
                        key=str,
                    ),
                    project_ids=sorted(membership.project_ids, key=str),
                )
                for membership in principal.memberships
            ],
        )
