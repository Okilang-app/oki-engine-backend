from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from oki.voices.enums import VoiceMode


class PronunciationEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    voice_profile_id: UUID
    original_text: str
    pronunciation: str
    part_of_speech: str | None
    language_code: str
    created_at: datetime
    updated_at: datetime


class VoiceProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    creator_id: UUID | None
    name: str
    mode: VoiceMode
    language_code: str
    provider_key: str
    provider_voice_id: str | None
    ssml_config: dict[str, Any]
    consent_reference: str | None
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class VoiceProfileCreate(BaseModel):
    name: str
    mode: VoiceMode
    language_code: str
    provider_key: str = "elevenlabs"
    provider_voice_id: str | None = None
    creator_id: UUID | None = None
    consent_reference: str | None = None


class VoiceProfileUpdate(BaseModel):
    name: str | None = None
    provider_voice_id: str | None = None
    language_code: str | None = None
    consent_reference: str | None = None


class ElevenLabsVoiceResponse(BaseModel):
    voice_id: str
    name: str
