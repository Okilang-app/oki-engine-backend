"""Stub sponsor detector that creates candidates from transcript keywords.

TODO: Replace with real audio fingerprinting, brand logo detection, and NLP models.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from oki.sponsors.enums import DetectionReason
from oki.sponsors.models import AdSegmentEvidence, AdSegments
from oki.sponsors.schemas import SponsorCandidateResponse


# Multilingual keyword list for MVP stub detection.
# Avoid overly broad single words (e.g. "спасибо", "банк" alone) that fire on
# non-sponsored mentions; prefer phrases or compound expressions.
SPONSOR_KEYWORDS = {
    # English
    "sponsor", "sponsored", "sponsored by", "promo code", "promo",
    "discount code", "use code", "thanks to", "brought to you by",
    "partner", "affiliate", "powered by", "presented by", "financed by",
    # Russian
    "спонсор", "спонсоры", "спонсор ролика", "спонсор выпуска",
    "промокод", "промо", "скидка", "партнёр", "партнер",
    "при поддержке", "сделано при поддержке", "благодаря",
    "по ссылке",            # needs contiguous merge to reduce noise
    "наши друзья", "наш партнёр",
    # Sponsor giveaway cues
    "переходите по ссылке", "ссылка в описании и закреплённом комментарии",
}


class StubSponsorDetector:
    """Detect sponsor segments by keyword matching on transcript text."""

    async def detect_from_transcript(
        self,
        job_id: UUID,
        asset_id: UUID,
        organization_id: UUID,
        segments: list[dict],
    ) -> list[SponsorCandidateResponse]:
        """Return sponsor candidates where transcript text contains keywords.

        Each segment dict should have: segment_id, text, start_time, end_time.
        """
        candidates: list[SponsorCandidateResponse] = []
        for seg in segments:
            text = seg.get("text", "").lower()
            if any(kw in text for kw in SPONSOR_KEYWORDS):
                now = datetime.now(UTC)
                candidate = SponsorCandidateResponse(
                    id=uuid4(),  # placeholder until persisted
                    job_id=job_id,
                    asset_id=asset_id,
                    start_time=seg["start_time"],
                    end_time=seg["end_time"],
                    sponsor_name=None,
                    status="detected",
                    detection_reason=DetectionReason.KEYWORD,
                    confidence=0.6,
                    created_at=now,
                    updated_at=now,
                )
                candidates.append(candidate)
        return candidates

    def build_ad_segment(
        self,
        job_id: UUID,
        asset_id: UUID,
        organization_id: UUID,
        user_id: UUID,
        start_time: float,
        end_time: float,
        sponsor_name: str | None = None,
    ) -> AdSegments:
        return AdSegments(
            organization_id=organization_id,
            asset_id=asset_id,
            job_id=job_id,
            start_time=start_time,
            end_time=end_time,
            sponsor_name=sponsor_name,
            status="detected",
            replacement_type=None,
            reason_note=None,
            reviewed_by_user_id=None,
            reviewed_at=None,
        )

    def build_evidence(
        self,
        ad_segment_id: UUID,
        organization_id: UUID,
        source_segment_id: UUID | None,
        confidence: float | None = None,
    ) -> AdSegmentEvidence:
        return AdSegmentEvidence(
            organization_id=organization_id,
            ad_segment_id=ad_segment_id,
            evidence_type=DetectionReason.KEYWORD,
            source_segment_id=source_segment_id,
            evidence_data={"method": "keyword_match"},
            confidence=confidence,
        )
