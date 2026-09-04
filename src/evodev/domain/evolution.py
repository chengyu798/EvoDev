"""定义 Prompt 进化任务、版本和 A/B 评测结果。"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from evodev.domain.tasks import utc_now


class PromptVersionStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    REJECTED = "rejected"
    RETIRED = "retired"


class EvolutionJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


class PromptVersion(BaseModel):
    """附加在固定系统提示词后的可进化指导层。"""

    id: UUID = Field(default_factory=uuid4)
    agent_role: str
    base_prompt_version: str
    revision: int = Field(ge=1)
    guidance: str = Field(min_length=1, max_length=4_000)
    hypothesis: str = Field(min_length=1, max_length=2_000)
    expected_effects: list[str] = Field(default_factory=list, max_length=10)
    risks: list[str] = Field(default_factory=list, max_length=10)
    source_experience_ids: list[UUID] = Field(default_factory=list, max_length=20)
    status: PromptVersionStatus = PromptVersionStatus.CANDIDATE
    evaluation: dict[str, object] | None = None
    rejection_reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    activated_at: datetime | None = None

    @property
    def effective_version(self) -> str:
        return f"{self.base_prompt_version}+e{self.revision}"


class PromptEvolutionJob(BaseModel):
    """由独立 Worker 领取的 Prompt 进化任务。"""

    id: UUID = Field(default_factory=uuid4)
    agent_role: str
    status: EvolutionJobStatus = EvolutionJobStatus.PENDING
    min_experiences: int = Field(default=1, ge=1, le=20)
    candidate_version_id: UUID | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PromptBenchmarkResult(BaseModel):
    """一个 Prompt 版本在一条真实 Bug 任务上的结果。"""

    benchmark_name: str
    succeeded: bool
    retry_count: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    error_code: str | None = None
    error_message: str | None = None


class PromptEvaluationComparison(BaseModel):
    """当前版本与候选版本在同一评测集上的对照结果。"""

    baseline: list[PromptBenchmarkResult]
    candidate: list[PromptBenchmarkResult]
    promoted: bool
    reason: str
