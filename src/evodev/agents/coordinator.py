"""为工作流提供四类智能体的统一调用入口。"""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from evodev.agents.executor import AgentExecutor, AgentInvocation
from evodev.agents.schemas import (
    ConversationReply,
    FailureAnalysis,
    ImplementationResult,
    IssueAnalysis,
    ReviewResult,
)
from evodev.domain.agents import AgentDefinition


class RepairAgentsProtocol(Protocol):
    def analyze(self, *, workspace: Path, task: dict[str, object]) -> AgentInvocation: ...

    def implement(self, *, workspace: Path, task: dict[str, object]) -> AgentInvocation: ...

    def diagnose(self, *, workspace: Path, task: dict[str, object]) -> AgentInvocation: ...

    def review(self, *, workspace: Path, task: dict[str, object]) -> AgentInvocation: ...

    def converse(
        self,
        *,
        workspace: Path,
        task: dict[str, object],
        on_delta: Callable[[str], None] | None = None,
    ) -> AgentInvocation: ...


class RepairAgentCoordinator:
    """根据角色配置调用对应智能体。"""

    def __init__(
        self,
        executor: AgentExecutor,
        catalog: dict[str, AgentDefinition],
    ) -> None:
        self.executor = executor
        self.catalog = catalog

    def analyze(self, *, workspace: Path, task: dict[str, object]) -> AgentInvocation:
        return self._invoke("analyst", workspace, task, IssueAnalysis)

    def converse(
        self,
        *,
        workspace: Path,
        task: dict[str, object],
        on_delta: Callable[[str], None] | None = None,
    ) -> AgentInvocation:
        return self._invoke(
            "conversation",
            workspace,
            task,
            ConversationReply,
            output_delta_callback=on_delta,
        )

    def implement(self, *, workspace: Path, task: dict[str, object]) -> AgentInvocation:
        return self._invoke("developer", workspace, task, ImplementationResult)

    def diagnose(self, *, workspace: Path, task: dict[str, object]) -> AgentInvocation:
        return self._invoke("failure_analyzer", workspace, task, FailureAnalysis)

    def review(self, *, workspace: Path, task: dict[str, object]) -> AgentInvocation:
        return self._invoke("reviewer", workspace, task, ReviewResult)

    def _invoke(
        self,
        role: str,
        workspace: Path,
        task: dict[str, object],
        output_schema: type[
            IssueAnalysis
            | ImplementationResult
            | FailureAnalysis
            | ReviewResult
            | ConversationReply
        ],
        output_delta_callback: Callable[[str], None] | None = None,
    ) -> AgentInvocation:
        return self.executor.invoke(
            agent=self.catalog[role],
            workspace=workspace,
            task=task,
            output_schema=output_schema,
            output_delta_callback=output_delta_callback,
        )
