"""验证多智能体修复闭环和检查点。"""

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
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
from evodev.domain.evolution import PromptEvolutionJob
from evodev.domain.experiences import (
    Experience,
    ExperienceMatch,
    ExperienceOutcome,
    ExperienceStatus,
)
from evodev.domain.tasks import TaskRead
from evodev.evaluation.retrieval import rank_experience_matches
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


class MemoryExperienceStore:
    """在内存中模拟经验存储、检索和幂等用量统计。"""

    def __init__(self, experiences: list[Experience] | None = None) -> None:
        self.experiences = {item.id: item for item in experiences or []}
        self.usages: set[tuple[UUID, UUID]] = set()

    def save(self, experience: Experience) -> Experience:
        existing = next(
            (
                item
                for item in self.experiences.values()
                if item.source_run_id == experience.source_run_id
            ),
            None,
        )
        if existing is not None:
            return existing
        self.experiences[experience.id] = experience
        return experience

    def search(
        self,
        *,
        task_type: str,
        tags: list[str],
        limit: int = 3,
    ) -> list[ExperienceMatch]:
        candidates = [
            item
            for item in self.experiences.values()
            if item.task_type == task_type and item.status is ExperienceStatus.ACTIVE
        ]
        return rank_experience_matches(candidates, tags, limit=limit)

    def get_many(self, experience_ids: list[UUID]) -> list[Experience]:
        return [self.experiences[item] for item in experience_ids]

    def record_usage(self, experience_ids: list[UUID], run_id: UUID) -> int:
        recorded = 0
        for experience_id in experience_ids:
            usage = (experience_id, run_id)
            if usage in self.usages:
                continue
            self.usages.add(usage)
            self.experiences[experience_id].usage_count += 1
            recorded += 1
        return recorded

    def finalize_run_usage(self, run_id: UUID, outcome: ExperienceOutcome) -> int:
        matched = [item for item in self.usages if item[1] == run_id]
        if outcome in {ExperienceOutcome.SUCCESS, ExperienceOutcome.FAILURE}:
            for experience_id, _ in matched:
                experience = self.experiences[experience_id]
                if outcome is ExperienceOutcome.SUCCESS:
                    experience.success_count += 1
                else:
                    experience.failure_count += 1
                experience.quality_score = (experience.success_count + 1) / (
                    experience.success_count + experience.failure_count + 2
                )
                if (
                    experience.success_count + experience.failure_count >= 3
                    and experience.quality_score < 0.35
                ):
                    experience.status = ExperienceStatus.DISABLED
        return len(matched)

    def list_for_evolution(self, *, limit: int = 5) -> list[Experience]:
        active = [
            item for item in self.experiences.values() if item.status is ExperienceStatus.ACTIVE
        ]
        return sorted(active, key=lambda item: item.quality_score, reverse=True)[:limit]


class ScriptedRepairAgents:
    """模拟四类 Agent，并在每轮产生可观察的代码变更。"""

    def __init__(self, *, review_passed: bool = True) -> None:
        self.review_passed = review_passed
        self.implement_count = 0
        self.diagnose_count = 0
        self.analyze_tasks: list[dict[str, object]] = []
        self.implement_tasks: list[dict[str, object]] = []

    def analyze(self, *, workspace: Path, task: dict[str, object]) -> AgentInvocation:
        del workspace
        self.analyze_tasks.append(task)
        return self._invocation(
            IssueAnalysis(
                problem_summary="加法实现错误",
                likely_root_cause="运算符错误",
                relevant_files=["calculator.py"],
                implementation_steps=["修正运算符"],
            )
        )

    def implement(self, *, workspace: Path, task: dict[str, object]) -> AgentInvocation:
        self.implement_tasks.append(task)
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
            duration_ms=4,
            agent_id=type(output).__name__,
            model="test-model",
            prompt_version="test-prompt",
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
    experience_store: MemoryExperienceStore | None = None,
    prompt_evolution_store: object | None = None,
) -> tuple[RepairWorkflowService, MemoryCheckpointStore, MemoryExperienceStore]:
    checkpoint_store = MemoryCheckpointStore()
    memory_experience_store = experience_store or MemoryExperienceStore()
    dependencies = WorkflowNodeDependencies(
        workspace_manager=WorkspaceManager(tmp_path / "workspaces"),
        pytest_runner=test_runner,  # type: ignore[arg-type]
        edit_tools=EditTools(),
        git_tools=GitTools(),
        artifact_store=LocalArtifactStore(tmp_path / "outputs"),
        experience_store=memory_experience_store,
        agents=agents,
    )
    service = RepairWorkflowService(
        RepairWorkflowNodes(dependencies),
        checkpoint_store,
        prompt_evolution_store,  # type: ignore[arg-type]
        1,
    )
    return service, checkpoint_store, memory_experience_store


