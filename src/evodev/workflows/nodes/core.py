"""实现软件修复闭环中的确定性节点和智能体节点。"""

from dataclasses import dataclass
from pathlib import Path

import structlog

from evodev.agents.coordinator import RepairAgentsProtocol
from evodev.agents.executor import AgentInvocation
from evodev.agents.schemas import (
    FailureAnalysis,
    ImplementationResult,
    IssueAnalysis,
    ReviewResult,
)
from evodev.domain.enums import TaskRunStatus
from evodev.persistence.artifacts import LocalArtifactStore
from evodev.runtime.testing import PytestRunner
from evodev.runtime.workspace import WorkspaceManager
from evodev.tools.edit import EditTools
from evodev.tools.git import GitTools
from evodev.workflows.state import EvoDevState

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WorkflowNodeDependencies:
    """工作流节点需要的外部能力。"""

    workspace_manager: WorkspaceManager
    pytest_runner: PytestRunner
    edit_tools: EditTools
    git_tools: GitTools
    artifact_store: LocalArtifactStore
    agents: RepairAgentsProtocol


class RepairWorkflowNodes:
    """通过依赖注入执行真实仓库、测试和智能体操作。"""

    def __init__(self, dependencies: WorkflowNodeDependencies) -> None:
        self.dependencies = dependencies

    def registry(self) -> dict[str, object]:
        return {
            "prepare_workspace": self.prepare_workspace,
            "run_baseline_tests": self.run_baseline_tests,
            "analyze_issue": self.analyze_issue,
            "implement_patch": self.implement_patch,
            "run_tests": self.run_tests,
            "diagnose_failure": self.diagnose_failure,
            "review_patch": self.review_patch,
            "final_evaluation": self.final_evaluation,
            "finalize_succeeded": self.finalize_succeeded,
            "finalize_failed": self.finalize_failed,
        }

    def prepare_workspace(self, state: EvoDevState) -> dict[str, object]:
        logger.info("正在准备隔离工作区")
        workspace = self.dependencies.workspace_manager.prepare_repository(
            state["run_id"],
            Path(state["repository_path"]),
        )
        return {
            "status": TaskRunStatus.PREPARING.value,
            "workspace_path": str(workspace.path),
            "base_commit": workspace.base_commit,
        }

    def run_baseline_tests(self, state: EvoDevState) -> dict[str, object]:
        logger.info("正在运行修改前的基准测试")
        result = self.dependencies.pytest_runner.run(
            self._workspace(state),
            state["test_command"],
            kind="baseline",
        )
        artifact_id = self.dependencies.artifact_store.write_json(
            state["run_id"],
            "baseline-test.json",
            result.model_dump(),
        )
        logger.info("基准测试完成", 结果="通过" if result.passed else "未通过")
        return {
            "status": TaskRunStatus.BASELINE_TESTING.value,
            "baseline_result_id": artifact_id,
            "baseline_passed": result.passed,
        }

    def analyze_issue(self, state: EvoDevState) -> dict[str, object]:
        logger.info("问题分析智能体正在分析问题")
        invocation = self.dependencies.agents.analyze(
            workspace=self._workspace(state),
            task=self._base_task(state),
        )
        output = self._output(invocation, IssueAnalysis)
        return {
            "status": TaskRunStatus.ANALYZING.value,
            "issue_analysis": output.model_dump(),
            **self._invocation_update(state, "analyst-0.json", invocation),
        }

    def implement_patch(self, state: EvoDevState) -> dict[str, object]:
        iteration = state.get("iteration", 0) + 1
        logger.info(f"代码开发智能体正在进行第 {iteration} 轮修改")
        workspace = self._workspace(state)
        diff_before = self.dependencies.git_tools.diff(workspace)
        invocation = self.dependencies.agents.implement(
            workspace=workspace,
            task=self._base_task(state)
            | {
                "iteration": iteration,
                "issue_analysis": state.get("issue_analysis"),
                "failure_analysis": state.get("failure_analysis"),
                "review_result": state.get("review_result"),
                "current_diff": diff_before,
            },
        )
        output = self._output(invocation, ImplementationResult)
        diff_after_agent = self.dependencies.git_tools.diff(workspace)
        if output.patch and diff_after_agent == diff_before:
            self.dependencies.edit_tools.apply_patch(workspace, output.patch)
        changed_files = self.dependencies.git_tools.changed_files(workspace)
        if not changed_files:
            raise RuntimeError("Developer Agent 未产生任何代码修改")
        return {
            "status": TaskRunStatus.IMPLEMENTING.value,
            "iteration": iteration,
            "changed_files": changed_files,
            **self._invocation_update(state, f"developer-{iteration}.json", invocation),
        }

    def run_tests(self, state: EvoDevState) -> dict[str, object]:
        logger.info(f"正在验证第 {state['iteration']} 轮修改")
        result = self.dependencies.pytest_runner.run(
            self._workspace(state),
            state["test_command"],
            kind="verification",
        )
        artifact_id = self.dependencies.artifact_store.write_json(
            state["run_id"],
            f"test-{state['iteration']}.json",
            result.model_dump(),
        )
        logger.info("修改后测试完成", 结果="通过" if result.passed else "未通过")
        return {
            "status": TaskRunStatus.TESTING.value,
            "test_result_id": artifact_id,
            "tests_passed": result.passed,
        }

    def diagnose_failure(self, state: EvoDevState) -> dict[str, object]:
        logger.info("失败分析智能体正在诊断测试失败原因")
        test_result = self.dependencies.artifact_store.read_json(
            state["run_id"],
            self._required_artifact(state, "test_result_id"),
        )
        invocation = self.dependencies.agents.diagnose(
            workspace=self._workspace(state),
            task=self._base_task(state)
            | {
                "iteration": state["iteration"],
                "issue_analysis": state.get("issue_analysis"),
                "test_result": test_result,
            },
        )
        output = self._output(invocation, FailureAnalysis)
        update: dict[str, object] = {
            "status": TaskRunStatus.DEBUGGING.value,
            "failure_analysis": output.model_dump(),
            "failure_retryable": output.retryable,
            **self._invocation_update(
                state,
                f"failure-analyzer-{state['iteration']}.json",
                invocation,
            ),
        }
        if not output.retryable:
            update |= {
                "error_code": "NON_RETRYABLE_FAILURE",
                "error_message": output.failure_summary,
            }
        return update

    def review_patch(self, state: EvoDevState) -> dict[str, object]:
        logger.info("代码审查智能体正在审查代码修改")
        workspace = self._workspace(state)
        invocation = self.dependencies.agents.review(
            workspace=workspace,
            task=self._base_task(state)
            | {
                "iteration": state["iteration"],
                "issue_analysis": state.get("issue_analysis"),
                "changed_files": self.dependencies.git_tools.changed_files(workspace),
                "current_diff": self.dependencies.git_tools.diff(workspace),
                "tests_passed": state.get("tests_passed"),
            },
        )
        output = self._output(invocation, ReviewResult)
        return {
            "status": TaskRunStatus.REVIEWING.value,
            "review_result": output.model_dump(),
            "review_passed": output.passed,
            **self._invocation_update(
                state,
                f"reviewer-{state['iteration']}.json",
                invocation,
            ),
        }

    def final_evaluation(self, state: EvoDevState) -> dict[str, object]:
        logger.info("正在生成最终 Patch 和评测结果")
        workspace = self._workspace(state)
        patch = self.dependencies.git_tools.create_patch(workspace)
        patch_artifact_id = self.dependencies.artifact_store.write_text(
            state["run_id"],
            "result.patch",
            patch,
        )
        evaluation_result_id = self.dependencies.artifact_store.write_json(
            state["run_id"],
            "evaluation.json",
            {
                "tests_passed": state.get("tests_passed"),
                "review_passed": state.get("review_passed"),
                "changed_files": self.dependencies.git_tools.changed_files(workspace),
                "iteration": state["iteration"],
            },
        )
        return {
            "status": TaskRunStatus.FINALIZING.value,
            "patch_artifact_id": patch_artifact_id,
            "evaluation_result_id": evaluation_result_id,
        }

    @staticmethod
    def finalize_succeeded(_: EvoDevState) -> dict[str, object]:
        logger.info("多智能体修复流程已成功完成")
        return {"status": TaskRunStatus.SUCCEEDED.value}

    @staticmethod
    def finalize_failed(state: EvoDevState) -> dict[str, object]:
        logger.error("多智能体修复流程失败")
        return {
            "status": TaskRunStatus.FAILED.value,
            "error_code": state.get("error_code") or "REPAIR_LIMIT_REACHED",
            "error_message": state.get("error_message") or "自动修复次数已达到上限。",
        }

    @staticmethod
    def _workspace(state: EvoDevState) -> Path:
        path = state.get("workspace_path")
        if not path:
            raise RuntimeError("工作区尚未准备")
        return Path(path)

    @staticmethod
    def _base_task(state: EvoDevState) -> dict[str, object]:
        return {
            "issue_title": state["issue_title"],
            "issue_body": state["issue_body"],
            "test_command": state["test_command"],
        }

    @staticmethod
    def _output(invocation: AgentInvocation, schema: type[object]):
        if not isinstance(invocation.output, schema):
            raise TypeError(f"Agent 返回类型错误，期望 {schema.__name__}")
        return invocation.output

    def _invocation_update(
        self,
        state: EvoDevState,
        artifact_name: str,
        invocation: AgentInvocation,
    ) -> dict[str, object]:
        artifact_id = self.dependencies.artifact_store.write_json(
            state["run_id"],
            artifact_name,
            {
                "agent_id": invocation.agent_id,
                "model": invocation.model,
                "prompt_version": invocation.prompt_version,
                "output": invocation.output.model_dump(),
                "tool_calls": invocation.tool_calls,
                "prompt_tokens": invocation.prompt_tokens,
                "completion_tokens": invocation.completion_tokens,
            },
        )
        return {
            "agent_invocation_ids": [*state.get("agent_invocation_ids", []), artifact_id],
            "prompt_tokens": state.get("prompt_tokens", 0) + invocation.prompt_tokens,
            "completion_tokens": state.get("completion_tokens", 0)
            + invocation.completion_tokens,
        }

    @staticmethod
    def _required_artifact(state: EvoDevState, key: str) -> str:
        value = state.get(key)
        if not value:
            raise RuntimeError(f"工作流状态缺少产物引用：{key}")
        return value


