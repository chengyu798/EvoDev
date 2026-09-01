"""定义任务创建与查询数据，并校验仓库路径。"""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class TaskCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    repository_path: Path
    issue_title: str = Field(min_length=1, max_length=200)
    issue_body: str = Field(min_length=1, max_length=20_000)
    test_command: str = Field(default="pytest -q", min_length=1, max_length=500)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    max_iterations: int = Field(default=3, ge=1, le=3)

    @field_validator("repository_path")
    @classmethod
    def validate_repository_path(cls, value: Path) -> Path:
        # 统一为绝对路径，避免工作目录变化后指向错误。
        path = value.expanduser().resolve()
        if not path.is_dir():
            raise ValueError("仓库路径必须指向已存在的目录")
        if not (path / ".git").exists():
            raise ValueError("仓库路径必须指向 Git 仓库")
        return path


class TaskRead(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    repository_path: Path
    issue_title: str
    issue_body: str
    test_command: str
    constraints: list[str]
    max_iterations: int
    created_at: datetime = Field(default_factory=utc_now)
