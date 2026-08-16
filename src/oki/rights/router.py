from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from oki.api.errors import ProblemException, generate_correlation_id, parse_correlation_id
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.rights.schemas import (
    AgreementCreate,
    AgreementDecisionResponse,
    AgreementResponse,
    AgreementVersionResponse,
    DecisionRequest,
    EndorsementConsentCreate,
    EndorsementConsentResponse,
    RightsGrantResponse,
    VoiceConsentCreate,
    VoiceConsentResponse,
)
from oki.rights.service import AgreementDetails, AgreementService

router = APIRouter(prefix="/api", tags=["rights"])


def _service(request: Request) -> AgreementService:
    service = getattr(request.app.state, "agreement_service", None)
    if not isinstance(service, AgreementService):
        raise ProblemException(
            status_code=503,
            code="agreement_service_unavailable",
            title="Agreement service unavailable",
            detail="Rights agreement management is not available.",
            retryable=True,
        )
    return service


def _correlation_id(request: Request) -> UUID:
    value = parse_correlation_id(str(getattr(request.state, "correlation_id", "")))
    return UUID(value or generate_correlation_id())


def _response(details: AgreementDetails) -> AgreementResponse:
    agreement = details.agreement
    version = details.version
    return AgreementResponse(
        id=agreement.id,
        organization_id=agreement.organization_id,
        creator_id=agreement.creator_id,
        title=agreement.title,
        external_reference=agreement.external_reference,
        latest_version=AgreementVersionResponse(
            id=version.id,
            agreement_id=version.agreement_id,
            agreement_version_number=version.agreement_version_number,
            contract_reference=version.contract_reference,
            contract_sha256=version.contract_sha256,
            effective_from=version.effective_from,
            expires_at=version.expires_at,
            termination_notice_days=version.termination_notice_days,
            termination_terms=version.termination_terms,
            monetization_mode=version.monetization_mode,
            fixed_fee_amount=version.fixed_fee_amount,
            revenue_share_bps=version.revenue_share_bps,
            payout_currency=version.payout_currency,
            payout_frequency=version.payout_frequency,
            payout_terms=version.payout_terms,
            submitted_at=version.submitted_at,
            grants=[RightsGrantResponse.model_validate(grant) for grant in details.grants],
            created_at=version.created_at,
            updated_at=version.updated_at,
            version=version.version,
        ),
        created_at=agreement.created_at,
        updated_at=agreement.updated_at,
        version=agreement.version,
    )


@router.post(
    "/creators/{creator_id}/agreements",
    response_model=AgreementResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_agreement_version(
    creator_id: UUID,
    payload: AgreementCreate,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> AgreementResponse:
    service = _service(request)
    agreement, _ = await service.create_version(
        principal,
        creator_id,
        payload,
        correlation_id=_correlation_id(request),
    )
    return _response(await service.get_details(principal, agreement.id))


@router.get("/agreements/{agreement_id}", response_model=AgreementResponse)
async def get_agreement(
    agreement_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> AgreementResponse:
    return _response(await _service(request).get_details(principal, agreement_id))


@router.post("/agreements/{agreement_id}/approve", response_model=AgreementDecisionResponse)
async def approve_agreement(
    agreement_id: UUID,
    request: Request,
    payload: DecisionRequest | None = None,
    principal: Principal = Depends(current_principal),
) -> AgreementDecisionResponse:
    data = payload or DecisionRequest()
    decision = await _service(request).approve(
        principal,
        agreement_id,
        reason=data.reason,
        agreement_version_id=data.agreement_version_id,
        correlation_id=_correlation_id(request),
    )
    return AgreementDecisionResponse.model_validate(decision)


@router.post("/agreements/{agreement_id}/revoke", response_model=AgreementDecisionResponse)
async def revoke_agreement(
    agreement_id: UUID,
    request: Request,
    payload: DecisionRequest | None = None,
    principal: Principal = Depends(current_principal),
) -> AgreementDecisionResponse:
    data = payload or DecisionRequest()
    decision = await _service(request).revoke(
        principal,
        agreement_id,
        reason=data.reason,
        agreement_version_id=data.agreement_version_id,
        correlation_id=_correlation_id(request),
    )
    return AgreementDecisionResponse.model_validate(decision)


@router.post(
    "/agreements/{agreement_id}/voice-consents",
    response_model=VoiceConsentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_voice_consent(
    agreement_id: UUID,
    payload: VoiceConsentCreate,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> VoiceConsentResponse:
    consent = await _service(request).record_voice_consent(
        principal,
        agreement_id,
        payload,
        correlation_id=_correlation_id(request),
    )
    return VoiceConsentResponse.model_validate(consent)


@router.post(
    "/agreements/{agreement_id}/endorsement-consents",
    response_model=EndorsementConsentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_endorsement_consent(
    agreement_id: UUID,
    payload: EndorsementConsentCreate,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> EndorsementConsentResponse:
    consent = await _service(request).record_endorsement_consent(
        principal,
        agreement_id,
        payload,
        correlation_id=_correlation_id(request),
    )
    return EndorsementConsentResponse.model_validate(consent)
