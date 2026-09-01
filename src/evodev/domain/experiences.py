"""定义可从历史运行中检索复用的经验数据。"""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from evodev.domain.tasks import utc_now


class Experience(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_run_id: UUID
    task_type: str = "bug_fix"
    tags: list[str] = Field(default_factory=list)
    failure_pattern: str
    lesson: str
    recommended_actions: list[str] = Field(default_factory=list)
    usage_count: int = 0
    created_at: datetime = Field(default_factory=utc_now)
