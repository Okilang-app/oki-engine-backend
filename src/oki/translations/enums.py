from enum import StrEnum


class TranslationStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    REVIEW_PENDING = "review_pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class QaDimension(StrEnum):
    # SOW Section 8.6 dimensions (primary)
    MEANING_ACCURACY = "meaning_accuracy"
    NATURALNESS = "naturalness"
    TIMING_FIT = "timing_fit"
    TERMINOLOGY = "terminology"
    NAMED_ENTITIES = "named_entities"
    BRAND_SAFETY = "brand_safety"
    CREATOR_VOICE_MATCH = "creator_voice_match"
    # Legacy dimensions kept for backward compatibility with stored records
    ACCURACY = "accuracy"
    FLUENCY = "fluency"
    STYLE = "style"
    LOCALE = "locale"
    FORMAT = "format"
    SAFETY = "safety"


SOW_DIMENSIONS = (
    QaDimension.MEANING_ACCURACY,
    QaDimension.NATURALNESS,
    QaDimension.TIMING_FIT,
    QaDimension.TERMINOLOGY,
    QaDimension.NAMED_ENTITIES,
    QaDimension.BRAND_SAFETY,
    QaDimension.CREATOR_VOICE_MATCH,
)

PASS_FAIL_DIMENSIONS = frozenset({
    QaDimension.TERMINOLOGY,
    QaDimension.NAMED_ENTITIES,
    QaDimension.BRAND_SAFETY,
})


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
