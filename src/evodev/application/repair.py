"""组装并执行带 PostgreSQL 检查点的多智能体修复工作流。"""

import time
from pathlib import Path
from typing import cast

from evodev.agents.catalog import default_agent_catalog
from evodev.agents.client import LiteLLMClient
from evodev.agents.coordinator import RepairAgentCoordinator
from evodev.agents.executor import AgentExecutor
from evodev.agents.prompting import PromptRepository
from evodev.agents.tools import AgentToolbox
from evodev.config import Settings
from evodev.domain.enums import TaskRunStatus
from evodev.domain.tasks import TaskRead
from evodev.persistence.artifacts import LocalArtifactStore
from evodev.persistence.checkpoints import (
    CheckpointStoreProtocol,
    PostgresCheckpointStore,
)
from evodev.persistence.evolution import PostgresPromptEvolutionStore
from evodev.persistence.experiences import ExperienceStoreProtocol, PostgresExperienceStore
from evodev.runtime.sandbox import DockerCommandRunner, DockerSandboxConfig
from evodev.runtime.testing import PytestRunner
from evodev.runtime.workspace import WorkspaceManager
from evodev.tools.edit import EditTools
from evodev.tools.git import GitTools
from evodev.tools.repository import RepositoryTools
from evodev.workflows.compiler import build_bug_fix_graph
from evodev.workflows.nodes.core import RepairWorkflowNodes, WorkflowNodeDependencies
from evodev.workflows.specs import BUG_FIX_V1
from evodev.workflows.state import EvoDevState


class MissingModelConfigurationError(RuntimeError):
    """运行多智能体工作流前尚未配置模型。"""


class RepairWorkflowService:
    """为一个任务创建初始状态并同步执行完整工作流。"""

    def __init__(
        self,
        nodes: RepairWorkflowNodes,
        checkpoint_store: CheckpointStoreProtocol,
        prompt_evolution_store: PostgresPromptEvolutionStore | None = None,
        prompt_evolution_min_experiences: int = 3,
    ) -> None:
        self.nodes = nodes
        self.checkpoint_store = checkpoint_store
        self.prompt_evolution_store = prompt_evolution_store
        self.prompt_evolution_min_experiences = prompt_evolution_min_experiences

    def execute(self, *, run_id: str, task: TaskRead) -> EvoDevState:
        started_at = time.perf_counter()
        initial_state: EvoDevState = {
            "run_id": run_id,
            "task_id": str(task.id),
            "status": TaskRunStatus.CREATED.value,
            "repository_path": str(task.repository_path),
            "issue_title": task.issue_title,
            "issue_body": task.issue_body,
            "test_command": task.test_command,
            "constraints": task.constraints,
            "max_iterations": task.max_iterations,
            "changed_files": [],
            "retrieved_experience_ids": [],
            "agent_invocation_ids": [],
            "iteration": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "agent_versions": {},
            "workflow_version": BUG_FIX_V1.version_id,
        }
        config = {"configurable": {"thread_id": run_id}}
        with self.checkpoint_store.open() as checkpointer:
            graph = build_bug_fix_graph(
                checkpointer=checkpointer,
                node_registry=self.nodes.registry(),
            )
            try:
                result = graph.invoke(initial_state, config=config)
            except Exception as exc:
                # 将基础设施或模型异常转为可查询的失败状态。
                graph.update_state(
                    config,
                    {
                        "status": TaskRunStatus.FAILED.value,
                        "error_code": "WORKFLOW_EXECUTION_FAILED",
                        "error_message": str(exc),
                    },
                )
                result = graph.get_state(config).values
            feedback_update = self.nodes.finalize_experience_feedback(
                cast(EvoDevState, result)
            )
            graph.update_state(config, feedback_update)
            result = graph.get_state(config).values
            if (
                feedback_update["experience_feedback_count"]
                and feedback_update["experience_feedback"] != "ignored"
                and self.prompt_evolution_store is not None
            ):
                job = self.prompt_evolution_store.enqueue_if_absent(
                    agent_role="developer",
                    min_experiences=self.prompt_evolution_min_experiences,
                )
                if job is not None:
                    graph.update_state(
                        config,
                        {"prompt_evolution_job_id": str(job.id)},
                    )
                    result = graph.get_state(config).values
            metrics_update = self.nodes.record_run_metrics(
                cast(EvoDevState, result),
                duration_ms=int((time.perf_counter() - started_at) * 1000),
                workflow_version=BUG_FIX_V1.version_id,
            )
            graph.update_state(config, metrics_update)
            result = graph.get_state(config).values
        return cast(EvoDevState, result)


def build_repair_workflow_service(
    settings: Settings,
    *,
    prompt_repository: PromptRepository | None = None,
    experience_store: ExperienceStoreProtocol | None = None,
) -> RepairWorkflowService:
    """根据应用配置创建生产环境依赖。"""
    if not settings.llm_model:
        raise MissingModelConfigurationError("请先配置 EVODEV_LLM_MODEL")

    workspace_manager = WorkspaceManager(settings.workspaces_dir)
    sandbox_runner = DockerCommandRunner(
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
    repository_tools = RepositoryTools()
    edit_tools = EditTools()
    git_tools = GitTools()
    toolbox = AgentToolbox(repository_tools, edit_tools, git_tools, sandbox_runner)
    client = LiteLLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )
    agents = RepairAgentCoordinator(
        AgentExecutor(
            client,
            toolbox,
            prompt_repository
            or PromptRepository(
                guidance_provider=PostgresPromptEvolutionStore(settings.database_url)
            ),
        ),
        default_agent_catalog(settings.llm_model),
    )
    dependencies = WorkflowNodeDependencies(
        workspace_manager=workspace_manager,
        pytest_runner=PytestRunner(sandbox_runner),
        edit_tools=edit_tools,
        git_tools=git_tools,
        artifact_store=LocalArtifactStore(Path(settings.outputs_dir)),
        experience_store=experience_store or PostgresExperienceStore(settings.database_url),
        agents=agents,
    )
    return RepairWorkflowService(
        RepairWorkflowNodes(dependencies),
        PostgresCheckpointStore(settings.database_url),
        PostgresPromptEvolutionStore(settings.database_url)
        if settings.prompt_evolution_auto_enqueue
        else None,
        settings.prompt_evolution_min_experiences,
    )
