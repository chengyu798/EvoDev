"""通过 Git 校验并应用工作区补丁。"""

import subprocess
from pathlib import Path

from evodev.tools.paths import resolve_workspace_root


class PatchApplyError(RuntimeError):
    """补丁无法安全应用到工作区。"""


class EditTools:
    """只使用 Git Apply 修改任务工作区。"""

    def __init__(self, *, max_patch_bytes: int = 1_048_576) -> None:
        self.max_patch_bytes = max_patch_bytes

    def apply_patch(self, workspace: Path, patch: str) -> None:
        """先检查补丁，再将补丁应用到工作区。"""
        if not patch.strip():
            raise PatchApplyError("补丁内容不能为空")
        if len(patch.encode("utf-8")) > self.max_patch_bytes:
            raise PatchApplyError("补丁超过允许的大小限制")

        root = resolve_workspace_root(workspace)
        self._run_git_apply(root, patch, check_only=True)
        self._run_git_apply(root, patch, check_only=False)

    @staticmethod
    def _run_git_apply(workspace: Path, patch: str, *, check_only: bool) -> None:
        command = ["git", "-C", str(workspace), "apply", "--recount", "--whitespace=nowarn"]
        if check_only:
            command.append("--check")
        try:
            result = subprocess.run(
                command,
                input=patch,
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PatchApplyError(f"补丁命令执行失败：{exc}") from exc
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "未知补丁错误"
            raise PatchApplyError(message)
