from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from oki.db.base import Base
from oki.db.mixins import TimestampMixin
from oki.voices.enums import VoiceMode


def _enum_values(enum_type: type[Any]) -> list[str]:
    return [member.value for member in enum_type]


VOICE_MODE_TYPE = Enum(
    VoiceMode,
    name="voice_mode",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=_enum_values,
)


class VoiceProfile(TimestampMixin, Base):
    __tablename__ = "voice_profiles"
    __table_args__ = (
        Index("ix_voice_profiles_organization", "organization_id"),
        Index("ix_voice_profiles_creator", "creator_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    creator_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("creators.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[VoiceMode] = mapped_column(VOICE_MODE_TYPE, nullable=False)
    language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(100), nullable=False, default="internal")
    provider_voice_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssml_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    consent_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class PronunciationEntry(TimestampMixin, Base):
    __tablename__ = "pronunciation_entries"
    __table_args__ = (
        UniqueConstraint(
            "voice_profile_id", "original_text", "language_code",
            name="uq_pronunciation_entries_text_lang",
        ),
        Index("ix_pronunciation_entries_voice_profile", "voice_profile_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    voice_profile_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("voice_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    pronunciation: Mapped[str] = mapped_column(Text, nullable=False)
    part_of_speech: Mapped[str | None] = mapped_column(String(50), nullable=True)
    language_code: Mapped[str] = mapped_column(String(16), nullable=False)
