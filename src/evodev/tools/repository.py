"""提供受控的仓库文件列表、读取和文本搜索能力。"""

import os
from pathlib import Path

from evodev.tools.paths import resolve_workspace_path, resolve_workspace_root


class RepositoryToolError(RuntimeError):
    """仓库工具无法完成请求。"""


class RepositoryTools:
    """只读取任务工作区内的普通文本文件。"""

    def __init__(self, *, max_file_bytes: int = 1_048_576, max_search_results: int = 200) -> None:
        self.max_file_bytes = max_file_bytes
        self.max_search_results = max_search_results

    def list_files(self, workspace: Path) -> list[str]:
        """按路径排序列出仓库文件，不返回 Git 元数据和符号链接。"""
        root = resolve_workspace_root(workspace)
        files: list[str] = []
        for current_directory, directories, filenames in os.walk(root, followlinks=False):
            current = Path(current_directory)
            directories[:] = sorted(
                name
                for name in directories
                if name != ".git" and not (current / name).is_symlink()
            )
            for filename in sorted(filenames):
                path = current / filename
                if path.is_symlink():
                    continue
                files.append(path.relative_to(root).as_posix())
        return files

    def read_file(self, workspace: Path, relative_path: str) -> str:
        """读取大小受限的 UTF-8 文本文件。"""
        path = resolve_workspace_path(workspace, relative_path)
        if not path.is_file():
            raise RepositoryToolError(f"文件不存在：{relative_path}")
        if path.stat().st_size > self.max_file_bytes:
            raise RepositoryToolError(f"文件超过读取大小限制：{relative_path}")
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise RepositoryToolError(f"文件不是 UTF-8 文本：{relative_path}") from exc
        except OSError as exc:
            raise RepositoryToolError(f"文件读取失败：{relative_path}") from exc

    def search_text(self, workspace: Path, query: str) -> list[str]:
        """返回包含查询文本的文件、行号和单行内容。"""
        if not query:
            raise RepositoryToolError("搜索文本不能为空")

        matches: list[str] = []
        for relative_path in self.list_files(workspace):
            try:
                content = self.read_file(workspace, relative_path)
            except RepositoryToolError:
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                if query not in line:
                    continue
                matches.append(f"{relative_path}:{line_number}:{line}")
                if len(matches) >= self.max_search_results:
                    return matches
        return matches
