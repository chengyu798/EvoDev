"""验证后台运行状态和运行产物聚合。"""

import subprocess
import time
from pathlib import Path
from threading import Event

import pytest

from evodev.agents.executor import AgentExecutionError
from evodev.agents.schemas import ConversationReply
from evodev.application.services import (
    ConversationExecutionError,
    PlanApprovalRequiredError,
    RunService,
    TaskService,
)
from evodev.domain.enums import TaskRunStatus
from evodev.domain.tasks import (
    PlanCreate,
    TaskCreate,
    TaskMessageCreate,
    TaskPlan,
    TaskTitleUpdate,
)
from evodev.persistence.artifacts import LocalArtifactStore


class FakeRepairWorkflow:
    """模拟完成两个节点的修复工作流。"""

    def __init__(self, artifact_store: LocalArtifactStore, invoked: Event) -> None:
        self.artifact_store = artifact_store
        self.invoked = invoked

    def execute(self, *, run_id: str, task, progress_callback=None):
        del task
        if progress_callback:
            progress_callback("prepare_workspace", {"status": "preparing"})
            progress_callback(
                "run_tests",
                {"status": "testing", "iteration": 1, "tests_passed": True},
            )
        self.artifact_store.write_json(
            run_id,
            "baseline-test.json",
            {"command": ["pytest", "-q"], "exit_code": 1, "stdout": "1 failed"},
        )
        self.artifact_store.write_json(
            run_id,
            "test-1.json",
            {"command": ["pytest", "-q"], "exit_code": 0, "stdout": "2 passed"},
        )
        self.artifact_store.write_text(run_id, "result.patch", "+return left + right\n")
        self.invoked.set()
        return {
            "status": "succeeded",
            "iteration": 1,
            "tests_passed": True,
            "review_passed": True,
            "changed_files": ["calculator.py"],
            "retrieved_experience_ids": [],
            "retry_count": 0,
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "duration_ms": 30,
        }


class FakeReadOnlyAgents:
    """模拟只读问答和规划结果。"""

    def create_plan(self, task, feedback=None) -> TaskPlan:
        return TaskPlan(
            version=len(task.plans) + 1,
            problem_summary=feedback or "定位并修复加法错误。",
            likely_root_cause="运算符使用错误。",
            relevant_files=["calculator.py"],
            implementation_steps=["将减法运算改为加法运算。"],
            validation_steps=["运行 pytest -q。"],
        )

    def converse(self, task, content) -> ConversationReply:
        del task
        if "修复" in content:
            return ConversationReply(
                intent="modify",
                response="我会先更新计划。",
                explicit_action=True,
            )
        return ConversationReply(intent="explain", response="问题来自错误的运算符。")


def initialize_repository(repository: Path) -> None:
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "--allow-empty", "-m", "init", "-q"],
        check=True,
    )


