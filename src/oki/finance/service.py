from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import select

from oki.api.errors import ProblemException
from oki.creators.models import Creator
from oki.creators.service import add_mutation_evidence
from oki.db.uow import UnitOfWork
from oki.finance.calculator import PayoutCalculator
from oki.finance.models import (
    CreatorPayouts,
    FinanceExports,
    PayoutApprovals,
    PayoutInputs,
    PayoutRuns,
)
from oki.finance.schemas import PayoutRunCreate
from oki.identity.authorization import Authorizer
from oki.identity.enums import Action
from oki.identity.schemas import Principal, ResourceScope
import csv
import hashlib
import io
from oki.rights.models import RightsAgreement, RightsAgreementVersion
from oki.storage.s3 import S3ObjectStore


class FinanceService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        authorizer: Authorizer,
        store: S3ObjectStore | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorizer = authorizer
        self._store = store

    async def create_run(
        self,
        payload: PayoutRunCreate,
        principal: Principal,
        correlation_id: UUID,
    ) -> PayoutRuns:
        self._authorizer.require(
            principal,
            Action.PAYOUT_APPROVE,
            self._scope(payload.organization_id),
        )

        async with self._uow_factory() as uow:
            run = PayoutRuns(
                organization_id=payload.organization_id,
                period_start=payload.period_start,
                period_end=payload.period_end,
                status="draft",
                total_gross=Decimal("0"),
                total_fees=Decimal("0"),
                total_payouts=Decimal("0"),
                currency=payload.currency.upper(),
                created_by_user_id=principal.user_id,
            )
            uow.session.add(run)
            await uow.session.flush()

            total_gross = Decimal("0")
            for item in payload.inputs:
                creator = await uow.session.get(Creator, item.creator_id)
                if creator is None:
                    self._not_found("creator_not_found", "Creator not found")

                payout_input = PayoutInputs(
                    organization_id=payload.organization_id,
                    run_id=run.id,
                    creator_id=item.creator_id,
                    revenue_share_basis=item.revenue_share_basis,
                    deductions=item.deductions,
                    bonus=item.bonus,
                    currency=item.currency.upper(),
                    exchange_rate=item.exchange_rate,
                )
                uow.session.add(payout_input)

                # Placeholder: use revenue_share_basis as gross for accumulation
                total_gross += item.revenue_share_basis

                # Load creator's latest agreement and version for revenue share
                agreement = await uow.session.scalar(
                    select(RightsAgreement)
                    .where(
                        RightsAgreement.creator_id == item.creator_id,
                        RightsAgreement.organization_id == payload.organization_id,
                    )
                    .order_by(RightsAgreement.created_at.desc())
                    .limit(1)
                )
                share_bps = 5000  # default 50%
                if agreement is not None:
                    version = await uow.session.scalar(
                        select(RightsAgreementVersion)
                        .where(RightsAgreementVersion.agreement_id == agreement.id)
                        .order_by(RightsAgreementVersion.agreement_version_number.desc())
                        .limit(1)
                    )
                    if version is not None and version.revenue_share_bps is not None:
                        share_bps = int(version.revenue_share_bps)

                calculated = PayoutCalculator.calculate(
                    gross=item.revenue_share_basis,
                    share_bps=share_bps,
                    currency=item.currency,
                )
                payout = CreatorPayouts(
                    organization_id=payload.organization_id,
                    run_id=run.id,
                    input_id=payout_input.id,
                    creator_id=item.creator_id,
                    calculated_amount=calculated,
                    currency=item.currency.upper(),
                    transfer_method=None,
                    transfer_reference=None,
                    status="pending",
                    paid_at=None,
                )
                uow.session.add(payout)

            run.total_gross = total_gross
            run.total_payouts = total_gross  # TODO: apply fees/deductions
            await uow.session.flush()

            add_mutation_evidence(
                uow,
                principal=principal,
                organization_id=payload.organization_id,
                entity_type="payout_run",
                entity_id=run.id,
                action="payout_run.create",
                correlation_id=correlation_id,
                new_values={
                    "period_start": run.period_start.isoformat(),
                    "period_end": run.period_end.isoformat(),
                    "currency": run.currency,
                },
            )
            return run

    async def approve_run(
        self,
        run_id: UUID,
        principal: Principal,
        correlation_id: UUID,
    ) -> PayoutApprovals:
        async with self._uow_factory() as uow:
            run = await uow.session.get(PayoutRuns, run_id)
            if run is None:
                self._not_found("payout_run_not_found", "Payout run not found")

            self._authorizer.require(
                principal,
                Action.PAYOUT_APPROVE,
                self._scope(run.organization_id),
            )

            approval = PayoutApprovals(
                organization_id=run.organization_id,
                run_id=run.id,
                approved_by_user_id=principal.user_id,
                approved_at=datetime.now(datetime.timezone.utc),
            )
            uow.session.add(approval)

            run.status = "approved"
            await uow.session.flush()

            add_mutation_evidence(
                uow,
                principal=principal,
                organization_id=run.organization_id,
                entity_type="payout_approval",
                entity_id=approval.id,
                action="payout_run.approve",
                correlation_id=correlation_id,
                new_values={"run_id": str(run.id), "status": "approved"},
            )
            return approval

    async def export(
        self,
        run_id: UUID,
        export_type: str,
        principal: Principal,
        correlation_id: UUID,
    ) -> FinanceExports:
        async with self._uow_factory() as uow:
            run = await uow.session.get(PayoutRuns, run_id)
            if run is None:
                self._not_found("payout_run_not_found", "Payout run not found")

            self._authorizer.require(
                principal,
                Action.PAYOUT_APPROVE,
                self._scope(run.organization_id),
            )

            export_record = FinanceExports(
                organization_id=run.organization_id,
                run_id=run.id,
                export_type=export_type,
                file_url=None,
                file_sha256=None,
                created_by_user_id=principal.user_id,
            )
            uow.session.add(export_record)
            await uow.session.flush()

            payouts = list(
                (
                    await uow.session.scalars(
                        select(CreatorPayouts).where(CreatorPayouts.run_id == run.id)
                    )
                ).all()
            )

            csv_buffer = io.StringIO()
            writer = csv.writer(csv_buffer)
            writer.writerow(
                [
                    "creator_name",
                    "total_views",
                    "revenue_share_bps",
                    "payout_amount",
                    "currency",
                    "period_start",
                    "period_end",
                ]
            )
            for payout in payouts:
                creator = await uow.session.get(Creator, payout.creator_id)
                creator_name = creator.display_name if creator else ""

                agreement = await uow.session.scalar(
                    select(RightsAgreement)
                    .where(
                        RightsAgreement.creator_id == payout.creator_id,
                        RightsAgreement.organization_id == run.organization_id,
                    )
                    .order_by(RightsAgreement.created_at.desc())
                    .limit(1)
                )
                revenue_share_bps = 5000
                if agreement is not None:
                    version = await uow.session.scalar(
                        select(RightsAgreementVersion)
                        .where(RightsAgreementVersion.agreement_id == agreement.id)
                        .order_by(RightsAgreementVersion.agreement_version_number.desc())
                        .limit(1)
                    )
                    if version is not None and version.revenue_share_bps is not None:
                        revenue_share_bps = int(version.revenue_share_bps)

                writer.writerow(
                    [
                        creator_name,
                        0,
                        revenue_share_bps,
                        str(payout.calculated_amount),
                        payout.currency,
                        run.period_start.isoformat(),
                        run.period_end.isoformat(),
                    ]
                )

            csv_bytes = csv_buffer.getvalue().encode("utf-8")
            file_key = f"finance/exports/{export_record.id}.csv"

            if self._store is not None:
                await self._store.put_object(file_key, csv_bytes, content_type="text/csv")
                file_url = await self._store.presign_get(file_key, expires_in=3600)
                file_sha256 = hashlib.sha256(csv_bytes).hexdigest()
                export_record.file_url = file_url
                export_record.file_sha256 = file_sha256
                await uow.session.flush()

            add_mutation_evidence(
                uow,
                principal=principal,
                organization_id=run.organization_id,
                entity_type="finance_export",
                entity_id=export_record.id,
                action="finance_export.create",
                correlation_id=correlation_id,
                new_values={"run_id": str(run.id), "export_type": export_type},
            )
            return export_record

    async def list_runs(
        self,
        principal: Principal,
    ) -> list[PayoutRuns]:
        org_ids = [m.organization_id for m in principal.memberships]
        if not org_ids:
            return []
        async with self._uow_factory() as uow:
            result = await uow.session.scalars(
                select(PayoutRuns)
                .where(PayoutRuns.organization_id.in_(org_ids))
                .order_by(PayoutRuns.period_start.desc())
            )
            return list(result.all())

    @staticmethod
    def _scope(organization_id: UUID) -> ResourceScope:
        return ResourceScope(
            organization_id=organization_id,
            creator_organization_id=organization_id,
        )

    @staticmethod
    def _not_found(code: str, title: str) -> NoReturn:
        raise ProblemException(
            status_code=404,
            code=code,
            title=title,
            detail=f"The requested {title.lower()} does not exist.",
        )
