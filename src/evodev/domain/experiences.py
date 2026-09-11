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


class ExperienceMatch(BaseModel):
    """一次可解释的经验检索结果。"""

    experience: Experience
    score: float = Field(ge=0.0)
    relevance_score: float = Field(ge=0.0)
    quality_factor: float = Field(ge=0.0)
    matched_tags: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

    def prompt_context(self) -> dict[str, object]:
        """在经验内容中附带命中依据，供 Agent 判断是否采用。"""
        return self.experience.prompt_context() | {
            "retrieval": {
                "score": round(self.score, 3),
                "matched_tags": self.matched_tags,
                "reasons": self.reasons,
            }
        }

    def audit_context(self) -> dict[str, object]:
        """返回适合写入运行状态和审计产物的匹配摘要。"""
        return {
            "experience_id": str(self.experience.id),
            "score": round(self.score, 3),
            "relevance_score": round(self.relevance_score, 3),
            "quality_score": self.experience.quality_score,
            "quality_factor": round(self.quality_factor, 3),
            "matched_tags": self.matched_tags,
            "reasons": self.reasons,
        }
