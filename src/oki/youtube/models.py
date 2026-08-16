from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from oki.db.base import Base
from oki.db.mixins import TimestampMixin, VersionMixin
from oki.jobs import models as _jobs_models  # register FK targets
from oki.identity import models as _identity_models  # register FK targets


class OAuthConnection(TimestampMixin, VersionMixin, Base):
    __tablename__ = "oauth_connections"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    creator_id: Mapped[UUID] = mapped_column(
        ForeignKey("creators.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    access_token_encrypted: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )
    refresh_token_encrypted: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )
    token_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(String(512), nullable=False)
    state: Mapped[str | None] = mapped_column(String(256), nullable=True)
    code_verifier: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )


class AuthorizedChannel(Base):
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __tablename__ = "authorized_channels"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("oauth_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform_channel_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    channel_title: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
    )
    upload_defaults: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
