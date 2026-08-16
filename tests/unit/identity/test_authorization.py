from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine

from oki.api.errors import ForbiddenProblem
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.models import CreatorAccountScope
from oki.identity.schemas import Principal, PrincipalMembership, ResourceScope


@pytest.fixture
def authorizer() -> Authorizer:
    return Authorizer()


def principal_for(
    *,
    role: str,
    actions: frozenset[Action],
    organization_id=None,
    creator_organization_ids=frozenset(),
    project_ids=frozenset(),
) -> Principal:
    organization_id = organization_id or uuid4()
    return Principal(
        subject=f"keycloak:{uuid4()}",
        user_id=uuid4(),
        email="person@example.test",
        display_name="Test person",
        memberships=(
            PrincipalMembership(
                organization_id=organization_id,
                role_names=frozenset({role}),
                actions=actions,
                creator_organization_ids=creator_organization_ids,
                project_ids=project_ids,
            ),
        ),
    )


def test_creator_cannot_read_another_creator_project(authorizer: Authorizer) -> None:
    creator_organization_id = uuid4()
    assigned_project_id = uuid4()
    principal = principal_for(
        role="creator",
        actions=frozenset({Action.PROJECT_READ}),
        organization_id=creator_organization_id,
        creator_organization_ids=frozenset({creator_organization_id}),
        project_ids=frozenset({assigned_project_id}),
    )
    foreign_project = ResourceScope(
        organization_id=creator_organization_id,
        creator_organization_id=uuid4(),
        project_id=uuid4(),
    )

    with pytest.raises(ForbiddenProblem) as error:
        authorizer.require(principal, Action.PROJECT_READ, foreign_project)

    assert error.value.code == "resource_scope_denied"


def test_creator_cannot_read_unassigned_project_in_own_creator_organization(
    authorizer: Authorizer,
) -> None:
    creator_organization_id = uuid4()
    principal = principal_for(
        role="creator",
        actions=frozenset({Action.PROJECT_READ}),
        organization_id=creator_organization_id,
        creator_organization_ids=frozenset({creator_organization_id}),
        project_ids=frozenset({uuid4()}),
    )

    with pytest.raises(ForbiddenProblem) as error:
        authorizer.require(
            principal,
            Action.PROJECT_READ,
            ResourceScope(
                organization_id=creator_organization_id,
                creator_organization_id=creator_organization_id,
                project_id=uuid4(),
            ),
        )

    assert error.value.code == "resource_scope_denied"


def test_creator_can_read_explicitly_shared_project(authorizer: Authorizer) -> None:
    creator_organization_id = uuid4()
    project_id = uuid4()
    principal = principal_for(
        role="creator",
        actions=frozenset({Action.PROJECT_READ}),
        organization_id=creator_organization_id,
        creator_organization_ids=frozenset({creator_organization_id}),
        project_ids=frozenset({project_id}),
    )

    result = authorizer.require(
        principal,
        Action.PROJECT_READ,
        ResourceScope(
            organization_id=creator_organization_id,
            creator_organization_id=creator_organization_id,
            project_id=project_id,
        ),
    )

    assert result is None


def test_publisher_cannot_approve_agreement(authorizer: Authorizer) -> None:
    organization_id = uuid4()
    publisher = principal_for(
        role="publisher",
        actions=frozenset(
            {
                Action.PUBLICATION_UPLOAD_PRIVATE,
                Action.PUBLICATION_RELEASE_PUBLIC,
            }
        ),
        organization_id=organization_id,
    )
    agreement = ResourceScope(organization_id=organization_id)

    with pytest.raises(ForbiddenProblem) as error:
        authorizer.require(publisher, Action.AGREEMENT_APPROVE, agreement)

    assert error.value.code == "action_denied"


def test_permission_from_one_membership_does_not_cross_organization() -> None:
    legal_organization_id = uuid4()
    publisher_organization_id = uuid4()
    principal = Principal(
        subject=f"keycloak:{uuid4()}",
        user_id=uuid4(),
        email="multi@example.test",
        display_name="Multi membership",
        memberships=(
            PrincipalMembership(
                organization_id=legal_organization_id,
                role_names=frozenset({"legal_reviewer"}),
                actions=frozenset({Action.AGREEMENT_APPROVE}),
            ),
            PrincipalMembership(
                organization_id=publisher_organization_id,
                role_names=frozenset({"publisher"}),
                actions=frozenset({Action.PUBLICATION_UPLOAD_PRIVATE}),
            ),
        ),
    )

    with pytest.raises(ForbiddenProblem) as error:
        Authorizer().require(
            principal,
            Action.AGREEMENT_APPROVE,
            ResourceScope(organization_id=publisher_organization_id),
        )

    assert error.value.code == "action_denied"


def test_member_cannot_access_another_organization(authorizer: Authorizer) -> None:
    principal = principal_for(
        role="legal_reviewer",
        actions=frozenset({Action.AGREEMENT_APPROVE}),
    )

    with pytest.raises(ForbiddenProblem) as error:
        authorizer.require(
            principal,
            Action.AGREEMENT_APPROVE,
            ResourceScope(organization_id=uuid4()),
        )

    assert error.value.code == "resource_scope_denied"


def test_creator_scope_model_binds_project_to_creator_organization() -> None:
    constraint = next(
        constraint
        for constraint in CreatorAccountScope.__table__.foreign_key_constraints
        if constraint.name == "fk_creator_account_scopes_project_organization"
    )

    assert {column.name for column in constraint.columns} == {
        "project_id",
        "creator_organization_id",
    }
    assert {element.target_fullname for element in constraint.elements} == {
        "projects.id",
        "projects.organization_id",
    }


def test_identity_downgrade_preserves_seeded_role_referenced_by_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_path = (
        Path(__file__).parents[3]
        / "migrations"
        / "versions"
        / "0003_identity_permissions.py"
    )
    specification = spec_from_file_location("identity_migration", migration_path)
    assert specification is not None and specification.loader is not None
    migration = module_from_spec(specification)
    specification.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE roles ("
            "id TEXT PRIMARY KEY, organization_id TEXT, name TEXT, is_system INTEGER)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE memberships (id TEXT PRIMARY KEY, role_id TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE permissions (id TEXT PRIMARY KEY, code TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE role_permissions (role_id TEXT, permission_id TEXT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO roles VALUES "
            "('legal', NULL, 'legal_reviewer', 1), "
            "('publisher', NULL, 'publisher', 1)"
        )
        connection.exec_driver_sql(
            "INSERT INTO memberships VALUES ('membership-1', 'legal')"
        )
        monkeypatch.setattr(migration.op, "execute", connection.execute)
        monkeypatch.setattr(migration.op, "drop_table", lambda table_name: None)
        monkeypatch.setattr(
            migration.op,
            "drop_constraint",
            lambda name, table_name, type_: None,
        )

        migration.downgrade()

        roles = connection.exec_driver_sql(
            "SELECT name FROM roles ORDER BY name"
        ).scalars().all()

    engine.dispose()
    assert roles == ["legal_reviewer"]
