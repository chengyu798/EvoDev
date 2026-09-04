"""定义可从历史运行中检索复用的经验数据。"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from evodev.domain.tasks import utc_now


class ExperienceStatus(StrEnum):
    """经验是否继续参与自动检索。"""

    ACTIVE = "active"
    DISABLED = "disabled"


class ExperienceOutcome(StrEnum):
    """一次经验使用最终获得的任务结果。"""

    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"
    IGNORED = "ignored"


class Experience(BaseModel):
    """一次失败运行中提炼出的可检索经验。"""

    id: UUID = Field(default_factory=uuid4)
    source_run_id: UUID
    task_type: str = "bug_fix"
    tags: list[str] = Field(default_factory=list, max_length=20)
    failure_pattern: str
    lesson: str
    recommended_actions: list[str] = Field(default_factory=list)
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    quality_score: float = Field(default=0.5, ge=0.0, le=1.0)
    status: ExperienceStatus = ExperienceStatus.ACTIVE
    last_used_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)

    def prompt_context(self) -> dict[str, object]:
        """返回适合注入 Agent 的精简经验，避免携带数据库字段。"""
        return {
            "experience_id": str(self.id),
            "tags": self.tags,
            "failure_pattern": self.failure_pattern,
            "lesson": self.lesson,
            "recommended_actions": self.recommended_actions,
        }
