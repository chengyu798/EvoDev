"""定义用于还原运行过程的轨迹事件。"""

from datetime import datetime

from pydantic import BaseModel, Field

from evodev.domain.tasks import utc_now


class TraceEvent(BaseModel):
    run_id: str
    event_type: str
    node_name: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
