from collections.abc import Callable
from datetime import datetime, timezone
from typing import NoReturn
from uuid import UUID

import httpx
from sqlalchemy import func, select

from oki.api.errors import ProblemException
from oki.config import Settings, get_settings
from oki.db.uow import UnitOfWork
from oki.identity.authorization import Authorizer
from oki.identity.schemas import Principal, ResourceScope
from oki.notifications.models import Notification, NotificationChannel, NotificationStatus
from oki.notifications.schemas import NotificationCreateRequest


class NotificationService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        authorizer: Authorizer,
        settings: Settings | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer
        self._settings = settings or get_settings()

    async def send(
        self,
        payload: NotificationCreateRequest,
        principal: Principal,
    ) -> Notification:
        self._authorizer.require(
            principal=principal,
            scope=self._scope(payload.organization_id),
            action="notification:send",
        )

        notification = Notification(
            organization_id=payload.organization_id,
            user_id=payload.user_id,
            channel=payload.channel.value,
            subject=payload.subject,
            body=payload.body,
            send_at=payload.send_at,
        )

        # For IN_APP: mark immediately as sent
        if payload.channel == NotificationChannel.IN_APP:
            notification.status = NotificationStatus.SENT.value
            notification.sent_at = datetime.now(timezone.utc)
        # For EMAIL: leave as PENDING for background worker or attempt inline
        elif payload.channel == NotificationChannel.EMAIL:
            notification = await self._send_email(notification)
        elif payload.channel == NotificationChannel.TELEGRAM:
            notification = await self._send_telegram(notification)

        async with self._uow_factory() as uow:
            uow.session.add(notification)
            await uow.session.flush()
            return notification

    async def list_for_user(
        self,
        principal: Principal,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
    ) -> tuple[list[Notification], int]:
        org_ids = [
            m.organization_id for m in principal.memberships
        ]

        async with self._uow_factory() as uow:
            where_clause = [
                Notification.user_id == principal.user_id,
                Notification.organization_id.in_(org_ids),
            ]
            if unread_only:
                where_clause.append(Notification.read_at.is_(None))

            stmt = (
                select(Notification)
                .where(*where_clause)
                .order_by(Notification.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await uow.session.scalars(stmt)
            items = list(result.all())

            count_stmt = (
                select(func.count(Notification.id))
                .where(*where_clause)
            )
            total = await uow.session.scalar(count_stmt) or 0
            return items, total

    async def mark_read(
        self,
        notification_id: UUID,
        principal: Principal,
    ) -> Notification:
        async with self._uow_factory() as uow:
            notification = await uow.session.get(Notification, notification_id)
            if notification is None:
                self._not_found("notification_not_found", "Notification not found")

            self._authorizer.require(
                principal=principal,
                scope=self._scope(notification.organization_id),
                action="notification:update",
            )

            if notification.user_id != principal.user_id:
                self._not_found("notification_not_found", "Notification not found")

            notification.read_at = datetime.now(timezone.utc)
            return notification

    async def _send_email(self, notification: Notification) -> Notification:
        if not self._settings.smtp_host:
            # No SMTP configured — leave as pending for worker
            return notification

        try:
            import aiosmtplib
            await aiosmtplib.send(
                message=notification.body,
                sender=self._settings.notification_from_email,
                recipients=[notification.user_id],  # placeholder
                hostname=self._settings.smtp_host,
                port=self._settings.smtp_port,
                username=self._settings.smtp_user,
                password=self._settings.smtp_password,
                start_tls=True,
            )
            notification.status = NotificationStatus.SENT.value
            notification.sent_at = datetime.now(timezone.utc)
        except Exception as exc:
            notification.status = NotificationStatus.FAILED.value
            notification.error_message = str(exc)
        return notification

    async def _send_telegram(self, notification: Notification) -> Notification:
        token = self._settings.telegram_bot_token
        if not token:
            notification.status = NotificationStatus.FAILED.value
            notification.error_message = "Telegram bot token not configured"
            return notification

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # user_id is used as the Telegram chat ID
                chat_id = str(notification.user_id) if notification.user_id else None
                if not chat_id:
                    notification.status = NotificationStatus.FAILED.value
                    notification.error_message = "No user_id set for Telegram notification"
                    return notification

                response = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": f"{notification.subject}\n\n{notification.body}",
                        "parse_mode": "HTML",
                    },
                )
                response.raise_for_status()
                data = response.json()
                if not data.get("ok"):
                    notification.status = NotificationStatus.FAILED.value
                    notification.error_message = data.get("description", "Telegram API error")
                else:
                    notification.status = NotificationStatus.SENT.value
                    notification.sent_at = datetime.now(timezone.utc)
        except Exception as exc:
            notification.status = NotificationStatus.FAILED.value
            notification.error_message = str(exc)
        return notification

    @staticmethod
    def _scope(organization_id: UUID) -> ResourceScope:
        return ResourceScope(organization_id=organization_id)

    @staticmethod
    def _not_found(code: str, title: str) -> NoReturn:
        raise ProblemException(
            status_code=404,
            code=code,
            title=title,
            detail=f"{title}.",
        )
