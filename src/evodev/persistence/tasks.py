"""使用 PostgreSQL 保存任务、运行摘要和状态事件。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from evodev.domain.runs import RunEvent, TaskRunRead
from evodev.domain.tasks import TaskRead
from evodev.persistence.checkpoints import validate_postgres_url


class TaskStoreProtocol(Protocol):
    def save(self, task: TaskRead) -> TaskRead: ...

    def list(self) -> list[TaskRead]: ...

    def get(self, task_id: UUID) -> TaskRead | None: ...


class RunStoreProtocol(Protocol):
    def save(self, run: TaskRunRead, result: dict[str, object] | None = None) -> TaskRunRead: ...

    def list(self) -> list[TaskRunRead]: ...

    def get(self, run_id: UUID) -> TaskRunRead | None: ...

    def get_result(self, run_id: UUID) -> dict[str, object] | None: ...

    def add_event(self, event: RunEvent) -> RunEvent: ...

    def events(self, run_id: UUID) -> list[RunEvent]: ...


class MemoryTaskStore:
    """供单元测试和无数据库场景使用的任务仓库。"""

    def __init__(self) -> None:
        self.tasks: dict[UUID, TaskRead] = {}

    def save(self, task: TaskRead) -> TaskRead:
        self.tasks[task.id] = task.model_copy(deep=True)
        return task

    def list(self) -> list[TaskRead]:
        return sorted(self.tasks.values(), key=lambda item: item.created_at, reverse=True)

    def get(self, task_id: UUID) -> TaskRead | None:
        task = self.tasks.get(task_id)
        return task.model_copy(deep=True) if task else None


class MemoryRunStore:
    """供单元测试和无数据库场景使用的运行仓库。"""

    def __init__(self) -> None:
        self.runs: dict[UUID, TaskRunRead] = {}
        self.results: dict[UUID, dict[str, object]] = {}
        self.run_events: dict[UUID, list[RunEvent]] = {}

    def save(
        self,
        run: TaskRunRead,
        result: dict[str, object] | None = None,
    ) -> TaskRunRead:
        self.runs[run.id] = run.model_copy(deep=True)
        if result is not None:
            self.results[run.id] = dict(result)
        return run

    def list(self) -> list[TaskRunRead]:
        return sorted(self.runs.values(), key=lambda item: item.created_at, reverse=True)

    def get(self, run_id: UUID) -> TaskRunRead | None:
        run = self.runs.get(run_id)
        return run.model_copy(deep=True) if run else None

    def get_result(self, run_id: UUID) -> dict[str, object] | None:
        result = self.results.get(run_id)
        return dict(result) if result else None

    def add_event(self, event: RunEvent) -> RunEvent:
        self.run_events.setdefault(event.run_id, []).append(event.model_copy(deep=True))
        return event

    def events(self, run_id: UUID) -> list[RunEvent]:
        return [item.model_copy(deep=True) for item in self.run_events.get(run_id, [])]


class PostgresTaskRunStore:
    """在同一数据库中管理任务、运行和事件。"""

    def __init__(self, database_url: str) -> None:
        self.database_url = validate_postgres_url(database_url)
        self._initialized = False

    def setup(self) -> None:
        """创建任务和运行相关表，重复调用不会清空数据。"""
        if self._initialized:
            return
        with connect(self.database_url, autocommit=True) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evodev_tasks (
                    id UUID PRIMARY KEY,
                    repository_path TEXT NOT NULL,
                    issue_title TEXT NOT NULL,
                    issue_body TEXT NOT NULL,
                    test_command TEXT NOT NULL,
                    constraints JSONB NOT NULL DEFAULT '[]'::jsonb,
                    max_iterations INTEGER NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    archived_at TIMESTAMPTZ,
                    title_locked BOOLEAN NOT NULL DEFAULT FALSE,
                    messages JSONB NOT NULL DEFAULT '[]'::jsonb,
                    plans JSONB NOT NULL DEFAULT '[]'::jsonb,
                    planning_status TEXT NOT NULL DEFAULT 'idle',
                    planning_error TEXT
                )
                """
            )
            # 为已有开发数据库补齐会话字段，不要求手工执行迁移脚本。
            connection.execute(
                """
                ALTER TABLE evodev_tasks
                    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ,
                    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ,
                    ADD COLUMN IF NOT EXISTS title_locked BOOLEAN NOT NULL DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS messages JSONB NOT NULL DEFAULT '[]'::jsonb,
                    ADD COLUMN IF NOT EXISTS plans JSONB NOT NULL DEFAULT '[]'::jsonb,
                    ADD COLUMN IF NOT EXISTS planning_status TEXT NOT NULL DEFAULT 'idle',
                    ADD COLUMN IF NOT EXISTS planning_error TEXT
                """
            )
            connection.execute(
                """
                UPDATE evodev_tasks
                SET updated_at = created_at
                WHERE updated_at IS NULL
                """
            )
            connection.execute(
                """
                ALTER TABLE evodev_tasks
                    ALTER COLUMN updated_at SET NOT NULL
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evodev_task_runs (
                    id UUID PRIMARY KEY,
                    task_id UUID NOT NULL REFERENCES evodev_tasks(id),
                    status TEXT NOT NULL,
                    workflow_version TEXT NOT NULL,
                    current_node TEXT,
                    iteration INTEGER NOT NULL DEFAULT 0,
                    max_iterations INTEGER NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    tests_passed BOOLEAN,
                    review_passed BOOLEAN,
                    changed_files JSONB NOT NULL DEFAULT '[]'::jsonb,
                    retrieved_experience_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    generated_experience_id TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    cost_estimate JSONB,
                    execution_task JSONB,
                    result JSONB,
                    created_at TIMESTAMPTZ NOT NULL,
                    started_at TIMESTAMPTZ,
                    finished_at TIMESTAMPTZ
                )
                """
            )
            connection.execute(
                """
                ALTER TABLE evodev_task_runs
                    ADD COLUMN IF NOT EXISTS cost_estimate JSONB,
                    ADD COLUMN IF NOT EXISTS execution_task JSONB
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evodev_run_events (
                    id UUID PRIMARY KEY,
                    run_id UUID NOT NULL REFERENCES evodev_task_runs(id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    node_name TEXT,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS evodev_run_events_run_created_idx
                ON evodev_run_events (run_id, created_at)
                """
            )
        self._initialized = True

    def save(self, value: TaskRead | TaskRunRead, result: dict[str, object] | None = None):
        """根据模型类型保存任务或运行。"""
        if isinstance(value, TaskRead):
            return self.save_task(value)
        return self.save_run(value, result)

    def save_task(self, task: TaskRead) -> TaskRead:
        self.setup()
        with connect(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO evodev_tasks (
                    id, repository_path, issue_title, issue_body, test_command,
                    constraints, max_iterations, created_at, updated_at, archived_at,
                    title_locked, messages, plans, planning_status, planning_error
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    repository_path = EXCLUDED.repository_path,
                    issue_title = EXCLUDED.issue_title,
                    issue_body = EXCLUDED.issue_body,
                    test_command = EXCLUDED.test_command,
                    constraints = EXCLUDED.constraints,
                    max_iterations = EXCLUDED.max_iterations,
                    updated_at = EXCLUDED.updated_at,
                    archived_at = EXCLUDED.archived_at,
                    title_locked = EXCLUDED.title_locked,
                    messages = EXCLUDED.messages,
                    plans = EXCLUDED.plans,
                    planning_status = EXCLUDED.planning_status,
                    planning_error = EXCLUDED.planning_error
                """,
                (
                    task.id,
                    str(task.repository_path),
                    task.issue_title,
                    task.issue_body,
                    task.test_command,
                    Jsonb(task.constraints),
                    task.max_iterations,
                    task.created_at,
                    task.updated_at,
                    task.archived_at,
                    task.title_locked,
                    Jsonb([message.model_dump(mode="json") for message in task.messages]),
                    Jsonb([plan.model_dump(mode="json") for plan in task.plans]),
                    task.planning_status,
                    task.planning_error,
                ),
            )
            connection.commit()
        return task

    def list(self) -> list[TaskRead]:
        return self.list_tasks()

    def list_tasks(self) -> list[TaskRead]:
        self.setup()
        with connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                "SELECT * FROM evodev_tasks ORDER BY created_at DESC"
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def get(self, task_id: UUID) -> TaskRead | None:
        return self.get_task(task_id)

    def get_task(self, task_id: UUID) -> TaskRead | None:
        self.setup()
        with connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                "SELECT * FROM evodev_tasks WHERE id = %s", (task_id,)
            ).fetchone()
        return self._task_from_row(row) if row else None

    def save_run(
        self,
        run: TaskRunRead,
        result: dict[str, object] | None = None,
    ) -> TaskRunRead:
        self.setup()
        with connect(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO evodev_task_runs (
                    id, task_id, status, workflow_version, current_node, iteration,
                    max_iterations, error_code, error_message, tests_passed,
                    review_passed, changed_files, retrieved_experience_ids,
                    generated_experience_id, retry_count, prompt_tokens,
                    completion_tokens, duration_ms, cost_estimate, execution_task,
                    result, created_at, started_at, finished_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    workflow_version = EXCLUDED.workflow_version,
                    current_node = EXCLUDED.current_node,
                    iteration = EXCLUDED.iteration,
                    error_code = EXCLUDED.error_code,
                    error_message = EXCLUDED.error_message,
                    tests_passed = EXCLUDED.tests_passed,
                    review_passed = EXCLUDED.review_passed,
                    changed_files = EXCLUDED.changed_files,
                    retrieved_experience_ids = EXCLUDED.retrieved_experience_ids,
                    generated_experience_id = EXCLUDED.generated_experience_id,
                    retry_count = EXCLUDED.retry_count,
                    prompt_tokens = EXCLUDED.prompt_tokens,
                    completion_tokens = EXCLUDED.completion_tokens,
                    duration_ms = EXCLUDED.duration_ms,
                    cost_estimate = EXCLUDED.cost_estimate,
                    execution_task = COALESCE(
                        EXCLUDED.execution_task, evodev_task_runs.execution_task
                    ),
                    result = COALESCE(EXCLUDED.result, evodev_task_runs.result),
                    started_at = EXCLUDED.started_at,
                    finished_at = EXCLUDED.finished_at
                """,
                (
                    run.id,
                    run.task_id,
                    run.status.value,
                    run.workflow_version,
                    run.current_node,
                    run.iteration,
                    run.max_iterations,
                    run.error_code,
                    run.error_message,
                    run.tests_passed,
                    run.review_passed,
                    Jsonb(run.changed_files),
                    Jsonb(run.retrieved_experience_ids),
                    run.generated_experience_id,
                    run.retry_count,
                    run.prompt_tokens,
                    run.completion_tokens,
                    run.duration_ms,
                    Jsonb(run.cost_estimate) if run.cost_estimate is not None else None,
                    Jsonb(run.execution_task.model_dump(mode="json"))
                    if run.execution_task is not None
                    else None,
                    Jsonb(result) if result is not None else None,
                    run.created_at,
                    run.started_at,
                    run.finished_at,
                ),
            )
            connection.commit()
        return run

    def list_runs(self) -> list[TaskRunRead]:
        self.setup()
        with connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                "SELECT * FROM evodev_task_runs ORDER BY created_at DESC"
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def get_run(self, run_id: UUID) -> TaskRunRead | None:
        self.setup()
        with connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                "SELECT * FROM evodev_task_runs WHERE id = %s", (run_id,)
            ).fetchone()
        return self._run_from_row(row) if row else None

    def get_result(self, run_id: UUID) -> dict[str, object] | None:
        self.setup()
        with connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                "SELECT result FROM evodev_task_runs WHERE id = %s", (run_id,)
            ).fetchone()
        return dict(row["result"]) if row and row["result"] else None

    def add_event(self, event: RunEvent) -> RunEvent:
        self.setup()
        with connect(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO evodev_run_events (
                    id, run_id, event_type, node_name, payload, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    event.id,
                    event.run_id,
                    event.event_type,
                    event.node_name,
                    Jsonb(event.payload),
                    event.created_at,
                ),
            )
            connection.commit()
        return event

    def events(self, run_id: UUID) -> list[RunEvent]:
        self.setup()
        with connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT * FROM evodev_run_events
                WHERE run_id = %s ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()
        return [RunEvent.model_validate(row) for row in rows]

    @staticmethod
    def _task_from_row(row: dict[str, object]) -> TaskRead:
        return TaskRead.model_validate(row)

    @staticmethod
    def _run_from_row(row: dict[str, object]) -> TaskRunRead:
        return TaskRunRead.model_validate(row)


class PostgresTaskStore:
    """向任务服务暴露单一职责接口。"""

    def __init__(self, store: PostgresTaskRunStore) -> None:
        self.store = store

    def save(self, task: TaskRead) -> TaskRead:
        return self.store.save_task(task)

    def list(self) -> list[TaskRead]:
        return self.store.list_tasks()

    def get(self, task_id: UUID) -> TaskRead | None:
        return self.store.get_task(task_id)


class PostgresRunStore:
    """向运行服务暴露单一职责接口。"""

    def __init__(self, store: PostgresTaskRunStore) -> None:
        self.store = store

    def save(
        self,
        run: TaskRunRead,
        result: dict[str, object] | None = None,
    ) -> TaskRunRead:
        return self.store.save_run(run, result)

    def list(self) -> list[TaskRunRead]:
        return self.store.list_runs()

    def get(self, run_id: UUID) -> TaskRunRead | None:
        return self.store.get_run(run_id)

    def get_result(self, run_id: UUID) -> dict[str, object] | None:
        return self.store.get_result(run_id)

    def add_event(self, event: RunEvent) -> RunEvent:
        return self.store.add_event(event)

    def events(self, run_id: UUID) -> list[RunEvent]:
        return self.store.events(run_id)
