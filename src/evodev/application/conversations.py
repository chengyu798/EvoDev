"""组装只读对话与规划智能体。"""

from pathlib import Path
from typing import cast
from uuid import uuid4

from evodev.agents.catalog import default_agent_catalog
from evodev.agents.client import LiteLLMClient
from evodev.agents.coordinator import RepairAgentCoordinator
from evodev.agents.executor import AgentExecutor
from evodev.agents.prompting import PromptRepository
from evodev.agents.schemas import ConversationReply, IssueAnalysis
from evodev.agents.tools import AgentToolbox
from evodev.config import Settings
from evodev.domain.tasks import TaskPlan, TaskRead
from evodev.runtime.sandbox import DockerCommandRunner, DockerSandboxConfig
from evodev.runtime.workspace import WorkspaceManager
from evodev.tools.edit import EditTools
from evodev.tools.git import GitTools
from evodev.tools.repository import RepositoryTools


class ReadOnlyAgentService:
    """在不修改仓库的前提下完成问答和计划生成。"""

    def __init__(
        self,
        agents: RepairAgentCoordinator,
        workspace_manager: WorkspaceManager | None = None,
    ) -> None:
        self.agents = agents
        self.workspace_manager = workspace_manager

    def create_plan(self, task: TaskRead, feedback: str | None = None) -> TaskPlan:
        context = self._task_context(task)
        if feedback:
            context["plan_feedback"] = feedback
        workspace = Path(task.repository_path)
        base_commit = GitTools().base_commit(workspace)
        planning_workspace_id: str | None = None
        if self.workspace_manager is not None:
            planning_workspace_id = f"plan-{uuid4().hex}"
            prepared = self.workspace_manager.prepare_repository(
                planning_workspace_id,
                Path(task.repository_path),
            )
            workspace = prepared.path
            base_commit = prepared.base_commit
        try:
            invocation = self.agents.analyze(workspace=workspace, task=context)
        finally:
            if planning_workspace_id and self.workspace_manager is not None:
                self.workspace_manager.remove(planning_workspace_id)
        analysis = cast(IssueAnalysis, invocation.output)
        return TaskPlan(
            version=len(task.plans) + 1,
            problem_summary=analysis.problem_summary,
            likely_root_cause=analysis.likely_root_cause,
            relevant_files=analysis.relevant_files,
            implementation_steps=analysis.implementation_steps,
            validation_steps=[f"运行 `{task.test_command}` 验证修改结果"],
            risks=analysis.risks,
            base_commit=base_commit,
        )

    def converse(self, task: TaskRead, content: str) -> ConversationReply:
        context = self._task_context(task)
        context["latest_user_message"] = content
        invocation = self.agents.converse(
            workspace=Path(task.repository_path),
            task=context,
        )
        return cast(ConversationReply, invocation.output)

    @staticmethod
    def _task_context(task: TaskRead) -> dict[str, object]:
        return {
            "repository_path": str(task.repository_path),
            "issue_title": task.issue_title,
            "issue_body": task.issue_body,
            "test_command": task.test_command,
            "constraints": task.constraints,
            "run_evidence": task.run_evidence,
            "evidence_note": (
                "修复发生在隔离工作区，原仓库没有变化不等于没有完成修复。"
                "回答历史修改和测试问题时以 run_evidence 为准；没有证据时明确说明。"
            ),
            "conversation": [
                {
                    "role": message.role,
                    "content": message.content,
                    "intent": message.intent,
                }
                for message in task.messages[-20:]
            ],
            "plans": [
                {
                    "version": plan.version,
                    "status": plan.status,
                    "problem_summary": plan.problem_summary,
                    "implementation_steps": plan.implementation_steps,
                    "risks": plan.risks,
                }
                for plan in task.plans[-3:]
            ],
        }


def build_read_only_agent_service(settings: Settings) -> ReadOnlyAgentService:
    """使用与修复工作流相同的模型配置创建只读智能体。"""
    if not settings.llm_model:
        raise RuntimeError("请先配置 EVODEV_LLM_MODEL")
    runner = DockerCommandRunner(
        DockerSandboxConfig(
            image=settings.sandbox_image,
            network=settings.sandbox_network,
            cpus=settings.sandbox_cpus,
            memory=settings.sandbox_memory,
            pids_limit=settings.sandbox_pids_limit,
            timeout_seconds=settings.command_timeout_seconds,
            max_output_bytes=settings.max_command_output_bytes,
        )
    )
    toolbox = AgentToolbox(RepositoryTools(), EditTools(), GitTools(), runner)
    catalog = default_agent_catalog(settings.llm_model)
    catalog["analyst"].allowed_tools.append("run_command")
    executor = AgentExecutor(
        LiteLLMClient(api_key=settings.llm_api_key, base_url=settings.llm_base_url),
        toolbox,
        PromptRepository(),
    )
    return ReadOnlyAgentService(
        RepairAgentCoordinator(executor, catalog),
        WorkspaceManager(settings.workspaces_dir),
    )
