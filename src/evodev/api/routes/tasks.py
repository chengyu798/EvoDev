"""提供任务创建、查询和启动运行接口。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from evodev.api.dependencies import get_run_service, get_task_service
from evodev.application.services import RunService, TaskService
from evodev.domain.runs import TaskRunRead
from evodev.domain.tasks import TaskCreate, TaskRead

router = APIRouter(prefix="/tasks", tags=["tasks"])
TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
RunServiceDep = Annotated[RunService, Depends(get_run_service)]


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, service: TaskServiceDep) -> TaskRead:
    return service.create(payload)


@router.get("", response_model=list[TaskRead])
def list_tasks(service: TaskServiceDep) -> list[TaskRead]:
    return service.list()


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: UUID, service: TaskServiceDep) -> TaskRead:
    return service.get(task_id)


@router.post(
    "/{task_id}/runs",
    response_model=TaskRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_run(task_id: UUID, service: RunServiceDep) -> TaskRunRead:
    return service.create(task_id)
