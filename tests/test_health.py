"""验证健康检查接口返回必要的运行环境信息。"""

from fastapi.testclient import TestClient

from evodev.api.app import create_app
from evodev.application.services import RunService, TaskService


def memory_services() -> tuple[TaskService, RunService]:
    task_service = TaskService()
    return task_service, RunService(task_service)


def test_health_endpoint() -> None:
    with TestClient(create_app(memory_services)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"] == "0.1.0"
    assert isinstance(payload["docker_available"], bool)
