"""验证任务创建和运行创建接口能够正确衔接。"""

import subprocess

from fastapi.testclient import TestClient

from evodev.api.app import app


def test_create_task_and_run(tmp_path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    with TestClient(app) as client:
        task_response = client.post(
            "/api/tasks",
            json={
                "repository_path": str(tmp_path),
                "issue_title": "示例问题",
                "issue_body": "修复示例缺陷。",
                "test_command": "pytest -q",
                "constraints": ["保持补丁范围最小"],
            },
        )
        assert task_response.status_code == 201

        task = task_response.json()
        run_response = client.post(f"/api/tasks/{task['id']}/runs")

    assert run_response.status_code == 202
    assert run_response.json()["task_id"] == task["id"]
    assert run_response.json()["max_iterations"] == 3
