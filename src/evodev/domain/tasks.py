"""定义会话、消息和执行计划数据，并校验仓库路径。"""

import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
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
    title_locked: bool = False

    @field_validator("repository_path")
    @classmethod
    def validate_repository_path(cls, value: Path) -> Path:
        # 统一为绝对路径，避免工作目录变化后指向错误。
        path = value.expanduser().resolve()
        if not path.is_dir():
            raise ValueError("仓库路径必须指向已存在的目录")
        if not (path / ".git").exists():
            raise ValueError("仓库路径必须指向 Git 仓库")

        def git(*arguments: str) -> str:
            try:
                result = subprocess.run(
                    ["git", "-C", str(path), *arguments],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ValueError("无法检查 Git 仓库，请确认 Git 可用后重试") from exc
            if result.returncode:
                raise ValueError("Git 仓库无有效提交，请先完成一次 git commit")
            return result.stdout.strip()

        if Path(git("rev-parse", "--show-toplevel")).resolve() != path:
            raise ValueError("请选择 Git 仓库根目录")
        git("rev-parse", "--verify", "HEAD^{commit}")
        # 隔离工作区只克隆已提交内容，不能静默忽略用户的修改。
        if git("status", "--porcelain", "--untracked-files=normal"):
            raise ValueError("仓库存在未提交或未跟踪文件，请先提交或清理后重试")
        return path

    @field_validator("test_command")
    @classmethod
    def validate_test_command(cls, value: str) -> str:
        try:
            command = shlex.split(value)
        except ValueError as exc:
            raise ValueError("测试命令引号不完整") from exc
        direct = bool(command) and Path(command[0]).name in {"pytest", "py.test"}
        module = (
            len(command) >= 3
            and Path(command[0]).name in {"python", "python3"}
            and command[1:3] == ["-m", "pytest"]
        )
        if not direct and not module:
            raise ValueError("当前仅支持 pytest 或 python -m pytest 测试命令")
        if any(token in {"&&", "||", ";", "|", ">", "<"} for token in command):
            raise ValueError("测试命令不能包含 Shell 管道或多条命令")
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("测试命令必须为不含控制字符的单行命令")
        return value

    @field_validator("constraints")
    @classmethod
    def validate_constraints(cls, value: list[str]) -> list[str]:
        cleaned = [constraint.strip() for constraint in value]
        if any(not constraint or len(constraint) > 2_000 for constraint in cleaned):
            raise ValueError("每条修改约束需要包含 1 至 2000 个字符")
        return cleaned


class TaskMessage(BaseModel):
    """会话中的一条用户或智能体消息。"""

    id: UUID = Field(default_factory=uuid4)
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=20_000)
    intent: Literal["explain", "modify", "clarify", "system"] | None = None
    agent_name: str | None = None
    run_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)


class TaskPlan(BaseModel):
    """规划智能体生成并等待用户确认的计划版本。"""

    id: UUID = Field(default_factory=uuid4)
    version: int = Field(default=1, ge=1)
    status: Literal["draft", "approved", "superseded"] = "draft"
    problem_summary: str = Field(min_length=1)
    likely_root_cause: str = Field(min_length=1)
    relevant_files: list[str] = Field(default_factory=list)
    implementation_steps: list[str] = Field(min_length=1)
    validation_steps: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    approved_at: datetime | None = None
    base_commit: str | None = None


class TaskTitleUpdate(BaseModel):
    """用户手动修改会话标题。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)


class TaskMessageCreate(BaseModel):
    """用户在现有会话中发送的新消息。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=20_000)


class PlanCreate(BaseModel):
    """首次生成或根据用户反馈更新计划。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    feedback: str | None = Field(default=None, max_length=10_000)


class TaskRead(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    repository_path: Path
    issue_title: str
    issue_body: str
    test_command: str
    constraints: list[str]
    max_iterations: int
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    archived_at: datetime | None = None
    title_locked: bool = False
    messages: list[TaskMessage] = Field(default_factory=list)
    plans: list[TaskPlan] = Field(default_factory=list)
    planning_status: Literal["idle", "planning", "failed", "ready"] = "idle"
    planning_error: str | None = None
    # 仅在运行快照中设置，避免后续对话改写已经批准的执行依据。
    confirmed_plan: TaskPlan | None = None
    run_evidence: list[dict[str, object]] = Field(default_factory=list)
