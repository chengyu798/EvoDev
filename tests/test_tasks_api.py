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
                "issue_title": "Example",
                "issue_body": "Fix an example bug.",
                "test_command": "pytest -q",
                "constraints": ["Keep the patch minimal"],
                "max_iterations": 2,
            },
        )
        assert task_response.status_code == 201

        task = task_response.json()
        run_response = client.post(f"/api/tasks/{task['id']}/runs")

    assert run_response.status_code == 202
    assert run_response.json()["task_id"] == task["id"]
