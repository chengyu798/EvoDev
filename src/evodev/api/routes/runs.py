"""提供运行查询、取消和事件查询接口。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from evodev.api.dependencies import get_run_service
from evodev.application.services import RunService
from evodev.domain.runs import RunArtifactBundle, RunEvent, TaskRunRead

router = APIRouter(prefix="/runs", tags=["runs"])
RunServiceDep = Annotated[RunService, Depends(get_run_service)]


@router.get("", response_model=list[TaskRunRead])
def list_runs(service: RunServiceDep) -> list[TaskRunRead]:
    return service.list()


@router.get("/{run_id}", response_model=TaskRunRead)
def get_run(run_id: UUID, service: RunServiceDep) -> TaskRunRead:
    return service.get(run_id)


@router.post("/{run_id}/cancel", response_model=TaskRunRead)
def cancel_run(run_id: UUID, service: RunServiceDep) -> TaskRunRead:
    return service.cancel(run_id)


@router.get("/{run_id}/events", response_model=list[RunEvent])
def get_run_events(run_id: UUID, service: RunServiceDep) -> list[RunEvent]:
    return service.events(run_id)


@router.get("/{run_id}/artifacts", response_model=RunArtifactBundle)
def get_run_artifacts(run_id: UUID, service: RunServiceDep) -> RunArtifactBundle:
    return service.artifacts(run_id)
