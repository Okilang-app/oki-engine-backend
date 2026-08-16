from oki.shorts.models import ShortCandidates


class ShortScorer:
    """Stub scorer for short candidates.

    TODO: integrate with ML scoring pipeline for factor analysis.
    """

    @staticmethod
    def score(candidate: ShortCandidates) -> dict:
        """Compute scores for all 9 factors from SOW.

        Returns a dict with individual factor scores and a total.
        """
        del candidate
        return {
            "hook_strength": 0.0,
            "pacing": 0.0,
            "audio_clarity": 0.0,
            "visual_engagement": 0.0,
            "brand_safety": 0.0,
            "language_clarity": 0.0,
            "cultural_resonance": 0.0,
            "platform_fit": 0.0,
            "monetization_potential": 0.0,
            "total": 0.0,
        }
