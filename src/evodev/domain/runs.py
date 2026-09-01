from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from evodev.domain.enums import TaskRunStatus
from evodev.domain.tasks import utc_now


class TaskRunRead(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    status: TaskRunStatus = TaskRunStatus.CREATED
    workflow_version: str = "bug_fix@1"
    current_node: str | None = None
    iteration: int = 0
    max_iterations: int = 2
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    event_type: str
    node_name: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
