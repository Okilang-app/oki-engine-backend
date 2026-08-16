from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from oki.api.errors import ProblemException
from oki.campaigns.enums import CreativeStatus
from oki.campaigns.models import Creative
from oki.campaigns.service import CampaignService


class FakeUow:
    """Minimal Uow stand-in for eligibility unit tests."""

    def __init__(self, creatives: dict[str, Creative]) -> None:
        self._creatives = creatives
        self.session = self  # type: ignore[assignment]

    async def get(self, model: type[Creative], obj_id: object) -> Creative | None:
        return self._creatives.get(str(obj_id))

    async def flush(self) -> None:
        pass

    async def __aenter__(self) -> "FakeUow":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


class FakeAuthorizer:
    def require(self, principal: object, action: object, scope: object) -> None:
        pass


class FakePrincipal:
    user_id = uuid4()
    memberships = ()


def _make_creative(status: CreativeStatus, expires_at: datetime | None = None) -> Creative:
    org_id = uuid4()
    return Creative(  # type: ignore[call-arg]
        id=uuid4(),
        organization_id=org_id,
        campaign_id=uuid4(),
        name="Test Creative",
        creative_type="sponsor_integration",
        status=status,
        language_code="en",
        territory_code="US",
        sponsor_name="Sponsor",
        sponsor_product="Product",
        script_text=None,
        visual_reference_url=None,
        expires_at=expires_at,
        metadata={},
    )


@pytest.mark.asyncio
async def test_eligibility_approves_active_creative() -> None:
    creative = _make_creative(CreativeStatus.APPROVED)
    service = CampaignService(lambda: FakeUow({str(creative.id): creative}), FakeAuthorizer())
    result = await service.check_creative_eligibility(FakePrincipal(), creative.id)
    assert result.id == creative.id


@pytest.mark.asyncio
async def test_eligibility_rejects_expired_creative() -> None:
    creative = _make_creative(
        CreativeStatus.APPROVED,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    service = CampaignService(lambda: FakeUow({str(creative.id): creative}), FakeAuthorizer())
    with pytest.raises(ProblemException) as exc_info:
        await service.check_creative_eligibility(FakePrincipal(), creative.id)
    assert exc_info.value.code == "creative_expired"


@pytest.mark.asyncio
async def test_eligibility_rejects_rejected_status() -> None:
    creative = _make_creative(CreativeStatus.REJECTED)
    service = CampaignService(lambda: FakeUow({str(creative.id): creative}), FakeAuthorizer())
    with pytest.raises(ProblemException) as exc_info:
        await service.check_creative_eligibility(FakePrincipal(), creative.id)
    assert exc_info.value.code == "creative_not_usable"


@pytest.mark.asyncio
async def test_eligibility_accepts_draft_status() -> None:
    creative = _make_creative(CreativeStatus.DRAFT)
    service = CampaignService(lambda: FakeUow({str(creative.id): creative}), FakeAuthorizer())
    result = await service.check_creative_eligibility(FakePrincipal(), creative.id)
    assert result.id == creative.id
