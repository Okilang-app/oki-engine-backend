from dataclasses import dataclass
from typing import Any, NoReturn
from uuid import UUID

from oki.api.errors import ProblemException
from oki.rights.enums import ConsentDecision
from oki.rights.models import RightsAgreement, RightsAgreementVersion, RightsGrant, VoiceConsent
from oki.voices.enums import VoiceMode


class VoicePolicyError(Exception):
    """Voice-specific policy violation."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class VoicePolicyRequest:
    organization_id: UUID
    creator_id: UUID
    agreement_version_id: UUID
    voice_mode: VoiceMode
    language_code: str
    territory_code: str


@dataclass(frozen=True, slots=True)
class VoicePolicyResult:
    approved: bool
    reason_code: str | None = None
    reason_detail: str | None = None
    voice_consent_id: UUID | None = None


class VoicePolicy:
    """Fail-closed voice policy: clones require separate consent."""

    @classmethod
    def require(
        cls,
        request: VoicePolicyRequest,
        agreement: RightsAgreement | None,
        version: RightsAgreementVersion | None,
        grants: tuple[RightsGrant, ...],
        voice_consents: tuple[VoiceConsent, ...],
    ) -> VoicePolicyResult:
        if agreement is None or version is None:
            return VoicePolicyResult(
                approved=False,
                reason_code="agreement_missing",
                reason_detail="No active agreement found for the creator.",
            )

        # Check dubbing allowance across grants
        dubbing_allowed = any(
            grant.dubbing_allowed
            and grant.language_code == request.language_code.lower()
            and grant.territory_code == request.territory_code.upper()
            for grant in grants
        )
        if not dubbing_allowed:
            return VoicePolicyResult(
                approved=False,
                reason_code="dubbing_not_granted",
                reason_detail="Rights grants do not allow dubbing for this language/territory.",
            )

        if request.voice_mode == VoiceMode.CREATOR_APPROVED_CLONE:
            # Fail closed: explicit clone consent required
            active_clones = [
                vc for vc in voice_consents
                if vc.decision == ConsentDecision.GRANTED
                and vc.language_code == request.language_code.lower()
                and (vc.expires_at is None or vc.expires_at > cls._now())
            ]
            if not active_clones:
                return VoicePolicyResult(
                    approved=False,
                    reason_code="voice_clone_consent_missing",
                    reason_detail="Creator-approved clone requires explicit, current voice consent.",
                )
            return VoicePolicyResult(
                approved=True,
                voice_consent_id=active_clones[0].id,
            )

        if request.voice_mode == VoiceMode.HUMAN_VOICE_ACTOR:
            # Check likeness rights for human actor representation
            likeness_allowed = any(
                grant.likeness_allowed
                and grant.language_code == request.language_code.lower()
                and grant.territory_code == request.territory_code.upper()
                for grant in grants
            )
            if not likeness_allowed:
                return VoicePolicyResult(
                    approved=False,
                    reason_code="likeness_not_granted",
                    reason_detail="Rights grants do not allow likeness use for this language/territory.",
                )
            return VoicePolicyResult(approved=True)

        if request.voice_mode == VoiceMode.LICENSED_NEUTRAL_VOICE:
            return VoicePolicyResult(approved=True)

        return VoicePolicyResult(
            approved=False,
            reason_code="voice_mode_unrecognized",
            reason_detail=f"Unrecognized voice mode: {request.voice_mode}",
        )

    @staticmethod
    def _now() -> Any:
        from datetime import UTC, datetime
        return datetime.now(UTC)

    @staticmethod
    def _deny(code: str, detail: str) -> NoReturn:
        raise ProblemException(
            status_code=403,
            code=code,
            title="Voice policy denied",
            detail=detail,
        )
