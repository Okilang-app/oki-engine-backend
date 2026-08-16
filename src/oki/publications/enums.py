from enum import StrEnum


class PublicationStatus(StrEnum):
    DRAFT = "draft"
    PRIVATE_UPLOADED = "private_uploaded"
    PLATFORM_CHECK_PENDING = "platform_check_pending"
    APPROVED = "approved"
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"
    FAILED = "failed"


class PublicationMode(StrEnum):
    CREATOR_CHANNEL_LOCALIZATION = "creator_channel_localization"
    LICENSED_REGIONAL_CHANNEL = "licensed_regional_channel"
    ORIGINAL_LOCAL_ADAPTATION = "original_local_adaptation"
