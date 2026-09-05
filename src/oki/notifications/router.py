from uuid import UUID

from fastapi import APIRouter, Depends, Request

from oki.api.errors import ProblemException
from oki.identity.dependencies import current_principal
from oki.identity.schemas import Principal
from oki.notifications.schemas import (
    NotificationCreateRequest,
    NotificationListResponse,
    NotificationResponse,
)
from oki.notifications.service import NotificationService

router = APIRouter(prefix="/api", tags=["notifications"])


def _service(request: Request) -> NotificationService:
    service = getattr(request.app.state, "notifications_service", None)
    if service is None:
        raise ProblemException(
            status_code=503,
            code="service_unavailable",
            title="Notifications service unavailable",
            detail="The notifications service is not available.",
            retryable=True,
        )
    return service


@router.get("/notifications", response_model=NotificationListResponse)
async def list_notifications(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    unread_only: bool = False,
    principal: Principal = Depends(current_principal),
) -> NotificationListResponse:
    items, total = await _service(request).list_for_user(
        principal=principal,
        limit=limit,
        offset=offset,
        unread_only=unread_only,
    )
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(n) for n in items],
        total=total,
    )


@router.post("/notifications/{notification_id}/mark-read", response_model=NotificationResponse)
async def mark_read(
    notification_id: UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> NotificationResponse:
    notification = await _service(request).mark_read(
        notification_id=notification_id,
        principal=principal,
    )
    return NotificationResponse.model_validate(notification)


@router.post("/notifications", response_model=NotificationResponse, status_code=201)
async def create_notification(
    payload: NotificationCreateRequest,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> NotificationResponse:
    notification = await _service(request).send(
        payload=payload,
        principal=principal,
    )
    return NotificationResponse.model_validate(notification)
