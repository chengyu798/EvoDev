"""定义任务运行状态和运行事件数据。"""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from evodev.domain.enums import TaskRunStatus
from evodev.domain.tasks import TaskRead, utc_now


class TaskRunRead(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    status: TaskRunStatus = TaskRunStatus.CREATED
    workflow_version: str = "bug_fix@1"
    current_node: str | None = None
    iteration: int = 0
    max_iterations: int = 3
    error_code: str | None = None
    error_message: str | None = None
    tests_passed: bool | None = None
    review_passed: bool | None = None
    changed_files: list[str] = Field(default_factory=list)
    retrieved_experience_ids: list[str] = Field(default_factory=list)
    generated_experience_id: str | None = None
    retry_count: int = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    cost_estimate: dict[str, object] | None = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    execution_task: TaskRead | None = None


class RunEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    event_type: str
    node_name: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class RunArtifactBundle(BaseModel):
    """复查一次运行所需的输出文件集合。"""

    run_id: UUID
    baseline_test: dict[str, object] | None = None
    verification_tests: list[dict[str, object]] = Field(default_factory=list)
    agent_traces: list[dict[str, object]] = Field(default_factory=list)
    evaluation: dict[str, object] | None = None
    patch: str | None = None
    experience: dict[str, object] | None = None
    experience_retrieval: dict[str, object] | None = None
    metrics: dict[str, object] | None = None
