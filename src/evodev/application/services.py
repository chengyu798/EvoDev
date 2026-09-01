"""实现任务与运行用例，并隔离接口层和存储层。"""

from uuid import UUID

from evodev.domain.enums import TaskRunStatus
from evodev.domain.runs import RunEvent, TaskRunRead
from evodev.domain.tasks import TaskCreate, TaskRead


class TaskNotFoundError(LookupError):
    pass


class RunNotFoundError(LookupError):
    pass


class TaskService:
    """临时在内存中保存任务，后续由数据库仓储替换。"""

    def __init__(self) -> None:
        self._tasks: dict[UUID, TaskRead] = {}

    def create(self, payload: TaskCreate) -> TaskRead:
        task = TaskRead(**payload.model_dump())
        self._tasks[task.id] = task
        return task

    def list(self) -> list[TaskRead]:
        return sorted(self._tasks.values(), key=lambda item: item.created_at, reverse=True)

    def get(self, task_id: UUID) -> TaskRead:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise TaskNotFoundError(str(task_id)) from exc


class RunService:
    """临时在内存中保存运行和事件记录。"""

    def __init__(self, task_service: TaskService) -> None:
        self._task_service = task_service
        self._runs: dict[UUID, TaskRunRead] = {}
        self._events: dict[UUID, list[RunEvent]] = {}

    def create(self, task_id: UUID) -> TaskRunRead:
        task = self._task_service.get(task_id)
        run = TaskRunRead(task_id=task.id, max_iterations=task.max_iterations)
        self._runs[run.id] = run
        self._events[run.id] = [
            RunEvent(run_id=run.id, event_type="run.created", payload={"status": run.status})
        ]
        return run

    def get(self, run_id: UUID) -> TaskRunRead:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise RunNotFoundError(str(run_id)) from exc

    def events(self, run_id: UUID) -> list[RunEvent]:
        self.get(run_id)
        return list(self._events[run_id])

    def cancel(self, run_id: UUID) -> TaskRunRead:
        run = self.get(run_id)
        if run.status not in {
            TaskRunStatus.SUCCEEDED,
            TaskRunStatus.FAILED,
            TaskRunStatus.CANCELLED,
        }:
            run.status = TaskRunStatus.CANCELLED
            self._events[run.id].append(
                RunEvent(
                    run_id=run.id,
                    event_type="run.cancelled",
                    payload={"status": run.status},
                )
            )
        return run
