"""Create creator account scopes and seed least-privilege actions.

Revision ID: 0003_identity_permissions
Revises: 0002_workflow_kernel
Create Date: 2026-08-15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_identity_permissions"
down_revision: str | None = "0002_workflow_kernel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_ROLE = "oki_app"
PERMISSIONS = (
    ("creator.create", "Create a creator identity and organization."),
    ("creator.read", "Read creator identity and organization data."),
    ("project.read", "Read a project within assigned resource scope."),
    ("agreement.create", "Create a versioned rights agreement."),
    ("agreement.approve", "Approve a rights agreement as legal reviewer."),
    ("agreement.revoke", "Revoke an approved rights agreement."),
    ("voice_consent.record", "Record explicit creator voice consent."),
    ("sponsor.replace", "Approve and perform a permitted sponsor replacement."),
    ("creator_review.submit", "Submit a creator review decision."),
    ("publication.upload_private", "Upload an approved package as private."),
    ("publication.release_public", "Release an approved private upload publicly."),
    ("publication.unpublish", "Unpublish an authorized publication."),
    ("payout.approve", "Approve a reproducible creator payout."),
    ("dead_letter.replay", "Replay an authorized dead-lettered task."),
    ("audit.read", "Read append-only audit history."),
)
SYSTEM_ROLES = (
    "administrator",
    "legal_reviewer",
    "creator_manager",
    "content_analyst",
    "translator",
    "linguistic_reviewer",
    "dubbing_reviewer",
    "video_editor",
    "publisher",
    "finance_reviewer",
    "creator",
    "read_only_auditor",
)
ROLE_PERMISSIONS = (
    ("legal_reviewer", "creator.read"),
    ("legal_reviewer", "project.read"),
    ("legal_reviewer", "agreement.create"),
    ("legal_reviewer", "agreement.approve"),
    ("legal_reviewer", "agreement.revoke"),
    ("legal_reviewer", "voice_consent.record"),
    ("creator_manager", "creator.create"),
    ("creator_manager", "creator.read"),
    ("creator_manager", "project.read"),
    ("creator_manager", "agreement.create"),
    ("content_analyst", "creator.read"),
    ("content_analyst", "project.read"),
    ("translator", "project.read"),
    ("linguistic_reviewer", "project.read"),
    ("dubbing_reviewer", "project.read"),
    ("video_editor", "project.read"),
    ("video_editor", "sponsor.replace"),
    ("publisher", "project.read"),
    ("publisher", "publication.upload_private"),
    ("publisher", "publication.release_public"),
    ("publisher", "publication.unpublish"),
    ("finance_reviewer", "payout.approve"),
    ("finance_reviewer", "audit.read"),
    ("creator", "project.read"),
    ("creator", "creator_review.submit"),
    ("read_only_auditor", "creator.read"),
    ("read_only_auditor", "project.read"),
    ("read_only_auditor", "audit.read"),
)


def _sql_values(rows: tuple[tuple[str, str], ...]) -> str:
    return ", ".join(
        "(" + ", ".join("'" + value.replace("'", "''") + "'" for value in row) + ")"
        for row in rows
    )


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_projects_id_organization",
        "projects",
        ["id", "organization_id"],
    )
    op.create_table(
        "creator_account_scopes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuidv7()"),
        ),
        sa.Column(
            "membership_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("memberships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "creator_organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.ForeignKeyConstraint(
            ["project_id", "creator_organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_creator_account_scopes_project_organization",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_creator_account_scopes_membership",
        "creator_account_scopes",
        ["membership_id"],
    )
    op.create_index(
        "uq_creator_account_scopes_grant",
        "creator_account_scopes",
        ["membership_id", "creator_organization_id", "project_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )

    permission_table = sa.table(
        "permissions",
        sa.column("code", sa.String()),
        sa.column("description", sa.Text()),
    )
    op.bulk_insert(
        permission_table,
        [{"code": code, "description": description} for code, description in PERMISSIONS],
    )
    role_table = sa.table(
        "roles",
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("is_system", sa.Boolean()),
    )
    op.bulk_insert(
        role_table,
        [
            {
                "name": role_name,
                "description": f"Oki system role: {role_name.replace('_', ' ')}.",
                "is_system": True,
            }
            for role_name in SYSTEM_ROLES
        ],
    )

    administrator_grants = tuple(("administrator", code) for code, _ in PERMISSIONS)
    op.execute(
        sa.text(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT roles.id, permissions.id
            FROM (VALUES """
            + _sql_values(ROLE_PERMISSIONS + administrator_grants)
            + """
            ) AS grants(role_name, permission_code)
            JOIN roles
              ON roles.name = grants.role_name
             AND roles.organization_id IS NULL
             AND roles.is_system
            JOIN permissions
              ON permissions.code = grants.permission_code
            ON CONFLICT (role_id, permission_id) DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APPLICATION_ROLE}') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE
                    ON TABLE creator_account_scopes TO {APPLICATION_ROLE};
                END IF;
            END
            $$
            """
        )
    )


def downgrade() -> None:
    role_names = ", ".join("'" + value + "'" for value in SYSTEM_ROLES)
    permission_codes = ", ".join("'" + code + "'" for code, _ in PERMISSIONS)
    op.execute(
        sa.text(
            f"""
            DELETE FROM role_permissions
            WHERE role_id IN (
                SELECT id FROM roles
                WHERE organization_id IS NULL AND is_system AND name IN ({role_names})
            )
              AND permission_id IN (
                SELECT id FROM permissions WHERE code IN ({permission_codes})
            )
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            DELETE FROM roles
            WHERE organization_id IS NULL
              AND is_system
              AND name IN ({role_names})
              AND NOT EXISTS (
                  SELECT 1
                  FROM memberships
                  WHERE memberships.role_id = roles.id
              )
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            DELETE FROM permissions AS p
            WHERE p.code IN ({permission_codes})
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions AS rp WHERE rp.permission_id = p.id
              )
            """
        )
    )
    op.drop_table("creator_account_scopes")
    op.drop_constraint("uq_projects_id_organization", "projects", type_="unique")