def prepare_workspace(_: EvoDevState) -> dict[str, object]:
    return {"status": TaskRunStatus.PREPARING.value}


def run_baseline_tests(_: EvoDevState) -> dict[str, object]:
    return {"status": TaskRunStatus.BASELINE_TESTING.value}


def analyze_issue(_: EvoDevState) -> dict[str, object]:
    return {"status": TaskRunStatus.ANALYZING.value}


def implement_patch(state: EvoDevState) -> dict[str, object]:
    return {
        "status": TaskRunStatus.IMPLEMENTING.value,
        "iteration": state.get("iteration", 0) + 1,
    }


def run_tests(_: EvoDevState) -> dict[str, object]:
    return {"status": TaskRunStatus.TESTING.value}


def diagnose_failure(_: EvoDevState) -> dict[str, object]:
    return {"status": TaskRunStatus.DEBUGGING.value}


def review_patch(_: EvoDevState) -> dict[str, object]:
    return {"status": TaskRunStatus.REVIEWING.value}


def final_evaluation(_: EvoDevState) -> dict[str, object]:
    return {"status": TaskRunStatus.FINALIZING.value}


def finalize_succeeded(_: EvoDevState) -> dict[str, object]:
    return {"status": TaskRunStatus.SUCCEEDED.value}


def finalize_failed(state: EvoDevState) -> dict[str, object]:
    return {
        "status": TaskRunStatus.FAILED.value,
        "error_code": state.get("error_code") or "REPAIR_LIMIT_REACHED",
        "error_message": state.get("error_message")
        or "自动修复次数已达到上限。",
    }
