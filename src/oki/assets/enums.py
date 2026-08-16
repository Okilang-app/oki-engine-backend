"""Asset domain enumerations."""

from enum import StrEnum


class AssetStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class UploadStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class ValidationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"


class MediaStreamType(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    DATA = "data"


class MediaArtifactType(StrEnum):
    PROXY = "proxy"
    AUDIO_EXTRACT = "audio_extract"
    THUMBNAIL = "thumbnail"
    TRANSCRIPT = "transcript"
    STEM = "stem"
