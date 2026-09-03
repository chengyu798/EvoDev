"""描述任务工作区并管理隔离目录的生命周期。"""

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class InvalidRunIdError(ValueError):
    """运行标识不能安全地用作工作区目录名。"""


class WorkspaceAlreadyExistsError(FileExistsError):
    """目标工作区已经存在。"""


class WorkspacePrepareError(RuntimeError):
    """无法从源仓库准备独立工作区。"""


@dataclass(frozen=True, slots=True)
class Workspace:
    run_id: str
    source_repository: Path
    path: Path
    base_commit: str


class WorkspaceManager:
    """在专用根目录中创建和清理任务工作区。"""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def workspace_path(self, run_id: str) -> Path:
        """返回运行对应的安全工作区路径。"""
        if not RUN_ID_PATTERN.fullmatch(run_id) or run_id in {".", ".."}:
            raise InvalidRunIdError(f"运行标识不能用作工作区目录名：{run_id!r}")
        return self.root / run_id

    def create(self, run_id: str) -> Path:
        """创建新的空工作区，已存在时拒绝覆盖。"""
        path = self.workspace_path(run_id)
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            path.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise WorkspaceAlreadyExistsError(f"工作区已经存在：{path}") from exc
        return path

    def exists(self, run_id: str) -> bool:
        """检查工作区目录是否存在。"""
        return self.workspace_path(run_id).is_dir()

    def prepare_repository(
        self,
        run_id: str,
        source_repository: Path,
        revision: str = "HEAD",
    ) -> Workspace:
        """克隆指定提交，创建不影响源仓库的独立工作区。"""
        source = source_repository.expanduser().resolve()
        if not source.is_dir() or not (source / ".git").exists():
            raise WorkspacePrepareError(f"源路径不是 Git 仓库：{source}")

        base_commit = self._resolve_commit(source, revision)
        path = self.create(run_id)
        try:
            self._run_git(
                [
                    "clone",
                    "--quiet",
                    "--no-hardlinks",
                    "--no-checkout",
                    "--",
                    str(source),
                    str(path),
                ]
            )
            self._run_git(["-C", str(path), "checkout", "--quiet", "--detach", base_commit])
        except (OSError, subprocess.SubprocessError, WorkspacePrepareError):
            self.remove(run_id)
            raise

        return Workspace(
            run_id=run_id,
            source_repository=source,
            path=path,
            base_commit=base_commit,
        )

    def remove(self, run_id: str) -> bool:
        """清理工作区；不存在时返回 ``False``。"""
        path = self.workspace_path(run_id)
        if path.is_symlink():
            path.unlink()
            return True
        if not path.exists():
            return False
        if not path.is_dir():
            path.unlink()
            return True
        shutil.rmtree(path)
        return True

    @staticmethod
    def _resolve_commit(repository: Path, revision: str) -> str:
        result = WorkspaceManager._run_git(
            ["-C", str(repository), "rev-parse", "--verify", f"{revision}^{{commit}}"]
        )
        return result.stdout.strip()

    @staticmethod
    def _run_git(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["git", *arguments],
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WorkspacePrepareError(f"Git 命令执行失败：{exc}") from exc
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "未知 Git 错误"
            raise WorkspacePrepareError(message)
        return result
