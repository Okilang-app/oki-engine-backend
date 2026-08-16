from enum import StrEnum


class Action(StrEnum):
    """Stable Oki authorization actions stored as permission codes."""

    CREATOR_CREATE = "creator.create"
    CREATOR_READ = "creator.read"
    AGREEMENT_CREATE = "agreement.create"
    AGREEMENT_REVOKE = "agreement.revoke"
    PROJECT_READ = "project.read"
    AGREEMENT_APPROVE = "agreement.approve"
    VOICE_CONSENT_RECORD = "voice_consent.record"
    SPONSOR_REPLACE = "sponsor.replace"
    CREATOR_REVIEW_SUBMIT = "creator_review.submit"
    PUBLICATION_UPLOAD_PRIVATE = "publication.upload_private"
    PUBLICATION_RELEASE_PUBLIC = "publication.release_public"
    PUBLICATION_UNPUBLISH = "publication.unpublish"
    PAYOUT_APPROVE = "payout.approve"
    DEAD_LETTER_REPLAY = "dead_letter.replay"
    AUDIT_READ = "audit.read"
    ASSET_CREATE = "asset.create"
    ASSET_READ = "asset.read"
    ASSET_VALIDATE = "asset.validate"
    ASSET_DELETE = "asset.delete"
    CREATOR_DELETE = "creator.delete"
    PROJECT_DELETE = "project.delete"
    STEM_REGISTER = "stem.register"
