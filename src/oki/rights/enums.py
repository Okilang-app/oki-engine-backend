from enum import StrEnum


class Platform(StrEnum):
    YOUTUBE = "youtube"
    YOUTUBE_MUSIC = "youtube_music"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    FACEBOOK = "facebook"
    OWNED_WEB = "owned_web"


class AssetScope(StrEnum):
    ALL = "all"
    CATEGORY = "category"
    ASSET = "asset"


class ContentFormat(StrEnum):
    FULL = "full"
    SHORTS = "shorts"


class SponsorReplacementMode(StrEnum):
    NONE = "none"
    VISUAL_ONLY = "visual_only"
    VOICE_ONLY = "voice_only"
    FULL = "full"


class EndorsementMode(StrEnum):
    NONE = "none"
    NEUTRAL_DISCLOSURE = "neutral_disclosure"
    PERSONAL = "personal"


class CreatorApprovalPolicy(StrEnum):
    NOT_REQUIRED = "not_required"
    FIRST_PER_LANGUAGE = "first_per_language"
    EVERY_PUBLICATION = "every_publication"


class MonetizationMode(StrEnum):
    NONE = "none"
    FIXED_FEE = "fixed_fee"
    REVENUE_SHARE = "revenue_share"
    HYBRID = "hybrid"


class AgreementDecisionType(StrEnum):
    APPROVED = "approved"
    REVOKED = "revoked"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class ConsentDecision(StrEnum):
    GRANTED = "granted"
    DENIED = "denied"
    REVOKED = "revoked"


class CreatorStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
