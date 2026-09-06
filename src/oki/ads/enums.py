from enum import StrEnum


class AdStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class AdFormat(StrEnum):
    BUMPER_10S = "bumper_10s"
    NEUTRAL_AD_15S = "neutral_ad_15s"
    PRODUCT_DEMO_30S = "product_demo_30s"
    EDUCATIONAL_45S = "educational_45s"
    VISUAL_ONLY = "visual_only"
    VOICE_ONLY = "voice_only"
    CREATOR_RECORDED = "creator_recorded"
    LOCAL_LANGUAGE_UGC = "local_language_ugc"


class EndorsementMode(StrEnum):
    NONE = "none"
    NEUTRAL_DISCLOSURE = "neutral_disclosure"
    PERSONAL_ENDORSEMENT = "personal_endorsement"
