from fastapi.testclient import TestClient

from oki.main import create_app


def test_health_is_available_without_auth() -> None:
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_problem_response_has_stable_shape() -> None:
    response = TestClient(create_app()).get("/api/_test/not-found")
    body = response.json()
    assert response.status_code == 404
    assert body["type"].startswith("https://errors.oki.app/")
    assert body["code"] == "resource_not_found"
    assert body["correlation_id"]