def test_repair_workflow_retries_then_saves_patch_and_checkpoint(tmp_path: Path) -> None:
    repository = create_source_repository(tmp_path)
    agents = ScriptedRepairAgents()
    service, checkpoint_store, _ = build_service(
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

    completed_nodes: list[str] = []
    result = service.execute(
        run_id=run_id,
        task=task,
        progress_callback=lambda node, _: completed_nodes.append(node),
    )

    assert result["status"] == TaskRunStatus.SUCCEEDED
    assert result["iteration"] == 2
    assert result["tests_passed"] is True
    assert result["review_passed"] is True
    assert result["changed_files"] == ["calculator.py"]
    assert result["prompt_tokens"] == 10
    assert result["completion_tokens"] == 15
    assert result["retry_count"] == 1
    assert result["duration_ms"] >= 0
    assert result["workflow_version"] == "bug_fix@1"
    assert result["run_metrics_id"] == "run-metrics.json"
    metrics = LocalArtifactStore(tmp_path / "outputs").read_json(
        run_id,
        result["run_metrics_id"],
    )
    assert metrics["workflow_version"] == "bug_fix@1"
    assert metrics["agent_versions"]["IssueAnalysis"] == ("prompt=test-prompt;model=test-model")
    assert len(result["agent_invocation_ids"]) == 5
    patch_path = tmp_path / "outputs" / run_id / result["patch_artifact_id"]
    assert "return left + right" in patch_path.read_text(encoding="utf-8")
    assert agents.implement_count == 2
    assert agents.diagnose_count == 1
    assert completed_nodes[0] == "prepare_workspace"
    assert completed_nodes[-1] == "finalize_succeeded"

    assert checkpoint_store.count(run_id) > 0


def test_repair_workflow_stops_after_three_failed_attempts(tmp_path: Path) -> None:
    repository = create_source_repository(tmp_path)
    agents = ScriptedRepairAgents()
    service, _, experience_store = build_service(
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
    assert result["generated_experience_id"]
    assert agents.implement_count == 3
    assert agents.diagnose_count == 2
    experience = experience_store.experiences[UUID(result["generated_experience_id"])]
    assert experience.source_run_id == UUID(result["run_id"])
    assert experience.failure_pattern == "仍有测试失败"
    assert "task:bug_fix" in experience.tags
    experience_artifact = LocalArtifactStore(tmp_path / "outputs").read_json(
        result["run_id"],
        "experience.json",
    )
    assert experience_artifact["id"] == result["generated_experience_id"]


def test_repair_workflow_retrieves_and_injects_experience(tmp_path: Path) -> None:
    repository = create_source_repository(tmp_path)
    historical = Experience(
        source_run_id=uuid4(),
        tags=["task:bug_fix", "function:add"],
        failure_pattern="加法断言失败",
        lesson="先核对运算符",
        recommended_actions=["检查加减号"],
    )
    experience_store = MemoryExperienceStore([historical])
    agents = ScriptedRepairAgents()
    service, _, _ = build_service(
        tmp_path,
        ScriptedTestRunner([True]),
        agents,
        experience_store,
    )
    task = TaskRead(
        repository_path=repository,
        issue_title="修复 add 函数",
        issue_body="add 应返回两数之和。",
        test_command="pytest -q",
        constraints=[],
        max_iterations=3,
    )

    result = service.execute(run_id=uuid4().hex, task=task)

    assert result["retrieved_experience_ids"] == [str(historical.id)]
    assert historical.usage_count == 1
    assert historical.success_count == 1
    assert historical.quality_score == pytest.approx(2 / 3)
    assert result["experience_feedback"] == "success"
    assert agents.analyze_tasks[0]["historical_experiences"][0]["lesson"] == "先核对运算符"
    retrieval = agents.analyze_tasks[0]["historical_experiences"][0]["retrieval"]
    assert retrieval["matched_tags"] == ["function:add", "task:bug_fix"]
    assert retrieval["reasons"] == ["函数名匹配：add", "任务类型匹配：bug_fix"]
    retrieval_artifact = LocalArtifactStore(tmp_path / "outputs").read_json(
        result["run_id"],
        result["experience_retrieval_id"],
    )
    assert retrieval_artifact["minimum_match_score"] == 2.5
    assert retrieval_artifact["matches"][0]["experience_id"] == str(historical.id)
    assert retrieval_artifact["matches"][0]["reasons"] == retrieval["reasons"]
    assert agents.implement_tasks[0]["historical_experiences"][0]["recommended_actions"] == [
        "检查加减号"
    ]


def test_repair_workflow_can_enqueue_evolution_after_feedback(tmp_path: Path) -> None:
    class PromptEvolutionStore:
        def enqueue_if_absent(
            self,
            *,
            agent_role: str,
            min_experiences: int,
        ) -> PromptEvolutionJob:
            assert agent_role == "developer"
            assert min_experiences == 1
            return PromptEvolutionJob(agent_role=agent_role)

    repository = create_source_repository(tmp_path)
    historical = Experience(
        source_run_id=uuid4(),
        tags=["task:bug_fix", "term:add"],
        failure_pattern="加法失败",
        lesson="核对运算符",
    )
    service, _, _ = build_service(
        tmp_path,
        ScriptedTestRunner([True]),
        ScriptedRepairAgents(),
        MemoryExperienceStore([historical]),
        PromptEvolutionStore(),
    )
    task = TaskRead(
        repository_path=repository,
        issue_title="修复 add",
        issue_body="add 应返回两数之和。",
        test_command="pytest -q",
        constraints=[],
        max_iterations=3,
    )

    result = service.execute(run_id=uuid4().hex, task=task)

    assert result["prompt_evolution_job_id"]
