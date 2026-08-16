from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from oki.api.errors import ProblemException, generate_correlation_id, parse_correlation_id
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.finance.schemas import (
    ExportRequest,
    FinanceExportResponse,
    PayoutApprovalResponse,
    PayoutRunCreate,
    PayoutRunResponse,
)
from oki.finance.service import FinanceService

router = APIRouter(prefix="/api", tags=["finance"])


def _service(request: Request) -> FinanceService:
    service = getattr(request.app.state, "finance_service", None)
    if not isinstance(service, FinanceService):
        raise ProblemException(
            status_code=503,
            code="finance_service_unavailable",
            title="Finance service unavailable",
            detail="Finance management is not available.",
            retryable=True,
        )
    return service


def _correlation_id(request: Request) -> UUID:
    value = parse_correlation_id(str(getattr(request.state, "correlation_id", "")))
    return UUID(value or generate_correlation_id())


@router.post("/finance/payouts", response_model=PayoutRunResponse, status_code=status.HTTP_201_CREATED)
async def create_payout_run(
    request: Request,
    payload: PayoutRunCreate,
    principal: Principal = Depends(current_principal),
) -> PayoutRunResponse:
    run = await _service(request).create_run(
        payload,
        principal,
        _correlation_id(request),
    )
    return PayoutRunResponse.model_validate(run)


@router.get("/finance/payouts", response_model=list[PayoutRunResponse])
async def list_payout_runs(
    request: Request,
    principal: Principal = Depends(current_principal),
) -> list[PayoutRunResponse]:
    runs = await _service(request).list_runs(principal)
    return [PayoutRunResponse.model_validate(run) for run in runs]


@router.post("/finance/payouts/{run_id}/approve", response_model=PayoutApprovalResponse)
async def approve_payout_run(
    run_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> PayoutApprovalResponse:
    approval = await _service(request).approve_run(
        run_id,
        principal,
        _correlation_id(request),
    )
    return PayoutApprovalResponse.model_validate(approval)


@router.post("/finance/payouts/{run_id}/export", response_model=FinanceExportResponse)
async def export_payout_run(
    run_id: UUID,
    request: Request,
    payload: ExportRequest,
    principal: Principal = Depends(current_principal),
) -> FinanceExportResponse:
    export_record = await _service(request).export(
        run_id,
        payload.export_type,
        principal,
        _correlation_id(request),
    )
    return FinanceExportResponse.model_validate(export_record)
