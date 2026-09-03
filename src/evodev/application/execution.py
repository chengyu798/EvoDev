"""编排不依赖智能体的确定性代码修复执行流程。"""

from dataclasses import dataclass
from pathlib import Path

from evodev.runtime.testing import PytestRunner, TestExecutionResult
from evodev.runtime.workspace import Workspace, WorkspaceManager
from evodev.tools.edit import EditTools
from evodev.tools.git import GitTools


@dataclass(frozen=True, slots=True)
class DeterministicRepairResult:
    """确定性修复流程产生的工作区、测试和补丁证据。"""

    workspace: Workspace
    baseline: TestExecutionResult
    verification: TestExecutionResult
    changed_files: list[str]
    patch: str


class DeterministicRepairService:
    """依次准备仓库、运行测试、应用补丁并收集结果。"""

    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        pytest_runner: PytestRunner,
        edit_tools: EditTools,
        git_tools: GitTools,
    ) -> None:
        self.workspace_manager = workspace_manager
        self.pytest_runner = pytest_runner
        self.edit_tools = edit_tools
        self.git_tools = git_tools

    def execute(
        self,
        *,
        run_id: str,
        source_repository: Path,
        patch: str,
        test_command: str = "pytest -q",
        revision: str = "HEAD",
    ) -> DeterministicRepairResult:
        """执行一次完整修复，并保留工作区供后续复查。"""
        workspace = self.workspace_manager.prepare_repository(
            run_id,
            source_repository,
            revision,
        )
        baseline = self.pytest_runner.run(
            workspace.path,
            test_command,
            kind="baseline",
        )
        self.edit_tools.apply_patch(workspace.path, patch)
        verification = self.pytest_runner.run(
            workspace.path,
            test_command,
            kind="verification",
        )
        return DeterministicRepairResult(
            workspace=workspace,
            baseline=baseline,
            verification=verification,
            changed_files=self.git_tools.changed_files(workspace.path),
            patch=self.git_tools.create_patch(workspace.path),
        )
