"""提供任务创建、查询、流式对话和启动运行接口。"""

import asyncio
import json
from collections.abc import Callable
from queue import Empty, Queue
from threading import Thread
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse

from evodev.api.dependencies import get_run_service, get_task_service
from evodev.application.services import RunService, TaskService
from evodev.domain.runs import TaskRunRead
from evodev.domain.tasks import (
    PlanCreate,
    TaskCreate,
    TaskMessageCreate,
    TaskRead,
    TaskTitleUpdate,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])
TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
RunServiceDep = Annotated[RunService, Depends(get_run_service)]


def _stream_task_response(
    request: Request,
    operation: Callable[[Callable[[str], None]], TaskRead],
) -> StreamingResponse:
    """在后台执行同步智能体，并把响应文本逐块推送给调用方。"""

    messages: Queue[tuple[str, object]] = Queue()

    def worker() -> None:
        try:
            task = operation(lambda delta: messages.put(("delta", {"delta": delta})))
            messages.put(("complete", task.model_dump(mode="json")))
        except Exception as exc:
            messages.put(("error", {"message": str(exc)}))

    Thread(target=worker, name="evodev-conversation-stream", daemon=True).start()

    async def event_stream():
        while not await request.is_disconnected():
            try:
                event_type, payload = await asyncio.to_thread(messages.get, True, 10)
            except Empty:
                yield ": keep-alive\n\n"
                continue
            yield (
                f"event: {event_type}\n"
                f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            )
            if event_type in {"complete", "error"}:
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, service: TaskServiceDep) -> TaskRead:
    return service.create(payload)


@router.get("", response_model=list[TaskRead])
def list_tasks(
    service: TaskServiceDep,
    archived: bool = Query(default=False),
) -> list[TaskRead]:
    return service.list(archived=archived)


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: UUID, service: TaskServiceDep) -> TaskRead:
    return service.get(task_id)


@router.patch("/{task_id}/title", response_model=TaskRead)
def update_task_title(
    task_id: UUID,
    payload: TaskTitleUpdate,
    service: TaskServiceDep,
) -> TaskRead:
    return service.update_title(task_id, payload)


@router.post("/{task_id}/archive", response_model=TaskRead)
def archive_task(task_id: UUID, service: TaskServiceDep) -> TaskRead:
    return service.archive(task_id)


@router.post("/{task_id}/restore", response_model=TaskRead)
def restore_task(task_id: UUID, service: TaskServiceDep) -> TaskRead:
    return service.restore(task_id)


@router.post("/{task_id}/messages", response_model=TaskRead)
def add_task_message(
    task_id: UUID,
    payload: TaskMessageCreate,
    service: TaskServiceDep,
) -> TaskRead:
    return service.add_message(task_id, payload)


@router.post("/{task_id}/messages/stream")
def stream_task_message(
    task_id: UUID,
    payload: TaskMessageCreate,
    request: Request,
    service: TaskServiceDep,
) -> StreamingResponse:
    return _stream_task_response(
        request,
        lambda on_delta: service.add_message(task_id, payload, on_delta=on_delta),
    )


@router.post("/{task_id}/plans", response_model=TaskRead)
def create_task_plan(
    task_id: UUID,
    payload: PlanCreate,
    service: TaskServiceDep,
) -> TaskRead:
    return service.create_plan(task_id, payload)


@router.post("/{task_id}/respond", response_model=TaskRead)
def respond_to_task(task_id: UUID, service: TaskServiceDep) -> TaskRead:
    return service.respond(task_id)


@router.post("/{task_id}/respond/stream")
def stream_task_response(
    task_id: UUID,
    request: Request,
    service: TaskServiceDep,
) -> StreamingResponse:
    return _stream_task_response(
        request,
        lambda on_delta: service.respond(task_id, on_delta=on_delta),
    )


@router.post("/{task_id}/plans/{plan_id}/approve", response_model=TaskRead)
def approve_task_plan(
    task_id: UUID,
    plan_id: UUID,
    service: TaskServiceDep,
) -> TaskRead:
    return service.approve_plan(task_id, plan_id)


@router.post(
    "/{task_id}/runs",
    response_model=TaskRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_run(task_id: UUID, service: RunServiceDep) -> TaskRunRead:
    return service.create(task_id)
