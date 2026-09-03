"""生成工作区的 Git 基准、变更文件、代码差异和补丁。"""

import subprocess
from pathlib import Path

from evodev.tools.paths import resolve_workspace_root


class GitToolError(RuntimeError):
    """Git 工具无法完成请求。"""


class GitTools:
    """读取工作区 Git 状态，不修改源仓库。"""

    def base_commit(self, workspace: Path) -> str:
        """返回工作区当前基准提交。"""
        root = resolve_workspace_root(workspace)
        return self._run_git(root, ["rev-parse", "HEAD"]).stdout.strip()

    def changed_files(self, workspace: Path) -> list[str]:
        """返回已修改、删除和未跟踪文件的有序列表。"""
        root = resolve_workspace_root(workspace)
        tracked = self._run_git(root, ["diff", "--name-only", "HEAD", "--"]).stdout.splitlines()
        untracked = self._run_git(
            root, ["ls-files", "--others", "--exclude-standard", "--"]
        ).stdout.splitlines()
        return sorted({*tracked, *untracked})

    def diff(self, workspace: Path) -> str:
        """生成包含未跟踪文件的二进制安全 Git Diff。"""
        root = resolve_workspace_root(workspace)
        self._run_git(root, ["add", "--intent-to-add", "--all", "--"])
        try:
            return self._run_git(root, ["diff", "--binary", "--no-ext-diff", "HEAD", "--"]).stdout
        finally:
            self._run_git(root, ["reset", "--quiet", "HEAD", "--"])

    def create_patch(self, workspace: Path) -> str:
        """返回可保存或再次应用的补丁文本。"""
        return self.diff(workspace)

    @staticmethod
    def _run_git(workspace: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["git", "-C", str(workspace), *arguments],
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitToolError(f"Git 命令执行失败：{exc}") from exc
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "未知 Git 错误"
            raise GitToolError(message)
        return result
