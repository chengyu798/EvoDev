from fastapi.testclient import TestClient

from evodev.api.app import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"] == "0.1.0"
    assert isinstance(payload["docker_available"], bool)
