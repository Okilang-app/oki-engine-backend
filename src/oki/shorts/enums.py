from enum import StrEnum


class ShortStatus(StrEnum):
    CANDIDATE = "candidate"
    SCORING = "scoring"
    REVISING = "revising"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
