from enum import StrEnum


class CreativeType(StrEnum):
    SPONSOR_INTEGRATION = "sponsor_integration"
    PRODUCT_PLACEMENT = "product_placement"
    BRAND_MENTION = "brand_mention"
    ENDORSEMENT = "endorsement"
    CUSTOM = "custom"


class CreativeStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ARCHIVED = "archived"
