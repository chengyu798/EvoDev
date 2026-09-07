"""提供运行查询、取消和事件查询接口。"""

import asyncio
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

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


@router.get("/{run_id}/stream")
async def stream_run_events(
    run_id: UUID,
    request: Request,
    service: RunServiceDep,
) -> StreamingResponse:
    """通过 SSE 向调用方推送真实运行事件。"""

    async def event_stream():
        sent_ids: set[UUID] = set()
        terminal = {"succeeded", "failed", "cancelled"}
        while not await request.is_disconnected():
            for event in service.events(run_id):
                if event.id in sent_ids:
                    continue
                sent_ids.add(event.id)
                payload = event.model_dump(mode="json")
                yield (
                    f"id: {event.id}\n"
                    "event: run_event\n"
                    f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                )
            run = service.get(run_id)
            if run.status.value in terminal:
                yield "event: stream_end\ndata: {}\n\n"
                break
            yield ": keep-alive\n\n"
            await asyncio.sleep(0.2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{run_id}/artifacts", response_model=RunArtifactBundle)
def get_run_artifacts(run_id: UUID, service: RunServiceDep) -> RunArtifactBundle:
    return service.artifacts(run_id)