def test_run_service_executes_in_background_and_exposes_artifacts(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    initialize_repository(repository)
    artifact_store = LocalArtifactStore(tmp_path / "outputs")
    invoked = Event()
    task_service = TaskService()
    task = task_service.create(
        TaskCreate(
            repository_path=repository,
            issue_title="修复加法",
            issue_body="add 应返回两数之和。",
        )
    )
    task.plans.append(
        TaskPlan(
            status="approved",
            problem_summary="修复加法错误。",
            likely_root_cause="运算符错误。",
            implementation_steps=["修改运算符。"],
        )
    )
    task_service.store.save(task)
    run_service = RunService(
        task_service,
        workflow_service_factory=lambda: FakeRepairWorkflow(artifact_store, invoked),
        artifact_store=artifact_store,
    )

    created = run_service.create(task.id)

    assert invoked.wait(timeout=2)
    deadline = time.monotonic() + 2
    while run_service.get(created.id).status is not TaskRunStatus.SUCCEEDED:
        assert time.monotonic() < deadline
        time.sleep(0.01)

    completed = run_service.get(created.id)
    artifacts = run_service.artifacts(created.id)
    events = run_service.events(created.id)
    assert completed.changed_files == ["calculator.py"]
    assert completed.tests_passed is True
    assert artifacts.baseline_test is not None
    assert artifacts.verification_tests[0]["exit_code"] == 0
    assert artifacts.patch == "+return left + right\n"
    assert [event.node_name for event in events if event.node_name] == [
        "prepare_workspace",
        "run_tests",
    ]


def test_task_service_manages_conversation_plan_and_archive(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    initialize_repository(repository)
    service = TaskService(read_only_agents=FakeReadOnlyAgents())
    task = service.create(
        TaskCreate(
            repository_path=repository,
            issue_title="修复加法",
            issue_body="add 应返回两数之和。",
        )
    )

    planned = service.create_plan(task.id, PlanCreate())
    assert planned.plans[0].status == "draft"
    approved = service.approve_plan(task.id, planned.plans[0].id)
    assert approved.plans[0].status == "approved"

    explained = service.add_message(task.id, TaskMessageCreate(content="为什么会出错？"))
    assert explained.messages[-1].intent == "explain"
    assert len(explained.plans) == 1

    revised = service.add_message(task.id, TaskMessageCreate(content="请继续修复负数场景"))
    assert revised.plans[-1].version == 2
    assert "补充要求" in revised.issue_body

    renamed = service.update_title(task.id, TaskTitleUpdate(title="新的会话名称"))
    assert renamed.title_locked is True
    assert renamed.issue_title == "新的会话名称"
    assert service.archive(task.id).archived_at is not None
    assert service.list() == []
    assert len(service.list(archived=True)) == 1
    assert service.restore(task.id).archived_at is None


def test_initial_message_is_classified_before_planning(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    initialize_repository(repository)
    service = TaskService(read_only_agents=FakeReadOnlyAgents())
    task = service.create(
        TaskCreate(
            repository_path=repository,
            issue_title="了解代码",
            issue_body="为什么这个函数会返回错误结果？",
        )
    )

    replied = service.respond(task.id)

    assert replied.messages[0].intent == "explain"
    assert replied.messages[-1].content == "问题来自错误的运算符。"
    assert replied.plans == []
    assert replied.planning_status == "idle"


def test_failed_response_is_persisted_and_can_be_retried(tmp_path: Path) -> None:
    class FailingAgents(FakeReadOnlyAgents):
        def converse(self, task, content):
            del task, content
            raise AgentExecutionError("Agent 工具调用次数已达到上限")

    repository = tmp_path / "repository"
    initialize_repository(repository)
    service = TaskService(read_only_agents=FailingAgents())
    task = service.create(
        TaskCreate(
            repository_path=repository,
            issue_title="分析失败",
            issue_body="为什么会失败？",
        )
    )

    with pytest.raises(ConversationExecutionError, match="工具调用次数"):
        service.respond(task.id)

    failed = service.get(task.id)
    assert failed.planning_status == "failed"
    assert failed.planning_error == "Agent 工具调用次数已达到上限"
    assert len(failed.messages) == 1


def test_run_uses_approved_plan_snapshot(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    initialize_repository(repository)
    invoked = Event()
    received = []

    class CapturingWorkflow:
        def execute(self, *, run_id, task, progress_callback=None):
            del run_id, progress_callback
            received.append(task)
            invoked.set()
            return {"status": "succeeded", "iteration": 0}

    task_service = TaskService(read_only_agents=FakeReadOnlyAgents())
    task = task_service.create(
        TaskCreate(
            repository_path=repository,
            issue_title="修复加法",
            issue_body="请修复加法。",
        )
    )
    planned = task_service.create_plan(task.id, PlanCreate())
    task_service.approve_plan(task.id, planned.plans[-1].id)
    run_service = RunService(task_service, workflow_service_factory=CapturingWorkflow)

    run = run_service.create(task.id)

    assert invoked.wait(timeout=2)
    assert received[0].confirmed_plan is not None
    assert received[0].confirmed_plan.id == planned.plans[-1].id
    assert run.execution_task is not None
    assert run.execution_task.messages == []


def test_run_rejects_repository_commit_changed_after_planning(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    initialize_repository(repository)
    task_service = TaskService(read_only_agents=FakeReadOnlyAgents())
    task = task_service.create(
        TaskCreate(
            repository_path=repository,
            issue_title="修复加法",
            issue_body="请修复加法。",
        )
    )
    planned = task_service.create_plan(task.id, PlanCreate())
    planned.plans[-1].base_commit = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
    ).strip()
    task_service.store.save(planned)
    task_service.approve_plan(task.id, planned.plans[-1].id)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "--allow-empty", "-m", "next", "-q"],
        check=True,
    )

    with pytest.raises(PlanApprovalRequiredError, match="仓库提交已变化"):
        RunService(task_service).create(task.id)
