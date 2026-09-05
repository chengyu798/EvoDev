"""安全清理一次手动测试产生的本地资源。"""

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from evodev.persistence.artifacts import LocalArtifactStore
from evodev.persistence.checkpoints import CheckpointStoreProtocol
from evodev.runtime.sandbox import docker_image_is_available
from evodev.runtime.workspace import RUN_ID_PATTERN, WorkspaceManager


class UnsafeCleanupTargetError(ValueError):
    """拒绝删除不属于 EvoDev 手动测试的路径。"""


class SandboxImageCleanupError(RuntimeError):
    """Docker 沙箱镜像无法删除。"""


@dataclass(frozen=True, slots=True)
class CleanupResult:
    """记录本次清理实际删除了哪些资源。"""

    run_id: str
    workspace_removed: bool
    outputs_removed: bool
    checkpoints_removed: bool
    demo_repository_removed: bool
    sandbox_image_removed: bool


class DemoCleanupService:
    """按运行编号清理工作区、输出、检查点和可选演示资源。"""

    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        output_store: LocalArtifactStore,
        checkpoint_store: CheckpointStoreProtocol,
        sandbox_image: str,
    ) -> None:
        self.workspace_manager = workspace_manager
        self.output_store = output_store
        self.checkpoint_store = checkpoint_store
        self.sandbox_image = sandbox_image

    def execute(
        self,
        *,
        run_id: str,
        demo_repository: Path | None = None,
        remove_image: bool = False,
    ) -> CleanupResult:
        if not RUN_ID_PATTERN.fullmatch(run_id) or run_id in {".", ".."}:
            raise UnsafeCleanupTargetError("运行编号不合法")
        demo_path = self._validate_demo_repository(demo_repository)

        workspace_removed = self.workspace_manager.remove(run_id)
        outputs_removed = self.output_store.remove_run(run_id)
        checkpoints_removed = self.checkpoint_store.delete_thread(run_id)
        demo_repository_removed = self._remove_demo_repository(demo_path)
        sandbox_image_removed = self._remove_sandbox_image() if remove_image else False
        return CleanupResult(
            run_id=run_id,
            workspace_removed=workspace_removed,
            outputs_removed=outputs_removed,
            checkpoints_removed=checkpoints_removed,
            demo_repository_removed=demo_repository_removed,
            sandbox_image_removed=sandbox_image_removed,
        )

    @staticmethod
    def _validate_demo_repository(path: Path | None) -> Path | None:
        if path is None:
            return None
        if path.is_symlink():
            raise UnsafeCleanupTargetError("临时示例仓库不能是符号链接")
        resolved = path.expanduser().resolve()
        temp_roots = {Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve()}
        within_temp = any(resolved.is_relative_to(root) for root in temp_roots)
        if not within_temp or not resolved.name.startswith("evodev-demo."):
            raise UnsafeCleanupTargetError("只允许删除临时目录中以 evodev-demo. 开头的示例仓库")
        if not resolved.is_dir() or not (resolved / ".git").is_dir():
            raise UnsafeCleanupTargetError("目标不是已存在的示例 Git 仓库")
        return resolved

    @staticmethod
    def _remove_demo_repository(path: Path | None) -> bool:
        if path is None:
            return False
        shutil.rmtree(path)
        return True

    def _remove_sandbox_image(self) -> bool:
        if not docker_image_is_available(self.sandbox_image):
            return False
        result = subprocess.run(
            ["docker", "image", "rm", self.sandbox_image],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "未知 Docker 错误"
            raise SandboxImageCleanupError(message)
        return True
