"""验证多智能体修复闭环和检查点。"""

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver

from evodev.agents.executor import AgentInvocation
from evodev.agents.schemas import (
    FailureAnalysis,
    ImplementationResult,
    IssueAnalysis,
    ReviewResult,
)
from evodev.application.repair import RepairWorkflowService
from evodev.domain.enums import TaskRunStatus
from evodev.domain.tasks import TaskRead
from evodev.persistence.artifacts import LocalArtifactStore
from evodev.runtime.command import CommandResult
from evodev.runtime.testing import TestExecutionResult as PytestExecutionResult
from evodev.runtime.workspace import WorkspaceManager
from evodev.tools.edit import EditTools
from evodev.tools.git import GitTools
from evodev.workflows.nodes.core import RepairWorkflowNodes, WorkflowNodeDependencies


class ScriptedTestRunner:
    """返回预设测试结果，避免单元测试依赖 Docker。"""

    def __init__(self, verification_results: list[bool]) -> None:
        self.verification_results = verification_results

    def run(
        self,
        workspace: Path,
        test_command: str,
        *,
        kind: str,
    ) -> PytestExecutionResult:
        del workspace, test_command
        passed = False if kind == "baseline" else self.verification_results.pop(0)
        result = CommandResult(
            command=["pytest", "-q"],
            exit_code=0 if passed else 1,
            stdout="测试通过" if passed else "断言失败",
            stderr="",
            duration_ms=10,
        )
        return PytestExecutionResult(**result.model_dump(), kind=kind, passed=passed)


class MemoryCheckpointStore:
    """使用 LangGraph 内存实现验证工作流，不依赖外部数据库。"""

    def __init__(self) -> None:
        self.saver = InMemorySaver()

    @contextmanager
    def open(self) -> Iterator[InMemorySaver]:
        yield self.saver

    def delete_thread(self, thread_id: str) -> bool:
        config = {"configurable": {"thread_id": thread_id}}
        existed = next(self.saver.list(config, limit=1), None) is not None
        self.saver.delete_thread(thread_id)
        return existed

    def count(self, thread_id: str) -> int:
        config = {"configurable": {"thread_id": thread_id}}
        return sum(1 for _ in self.saver.list(config))


class ScriptedRepairAgents:
    """模拟四类 Agent，并在每轮产生可观察的代码变更。"""

    def __init__(self, *, review_passed: bool = True) -> None:
        self.review_passed = review_passed
        self.implement_count = 0
        self.diagnose_count = 0

    def analyze(self, *, workspace: Path, task: dict[str, object]) -> AgentInvocation:
        del workspace, task
        return self._invocation(
            IssueAnalysis(
                problem_summary="加法实现错误",
                likely_root_cause="运算符错误",
                relevant_files=["calculator.py"],
                implementation_steps=["修正运算符"],
            )
        )

    def implement(self, *, workspace: Path, task: dict[str, object]) -> AgentInvocation:
        del task
        self.implement_count += 1
        target = workspace / "calculator.py"
        target.write_text(
            f"def add(left, right):\n    return left + right  # 第 {self.implement_count} 轮\n",
            encoding="utf-8",
        )
        return self._invocation(
            ImplementationResult(
                summary=f"完成第 {self.implement_count} 轮修改",
                changed_files=["calculator.py"],
            )
        )

    def diagnose(self, *, workspace: Path, task: dict[str, object]) -> AgentInvocation:
        del workspace, task
        self.diagnose_count += 1
        return self._invocation(
            FailureAnalysis(
                failure_summary="仍有测试失败",
                root_cause="首次修改不完整",
                suggested_changes=["继续修正实现"],
            )
        )

    def review(self, *, workspace: Path, task: dict[str, object]) -> AgentInvocation:
        del workspace, task
        return self._invocation(
            ReviewResult(
                passed=self.review_passed,
                summary="补丁满足需求" if self.review_passed else "补丁仍需修改",
                requirement_coverage=["加法行为已修复"],
            )
        )

    @staticmethod
    def _invocation(output: object) -> AgentInvocation:
        return AgentInvocation(  # type: ignore[arg-type]
            output=output,
            tool_calls=[],
            prompt_tokens=2,
            completion_tokens=3,
        )


def create_source_repository(root: Path) -> Path:
    repository = root / "source"
    repository.mkdir()
    (repository / "calculator.py").write_text(
        "def add(left, right):\n    return left - right\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "add", "calculator.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=EvoDev Test",
            "-c",
            "user.email=test@evodev.local",
            "commit",
            "--quiet",
            "-m",
            "初始化",
        ],
        check=True,
    )
    return repository


def build_service(
    tmp_path: Path,
    test_runner: ScriptedTestRunner,
    agents: ScriptedRepairAgents,
) -> tuple[RepairWorkflowService, MemoryCheckpointStore]:
    checkpoint_store = MemoryCheckpointStore()
    dependencies = WorkflowNodeDependencies(
        workspace_manager=WorkspaceManager(tmp_path / "workspaces"),
        pytest_runner=test_runner,  # type: ignore[arg-type]
        edit_tools=EditTools(),
        git_tools=GitTools(),
        artifact_store=LocalArtifactStore(tmp_path / "outputs"),
        agents=agents,
    )
    service = RepairWorkflowService(
        RepairWorkflowNodes(dependencies),
        checkpoint_store,
    )
    return service, checkpoint_store


def test_repair_workflow_retries_then_saves_patch_and_checkpoint(tmp_path: Path) -> None:
    repository = create_source_repository(tmp_path)
    agents = ScriptedRepairAgents()
    service, checkpoint_store = build_service(
        tmp_path,
        ScriptedTestRunner([False, True]),
        agents,
    )
    run_id = uuid4().hex
    task = TaskRead(
        repository_path=repository,
        issue_title="修复加法函数",
        issue_body="add 应返回两数之和。",
        test_command="pytest -q",
        constraints=[],
        max_iterations=3,
    )

    result = service.execute(run_id=run_id, task=task)

    assert result["status"] == TaskRunStatus.SUCCEEDED
    assert result["iteration"] == 2
    assert result["tests_passed"] is True
    assert result["review_passed"] is True
    assert result["changed_files"] == ["calculator.py"]
    assert result["prompt_tokens"] == 10
    assert result["completion_tokens"] == 15
    assert len(result["agent_invocation_ids"]) == 5
    patch_path = tmp_path / "outputs" / run_id / result["patch_artifact_id"]
    assert "return left + right" in patch_path.read_text(encoding="utf-8")
    assert agents.implement_count == 2
    assert agents.diagnose_count == 1

    assert checkpoint_store.count(run_id) > 0


def test_repair_workflow_stops_after_three_failed_attempts(tmp_path: Path) -> None:
    repository = create_source_repository(tmp_path)
    agents = ScriptedRepairAgents()
    service, _ = build_service(
        tmp_path,
        ScriptedTestRunner([False, False, False]),
        agents,
    )
    task = TaskRead(
        repository_path=repository,
        issue_title="修复加法函数",
        issue_body="add 应返回两数之和。",
        test_command="pytest -q",
        constraints=[],
        max_iterations=3,
    )

    result = service.execute(run_id=uuid4().hex, task=task)

    assert result["status"] == TaskRunStatus.FAILED
    assert result["iteration"] == 3
    assert result["error_code"] == "REPAIR_LIMIT_REACHED"
    assert agents.implement_count == 3
    assert agents.diagnose_count == 2
