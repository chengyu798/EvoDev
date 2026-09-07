"""实现可持久化任务管理和后台修复运行。"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from pathlib import Path
from threading import RLock, Thread
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from evodev.agents.executor import AgentExecutionError
from evodev.agents.schemas import ConversationReply
from evodev.domain.enums import TaskRunStatus
from evodev.domain.runs import RunArtifactBundle, RunEvent, TaskRunRead
from evodev.domain.tasks import (
    PlanCreate,
    TaskCreate,
    TaskMessage,
    TaskMessageCreate,
    TaskPlan,
    TaskRead,
    TaskTitleUpdate,
    utc_now,
)
from evodev.persistence.artifacts import LocalArtifactStore
from evodev.persistence.tasks import (
    MemoryRunStore,
    MemoryTaskStore,
    RunStoreProtocol,
    TaskStoreProtocol,
)
from evodev.tools.git import GitTools


class TaskNotFoundError(LookupError):
    """请求的任务不存在。"""


class RunNotFoundError(LookupError):
    """请求的运行不存在。"""


class PlanNotFoundError(LookupError):
    """请求的计划版本不存在。"""


class PlanApprovalRequiredError(RuntimeError):
    """最新计划尚未得到用户确认。"""


class ActiveRunExistsError(RuntimeError):
    """同一会话已经存在正在执行的运行。"""


class ConversationExecutionError(RuntimeError):
    """问答或规划失败，消息和错误已保存，可重试。"""


def serialized_task(method):
    """单进程内按会话串行修改，防止并发请求覆盖消息和计划。"""

    @wraps(method)
    def wrapped(self, task_id, *args, **kwargs):
        with self._locks_guard:
            lock = self._task_locks.setdefault(task_id, RLock())
        with lock:
            return method(self, task_id, *args, **kwargs)

    return wrapped


def validate_runnable_task(task: TaskRead) -> None:
    """重新校验源仓库和任务参数，避免忽略创建任务后的仓库变化。"""
    TaskCreate(
        repository_path=task.repository_path,
        issue_title=task.issue_title,
        issue_body=task.issue_body,
        test_command=task.test_command,
        constraints=task.constraints,
        max_iterations=task.max_iterations,
        title_locked=task.title_locked,
    )


class RepairServiceProtocol(Protocol):
    """运行服务依赖的真实修复工作流接口。"""

    def execute(
        self,
        *,
        run_id: str,
        task: TaskRead,
        progress_callback: Callable[[str, dict[str, object]], None] | None = None,
    ) -> dict[str, object]: ...


class ReadOnlyAgentServiceProtocol(Protocol):
    """任务服务依赖的只读问答与规划能力。"""

    def create_plan(self, task: TaskRead, feedback: str | None = None) -> TaskPlan: ...

    def converse(
        self,
        task: TaskRead,
        content: str,
        on_delta: Callable[[str], None] | None = None,
    ) -> ConversationReply: ...


class TaskService:
    """管理一个仓库任务对应的会话、消息和计划。"""

    def __init__(
        self,
        store: TaskStoreProtocol | None = None,
        read_only_agents: ReadOnlyAgentServiceProtocol | None = None,
    ) -> None:
        self.store = store or MemoryTaskStore()
        self.read_only_agents = read_only_agents
        self._locks_guard = RLock()
        self._task_locks: dict[UUID, RLock] = {}
        self.evidence_provider: Callable[[UUID], list[dict[str, object]]] | None = None

    def create(self, payload: TaskCreate) -> TaskRead:
        task = TaskRead(**payload.model_dump())
        task.messages.append(TaskMessage(role="user", content=payload.issue_body))
        return self.store.save(task)

    def list(self, *, archived: bool = False) -> list[TaskRead]:
        return [task for task in self.store.list() if (task.archived_at is not None) is archived]

    def get(self, task_id: UUID) -> TaskRead:
        task = self.store.get(task_id)
        if task is None:
            raise TaskNotFoundError(str(task_id))
        return task

    @serialized_task
    def update_title(self, task_id: UUID, payload: TaskTitleUpdate) -> TaskRead:
        task = self.get(task_id)
        task.issue_title = payload.title
        task.title_locked = True
        task.updated_at = utc_now()
        return self.store.save(task)

    @serialized_task
    def archive(self, task_id: UUID) -> TaskRead:
        task = self.get(task_id)
        task.archived_at = utc_now()
        task.updated_at = task.archived_at
        return self.store.save(task)

    @serialized_task
    def restore(self, task_id: UUID) -> TaskRead:
        task = self.get(task_id)
        task.archived_at = None
        task.updated_at = utc_now()
        return self.store.save(task)

    @serialized_task
    def create_plan(self, task_id: UUID, payload: PlanCreate) -> TaskRead:
        task = self.get(task_id)
        self._begin_reasoning(task)
        try:
            validate_runnable_task(task)
            if self.read_only_agents is None:
                raise ConversationExecutionError("请先配置大模型，再生成计划。")
            plan = self.read_only_agents.create_plan(task, payload.feedback)
        except Exception as exc:
            self._reasoning_failed(task, exc)
        for item in task.plans:
            item.status = "superseded"
        plan.version = len(task.plans) + 1
        task.plans.append(plan)
        task.planning_status = "ready"
        if not task.title_locked:
            generated_title = plan.problem_summary.split("。", maxsplit=1)[0].strip()
            task.issue_title = generated_title[:60] or task.issue_title
        task.messages.append(
            TaskMessage(
                role="assistant",
                content=plan.problem_summary,
                intent="modify",
                agent_name="规划智能体",
            )
        )
        task.updated_at = utc_now()
        return self.store.save(task)

    @serialized_task
    def approve_plan(self, task_id: UUID, plan_id: UUID) -> TaskRead:
        task = self.get(task_id)
        plan = next((item for item in task.plans if item.id == plan_id), None)
        if plan is None:
            raise PlanNotFoundError(str(plan_id))
        if plan is not task.plans[-1] or plan.status == "superseded":
            raise PlanApprovalRequiredError("只能确认最新的有效计划，请刷新会话。")
        if task.planning_status in {"planning", "failed"}:
            raise PlanApprovalRequiredError("请先完成当前规划，再确认计划。")
        for item in task.plans:
            if item.status == "approved":
                item.status = "superseded"
        plan.status = "approved"
        plan.approved_at = utc_now()
        task.updated_at = plan.approved_at
        task.messages.append(
            TaskMessage(
                role="system",
                content=f"已确认计划 {plan.version}，可以启动修复。",
                intent="system",
            )
        )
        return self.store.save(task)

    @serialized_task
    def add_message(
        self,
        task_id: UUID,
        payload: TaskMessageCreate,
        on_delta: Callable[[str], None] | None = None,
    ) -> TaskRead:
        task = self.get(task_id)
        task.messages.append(TaskMessage(role="user", content=payload.content))
        task.updated_at = utc_now()
        self.store.save(task)
        return self.respond(task_id, on_delta=on_delta)

    @serialized_task
    def respond(
        self,
        task_id: UUID,
        on_delta: Callable[[str], None] | None = None,
    ) -> TaskRead:
        """处理已保存的用户消息；失败重试不会重复追加同一条消息。"""
        task = self.get(task_id)
        if not task.messages or task.messages[-1].role != "user":
            return task
        message = task.messages[-1]
        self._begin_reasoning(task)
        try:
            if self.read_only_agents is None:
                raise ConversationExecutionError("请先配置大模型，再进行对话。")
            context = task.model_copy(deep=True)
            if self.evidence_provider is not None:
                context.run_evidence = self.evidence_provider(task_id)
            reply = self.read_only_agents.converse(context, message.content, on_delta=on_delta)
        except Exception as exc:
            self._reasoning_failed(task, exc)
        message.intent = reply.intent
        task.messages.append(
            TaskMessage(
                role="assistant",
                content=reply.response,
                intent=reply.intent,
                agent_name="对话智能体",
            )
        )
        if reply.intent == "modify" and reply.explicit_action:
            if message.content != task.issue_body:
                task.issue_body = f"{task.issue_body}\n\n补充要求：{message.content}"
            self.store.save(task)
            return self.create_plan(task_id, PlanCreate(feedback=message.content))
        task.planning_status = "ready" if task.plans else "idle"
        task.updated_at = utc_now()
        return self.store.save(task)

    def _begin_reasoning(self, task: TaskRead) -> None:
        task.planning_status = "planning"
        task.planning_error = None
        task.updated_at = utc_now()
        self.store.save(task)

    def _reasoning_failed(self, task: TaskRead, exc: Exception) -> None:
        if isinstance(exc, ValidationError):
            message = str(exc.errors(include_url=False)[0]["msg"]).removeprefix("Value error, ")
        elif isinstance(exc, (AgentExecutionError, ConversationExecutionError, ValueError)):
            message = str(exc)
        else:
            message = "智能体未能完成请求，请检查模型服务与仓库配置后重试。"
        task.planning_status = "failed"
        task.planning_error = message
        task.updated_at = utc_now()
        self.store.save(task)
        raise ConversationExecutionError(message) from exc


class RunService:
    """创建后台运行、同步状态并汇总可复查产物。"""

    def __init__(
        self,
        task_service: TaskService,
        *,
        store: RunStoreProtocol | None = None,
        workflow_service_factory: Callable[[], RepairServiceProtocol] | None = None,
        artifact_store: LocalArtifactStore | None = None,
    ) -> None:
        self.task_service = task_service
        self.store = store or MemoryRunStore()
        self.workflow_service_factory = workflow_service_factory
        self.artifact_store = artifact_store or LocalArtifactStore(Path("outputs"))
        self._lock = RLock()
        self._threads: dict[UUID, Thread] = {}
        self._locks_guard = task_service._locks_guard
        self._task_locks = task_service._task_locks
        task_service.evidence_provider = self.conversation_evidence

    @serialized_task
    def create(self, task_id: UUID) -> TaskRunRead:
        task = self.task_service.get(task_id)
        if (
            not task.plans
            or task.plans[-1].status != "approved"
            or task.planning_status in {"planning", "failed"}
        ):
            raise PlanApprovalRequiredError("请先确认最新执行计划，再启动修复")
        # 创建任务后源仓库可能变化，启动前重新校验并确认计划仍对应当前提交。
        try:
            validate_runnable_task(task)
        except ValueError as exc:
            raise PlanApprovalRequiredError(str(exc)) from exc
        planned_commit = task.plans[-1].base_commit
        if planned_commit and GitTools().base_commit(task.repository_path) != planned_commit:
            raise PlanApprovalRequiredError("仓库提交已变化，请重新生成并确认执行计划。")
        active_runs = [
            run
            for run in self.store.list()
            if run.task_id == task_id
            and (run.status not in self._terminal_statuses() or run.id in self._threads)
        ]
        if active_runs:
            raise ActiveRunExistsError("当前会话已有运行任务，请等待完成或先停止运行")
        snapshot = task.model_copy(deep=True)
        snapshot.confirmed_plan = task.plans[-1].model_copy(deep=True)
        snapshot.messages = []
        snapshot.run_evidence = []
        run = self.store.save(
            TaskRunRead(
                task_id=task.id,
                max_iterations=task.max_iterations,
                execution_task=snapshot,
            )
        )
        self._add_event(run.id, "run.created", payload={"status": run.status.value})
        if self.workflow_service_factory is not None:
            thread = Thread(
                target=self._execute,
                args=(run.id,),
                name=f"evodev-run-{run.id}",
                daemon=True,
            )
            with self._lock:
                self._threads[run.id] = thread
            thread.start()
        return run

    def list(self) -> list[TaskRunRead]:
        return self.store.list()

    def conversation_evidence(self, task_id: UUID) -> list[dict[str, object]]:
        """向问答注入最近三次运行的有限证据，不混用原仓库的 Git 状态。"""
        evidence = []
        for run in [item for item in self.list() if item.task_id == task_id][:3]:
            bundle = self.artifacts(run.id)
            evidence.append(
                {
                    "run_id": str(run.id),
                    "status": run.status.value,
                    "changed_files": run.changed_files,
                    "tests_passed": run.tests_passed,
                    "review_passed": run.review_passed,
                    "error_message": run.error_message,
                    "plan_version": (
                        run.execution_task.confirmed_plan.version
                        if run.execution_task and run.execution_task.confirmed_plan
                        else None
                    ),
                    "patch_excerpt": (bundle.patch or "")[:12000],
                    "patch_truncated": len(bundle.patch or "") > 12000,
                    "baseline_exit_code": (bundle.baseline_test or {}).get("exit_code"),
                    "verification_exit_codes": [
                        item.get("exit_code") for item in bundle.verification_tests
                    ],
                    "isolation": "修改仅保存在该次运行的隔离工作区与补丁中，未应用到原仓库。",
                }
            )
        return evidence

    def get(self, run_id: UUID) -> TaskRunRead:
        run = self.store.get(run_id)
        if run is None:
            raise RunNotFoundError(str(run_id))
        return run

    def events(self, run_id: UUID) -> list[RunEvent]:
        self.get(run_id)
        return self.store.events(run_id)

    def artifacts(self, run_id: UUID) -> RunArtifactBundle:
        """读取当前已经生成的运行文件，运行中调用也安全。"""
        self.get(run_id)
        run_key = run_id.hex
        names = self.artifact_store.list_run_artifacts(run_key)
        trace_prefixes = ("analyst-", "developer-", "failure-analyzer-", "reviewer-")
        return RunArtifactBundle(
            run_id=run_id,
            baseline_test=self._read_json_if_present(run_key, names, "baseline-test.json"),
            verification_tests=[
                self.artifact_store.read_json(run_key, name)
                for name in names
                if name.startswith("test-") and name.endswith(".json")
            ],
            agent_traces=[
                self.artifact_store.read_json(run_key, name)
                for name in names
                if name.startswith(trace_prefixes) and name.endswith(".json")
            ],
            evaluation=self._read_json_if_present(run_key, names, "evaluation.json"),
            patch=(
                self.artifact_store.read_text(run_key, "result.patch")
                if "result.patch" in names
                else None
            ),
            experience=self._read_json_if_present(run_key, names, "experience.json"),
            metrics=self._read_json_if_present(run_key, names, "run-metrics.json"),
        )

    def cancel(self, run_id: UUID) -> TaskRunRead:
        run = self.get(run_id)
        if run.status not in self._terminal_statuses():
            run.status = TaskRunStatus.CANCELLED
            run.finished_at = utc_now()
            self.store.save(run)
            self._add_event(
                run.id,
                "run.cancelled",
                payload={"status": run.status.value},
            )
        return run

    def _execute(self, run_id: UUID) -> None:
        try:
            run = self.get(run_id)
            if run.status is TaskRunStatus.CANCELLED:
                return
            run.status = TaskRunStatus.PREPARING
            run.started_at = utc_now()
            self.store.save(run)
            self._add_event(run_id, "run.started", payload={"status": run.status.value})
            task = run.execution_task or self.task_service.get(run.task_id)
            workflow = self.workflow_service_factory()
            result = workflow.execute(
                run_id=run_id.hex,
                task=task,
                progress_callback=lambda node, update: self._record_progress(run_id, node, update),
            )
            current = self.get(run_id)
            if current.status is TaskRunStatus.CANCELLED:
                return
            self._apply_result(current, result)
            self.store.save(current, result)
            self._add_event(
                run_id,
                "run.completed" if current.status is TaskRunStatus.SUCCEEDED else "run.failed",
                payload={
                    "status": current.status.value,
                    "error_code": current.error_code,
                },
            )
        except Exception as exc:
            self._mark_failed(run_id, exc)
        finally:
            with self._lock:
                self._threads.pop(run_id, None)

    def _record_progress(
        self,
        run_id: UUID,
        node_name: str,
        update: dict[str, object],
    ) -> None:
        run = self.get(run_id)
        if run.status is TaskRunStatus.CANCELLED:
            raise RuntimeError("运行已取消")
        if node_name == "__agent_event__":
            event_payload = dict(update)
            event_type = str(event_payload.pop("event_type", "agent.event"))
            self._add_event(run_id, event_type, payload=event_payload)
            return
        status_value = update.get("status")
        if status_value is not None:
            run.status = TaskRunStatus(str(status_value))
        run.current_node = node_name
        if isinstance(update.get("iteration"), int):
            run.iteration = int(update["iteration"])
        if isinstance(update.get("tests_passed"), bool):
            run.tests_passed = bool(update["tests_passed"])
        if isinstance(update.get("review_passed"), bool):
            run.review_passed = bool(update["review_passed"])
        run.error_code = self._optional_text(update.get("error_code")) or run.error_code
        run.error_message = self._optional_text(update.get("error_message")) or run.error_message
        self.store.save(run)
        self._add_event(
            run_id,
            "node.completed",
            node_name=node_name,
            payload={
                "status": run.status.value,
                "iteration": run.iteration,
                "tests_passed": run.tests_passed,
                "review_passed": run.review_passed,
            },
        )

    @staticmethod
    def _apply_result(run: TaskRunRead, result: dict[str, object]) -> None:
        run.status = TaskRunStatus(str(result["status"]))
        run.current_node = None
        run.iteration = int(result.get("iteration", 0))
        tests_passed = result.get("tests_passed")
        review_passed = result.get("review_passed")
        run.tests_passed = tests_passed if isinstance(tests_passed, bool) else None
        run.review_passed = review_passed if isinstance(review_passed, bool) else None
        run.changed_files = [str(item) for item in result.get("changed_files", [])]
        run.retrieved_experience_ids = [
            str(item) for item in result.get("retrieved_experience_ids", [])
        ]
        run.generated_experience_id = RunService._optional_text(
            result.get("generated_experience_id")
        )
        run.retry_count = int(result.get("retry_count", 0))
        run.prompt_tokens = int(result.get("prompt_tokens", 0))
        run.completion_tokens = int(result.get("completion_tokens", 0))
        run.duration_ms = int(result.get("duration_ms", 0))
        cost_estimate = result.get("cost_estimate")
        run.cost_estimate = dict(cost_estimate) if isinstance(cost_estimate, dict) else None
        run.error_code = RunService._optional_text(result.get("error_code"))
        run.error_message = RunService._optional_text(result.get("error_message"))
        run.finished_at = utc_now()

    def _mark_failed(self, run_id: UUID, exc: Exception) -> None:
        try:
            run = self.get(run_id)
        except RunNotFoundError:
            return
        if run.status is TaskRunStatus.CANCELLED:
            return
        run.status = TaskRunStatus.FAILED
        run.current_node = None
        run.error_code = "RUN_EXECUTION_FAILED"
        run.error_message = str(exc)
        run.finished_at = utc_now()
        self.store.save(run)
        self._add_event(
            run_id,
            "run.failed",
            payload={"status": run.status.value, "error_code": run.error_code},
        )

    def _add_event(
        self,
        run_id: UUID,
        event_type: str,
        *,
        node_name: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> RunEvent:
        return self.store.add_event(
            RunEvent(
                run_id=run_id,
                event_type=event_type,
                node_name=node_name,
                payload=payload or {},
            )
        )

    def _read_json_if_present(
        self,
        run_id: str,
        names: list[str],
        artifact_name: str,
    ) -> dict[str, object] | None:
        if artifact_name not in names:
            return None
        return self.artifact_store.read_json(run_id, artifact_name)

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _terminal_statuses() -> set[TaskRunStatus]:
        return {
            TaskRunStatus.SUCCEEDED,
            TaskRunStatus.FAILED,
            TaskRunStatus.CANCELLED,
        }
