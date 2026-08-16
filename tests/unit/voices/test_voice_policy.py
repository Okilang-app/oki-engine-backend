from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from oki.rights.enums import ConsentDecision
from oki.rights.models import RightsAgreement, RightsAgreementVersion, RightsGrant, VoiceConsent
from oki.voices.enums import VoiceMode
import dataclasses
from oki.voices.policy import VoicePolicy, VoicePolicyRequest


@pytest.fixture
def base_request() -> VoicePolicyRequest:
    return VoicePolicyRequest(
        organization_id=uuid4(),
        creator_id=uuid4(),
        agreement_version_id=uuid4(),
        voice_mode=VoiceMode.LICENSED_NEUTRAL_VOICE,
        language_code="es",
        territory_code="MX",
    )


@pytest.fixture
def agreement() -> RightsAgreement:
    return RightsAgreement(  # type: ignore[call-arg]
        id=uuid4(),
        organization_id=uuid4(),
        creator_id=uuid4(),
        title="Test",
        external_reference="ref-1",
        created_by_user_id=uuid4(),
    )


@pytest.fixture
def version(agreement: RightsAgreement) -> RightsAgreementVersion:
    return RightsAgreementVersion(  # type: ignore[call-arg]
        id=uuid4(),
        organization_id=agreement.organization_id,
        agreement_id=agreement.id,
        agreement_version_number=1,
        contract_reference="ref",
        contract_sha256="a" * 64,
        effective_from=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=365),
        termination_notice_days=30,
        termination_terms="",
        monetization_mode="none",
        fixed_fee_amount=None,
        revenue_share_bps=None,
        payout_currency="USD",
        payout_frequency="monthly",
        payout_terms="",
        created_by_user_id=uuid4(),
    )


@pytest.fixture
def grant(version: RightsAgreementVersion) -> RightsGrant:
    return RightsGrant(  # type: ignore[call-arg]
        id=uuid4(),
        organization_id=version.organization_id,
        agreement_version_id=version.id,
        asset_scope="all",
        asset_reference=None,
        language_code="es",
        territory_code="MX",
        platform="youtube",
        content_format="full",
        translation_allowed=True,
        dubbing_allowed=True,
        editing_allowed=True,
        metadata_allowed=True,
        likeness_allowed=True,
        brand_use_allowed=True,
        sponsor_removal_allowed=True,
        sponsor_replacement_mode="full",
        endorsement_mode="none",
        voice_clone_allowed=True,
        creator_approval_policy="not_required",
        starts_at=None,
        ends_at=None,
        created_by_user_id=uuid4(),
    )


def test_licensed_neutral_voice_approved(base_request: VoicePolicyRequest, agreement: RightsAgreement, version: RightsAgreementVersion, grant: RightsGrant) -> None:
    result = VoicePolicy.require(
        base_request,
        agreement=agreement,
        version=version,
        grants=(grant,),
        voice_consents=(),
    )
    assert result.approved is True


def test_creator_clone_missing_consent(base_request: VoicePolicyRequest, agreement: RightsAgreement, version: RightsAgreementVersion, grant: RightsGrant) -> None:
    base_request = dataclasses.replace(
        base_request, voice_mode=VoiceMode.CREATOR_APPROVED_CLONE
    )
    result = VoicePolicy.require(
        base_request,
        agreement=agreement,
        version=version,
        grants=(grant,),
        voice_consents=(),
    )
    assert result.approved is False
    assert result.reason_code == "voice_clone_consent_missing"


def test_creator_clone_with_consent_approved(base_request: VoicePolicyRequest, agreement: RightsAgreement, version: RightsAgreementVersion, grant: RightsGrant) -> None:
    base_request = dataclasses.replace(
        base_request, voice_mode=VoiceMode.CREATOR_APPROVED_CLONE
    )
    consent = VoiceConsent(  # type: ignore[call-arg]
        id=uuid4(),
        organization_id=agreement.organization_id,
        agreement_id=agreement.id,
        agreement_version_id=version.id,
        decision=ConsentDecision.GRANTED,
        supersedes_consent_id=None,
        language_code="es",
        territory_code="MX",
        platform="youtube",
        provider="internal",
        purpose="dubbing",
        evidence_reference="ref",
        evidence_sha256="a" * 64,
        effective_from=datetime.now(UTC) - timedelta(days=1),
        expires_at=datetime.now(UTC) + timedelta(days=365),
        decided_by_user_id=uuid4(),
    )
    result = VoicePolicy.require(
        base_request,
        agreement=agreement,
        version=version,
        grants=(grant,),
        voice_consents=(consent,),
    )
    assert result.approved is True
    assert result.voice_consent_id == consent.id


def test_human_voice_actor_missing_likeness(base_request: VoicePolicyRequest, agreement: RightsAgreement, version: RightsAgreementVersion) -> None:
    base_request = dataclasses.replace(
        base_request, voice_mode=VoiceMode.HUMAN_VOICE_ACTOR
    )
    grant = RightsGrant(  # type: ignore[call-arg]
        id=uuid4(),
        organization_id=agreement.organization_id,
        agreement_version_id=version.id,
        asset_scope="all",
        asset_reference=None,
        language_code="es",
        territory_code="MX",
        platform="youtube",
        content_format="full",
        translation_allowed=True,
        dubbing_allowed=True,
        editing_allowed=True,
        metadata_allowed=True,
        likeness_allowed=False,
        brand_use_allowed=True,
        sponsor_removal_allowed=True,
        sponsor_replacement_mode="full",
        endorsement_mode="none",
        voice_clone_allowed=True,
        creator_approval_policy="not_required",
        starts_at=None,
        ends_at=None,
        created_by_user_id=uuid4(),
    )
    result = VoicePolicy.require(
        base_request,
        agreement=agreement,
        version=version,
        grants=(grant,),
        voice_consents=(),
    )
    assert result.approved is False
    assert result.reason_code == "likeness_not_granted"


def test_dubbing_not_granted(base_request: VoicePolicyRequest, agreement: RightsAgreement, version: RightsAgreementVersion) -> None:
    grant = RightsGrant(  # type: ignore[call-arg]
        id=uuid4(),
        organization_id=agreement.organization_id,
        agreement_version_id=version.id,
        asset_scope="all",
        asset_reference=None,
        language_code="es",
        territory_code="MX",
        platform="youtube",
        content_format="full",
        translation_allowed=True,
        dubbing_allowed=False,
        editing_allowed=True,
        metadata_allowed=True,
        likeness_allowed=True,
        brand_use_allowed=True,
        sponsor_removal_allowed=True,
        sponsor_replacement_mode="full",
        endorsement_mode="none",
        voice_clone_allowed=True,
        creator_approval_policy="not_required",
        starts_at=None,
        ends_at=None,
        created_by_user_id=uuid4(),
    )
    result = VoicePolicy.require(
        base_request,
        agreement=agreement,
        version=version,
        grants=(grant,),
        voice_consents=(),
    )
    assert result.approved is False
    assert result.reason_code == "dubbing_not_granted"


def test_agreement_missing(base_request: VoicePolicyRequest) -> None:
    result = VoicePolicy.require(
        base_request,
        agreement=None,
        version=None,
        grants=(),
        voice_consents=(),
    )
    assert result.approved is False
    assert result.reason_code == "agreement_missing"
