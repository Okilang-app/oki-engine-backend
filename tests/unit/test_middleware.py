from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from oki.main import create_app

KNOWN_UUID7 = "01890f58-e9f2-7cc2-98c4-dc0c0c07398f"


def test_generated_correlation_id_is_uuid7_and_matches_problem_body() -> None:
    response = TestClient(create_app()).get("/missing")

    correlation_id = response.headers["x-correlation-id"]
    assert UUID(correlation_id).version == 7
    assert response.json()["correlation_id"] == correlation_id


def test_valid_inbound_uuid7_is_propagated() -> None:
    response = TestClient(create_app()).get(
        "/health",
        headers={"X-Correlation-ID": KNOWN_UUID7},
    )

    assert response.headers["x-correlation-id"] == KNOWN_UUID7


@pytest.mark.parametrize(
    "supplied",
    [
        "not-a-uuid",
        "35f0d7a8-bd27-4bb0-8b8b-fd54e169e30a",
    ],
)
def test_invalid_or_non_uuid7_correlation_id_is_replaced(supplied: str) -> None:
    response = TestClient(create_app()).get(
        "/health",
        headers={"X-Correlation-ID": supplied},
    )

    correlation_id = response.headers["x-correlation-id"]
    assert correlation_id != supplied
    assert UUID(correlation_id).version == 7


def test_unexpected_error_is_logged_with_correlation_without_detail_leak() -> None:
    app = create_app()

    def raise_unexpected_error() -> None:
        raise RuntimeError("sensitive failure detail")

    app.add_api_route("/_test/raise", raise_unexpected_error)

    with capture_logs() as logs:
        response = TestClient(app).get("/_test/raise")

    body = response.json()
    error_log = next(log for log in logs if log["event"] == "unhandled_http_exception")
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert body["code"] == "internal_server_error"
    assert "sensitive failure detail" not in response.text
    assert error_log["correlation_id"] == body["correlation_id"]
    assert error_log["exception_type"] == "RuntimeError"
    assert error_log["exc_info"] is True
