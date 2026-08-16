from enum import StrEnum


class ReviewDecisionType(StrEnum):
    APPROVED = "approved"
    APPROVED_WITH_COMMENTS = "approved_with_comments"
    CHANGES_REQUESTED = "changes_requested"
    REJECTED = "rejected"
