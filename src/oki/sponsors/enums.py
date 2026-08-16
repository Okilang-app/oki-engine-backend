from enum import StrEnum


class SponsorStatus(StrEnum):
    DETECTED = "detected"
    CONFIRMED = "confirmed"
    PROPOSED = "proposed"
    REPLACED = "replaced"
    REJECTED = "rejected"


class DetectionReason(StrEnum):
    KEYWORD = "keyword"
    AUDIO_FINGERPRINT = "audio_fingerprint"
    BRAND_LOGO = "brand_logo"
    ML_TRANSFORMER = "ml_transformer"
    MANUAL = "manual"


class ReplacementType(StrEnum):
    SKIP = "skip"
    MUTE = "mute"
    REPLACE_VOICE = "replace_voice"
    REPLACE_VISUAL = "replace_visual"
