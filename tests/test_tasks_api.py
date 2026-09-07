"""验证任务创建和运行创建接口能够正确衔接。"""

import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient

from evodev.agents.schemas import ConversationReply
from evodev.api.app import create_app
from evodev.application.services import RunService, TaskService
from evodev.domain.tasks import TaskPlan
from evodev.persistence.artifacts import LocalArtifactStore


class FakeReadOnlyAgents:
    """为接口测试生成稳定的计划和对话结果。"""

    def create_plan(self, task, feedback=None) -> TaskPlan:
        del feedback
        return TaskPlan(
            version=len(task.plans) + 1,
            problem_summary="修复示例问题。",
            likely_root_cause="示例根因。",
            implementation_steps=["修改示例代码。"],
        )

    def converse(self, task, content, on_delta=None) -> ConversationReply:
        del task, content
        if on_delta:
            on_delta("示例回答。")
        return ConversationReply(intent="explain", response="示例回答。")


def memory_services() -> tuple[TaskService, RunService]:
    task_service = TaskService(read_only_agents=FakeReadOnlyAgents())
    return task_service, RunService(task_service)


def test_create_task_and_run(tmp_path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init", "-q"], check=True
    )

    with TestClient(create_app(memory_services)) as client:
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
        planned = client.post(f"/api/tasks/{task['id']}/plans", json={}).json()
        plan_id = planned["plans"][-1]["id"]
        client.post(f"/api/tasks/{task['id']}/plans/{plan_id}/approve")
        run_response = client.post(f"/api/tasks/{task['id']}/runs")
        list_response = client.get("/api/runs")
        artifacts_response = client.get(f"/api/runs/{run_response.json()['id']}/artifacts")

    assert run_response.status_code == 202
    assert run_response.json()["task_id"] == task["id"]
    assert run_response.json()["max_iterations"] == 3
    assert len(list_response.json()) == 1
    assert artifacts_response.status_code == 200
    assert artifacts_response.json()["agent_traces"] == []


def test_initial_message_uses_conversation_route_without_creating_plan(tmp_path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init", "-q"],
        check=True,
    )

    with TestClient(create_app(memory_services)) as client:
        task = client.post(
            "/api/tasks",
            json={
                "repository_path": str(tmp_path),
                "issue_title": "解释代码",
                "issue_body": "为什么这里可能出错？",
                "test_command": "pytest -q",
                "constraints": [],
            },
        ).json()
        response = client.post(f"/api/tasks/{task['id']}/respond")

    assert response.status_code == 200
    assert response.json()["messages"][-1]["content"] == "示例回答。"
    assert response.json()["plans"] == []


def test_conversation_stream_pushes_text_and_final_task(tmp_path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init", "-q"],
        check=True,
    )

    with TestClient(create_app(memory_services)) as client:
        task = client.post(
            "/api/tasks",
            json={
                "repository_path": str(tmp_path),
                "issue_title": "解释代码",
                "issue_body": "这个模块做什么？",
                "test_command": "pytest -q",
                "constraints": [],
            },
        ).json()
        with client.stream("POST", f"/api/tasks/{task['id']}/respond/stream") as response:
            body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: delta" in body
    assert '"delta": "示例回答。"' in body
    assert "event: complete" in body
    assert '"content": "示例回答。"' in body


def test_http_run_executes_workflow_and_returns_evidence(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "--allow-empty", "-m", "init", "-q"], check=True
    )
    artifact_store = LocalArtifactStore(tmp_path / "outputs")

    class Workflow:
        def execute(self, *, run_id: str, task, progress_callback=None):
            del task
            if progress_callback:
                progress_callback("run_tests", {"status": "testing", "iteration": 1})
            artifact_store.write_json(
                run_id,
                "test-1.json",
                {"exit_code": 0, "stdout": "2 passed"},
            )
            artifact_store.write_text(run_id, "result.patch", "+修复内容\n")
            return {
                "status": "succeeded",
                "iteration": 1,
                "tests_passed": True,
                "review_passed": True,
                "changed_files": ["example.py"],
                "retrieved_experience_ids": [],
                "retry_count": 0,
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "duration_ms": 20,
            }

    def services() -> tuple[TaskService, RunService]:
        task_service = TaskService(read_only_agents=FakeReadOnlyAgents())
        return task_service, RunService(
            task_service,
            workflow_service_factory=Workflow,
            artifact_store=artifact_store,
        )

    with TestClient(create_app(services)) as client:
        task = client.post(
            "/api/tasks",
            json={
                "repository_path": str(repository),
                "issue_title": "端到端任务",
                "issue_body": "验证接口到后台工作流。",
                "test_command": "pytest -q",
                "constraints": [],
            },
        ).json()
        planned = client.post(f"/api/tasks/{task['id']}/plans", json={}).json()
        plan_id = planned["plans"][-1]["id"]
        client.post(f"/api/tasks/{task['id']}/plans/{plan_id}/approve")
        run = client.post(f"/api/tasks/{task['id']}/runs").json()
        deadline = time.monotonic() + 2
        while run["status"] != "succeeded":
            assert time.monotonic() < deadline
            time.sleep(0.01)
            run = client.get(f"/api/runs/{run['id']}").json()
        artifacts = client.get(f"/api/runs/{run['id']}/artifacts").json()
        with client.stream("GET", f"/api/runs/{run['id']}/stream") as stream_response:
            stream_body = "".join(stream_response.iter_text())

    assert run["tests_passed"] is True
    assert artifacts["verification_tests"][0]["stdout"] == "2 passed"
    assert artifacts["patch"] == "+修复内容\n"
    assert stream_response.status_code == 200
    assert "event: run_event" in stream_body
    assert "event: stream_end" in stream_body
    assert '"event_type": "run.completed"' in stream_body
