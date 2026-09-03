"""校验工具访问路径，防止操作逃逸出任务工作区。"""

from pathlib import Path


class WorkspacePathError(ValueError):
    """工具请求的路径不在任务工作区内。"""


def resolve_workspace_root(workspace: Path) -> Path:
    """返回已存在的工作区绝对路径。"""
    root = workspace.expanduser().resolve()
    if not root.is_dir():
        raise WorkspacePathError(f"工作区目录不存在：{root}")
    return root


def resolve_workspace_path(workspace: Path, relative_path: str) -> Path:
    """解析工作区内的相对路径，并拒绝越界访问。"""
    root = resolve_workspace_root(workspace)
    requested_path = Path(relative_path)
    if requested_path.is_absolute():
        raise WorkspacePathError(f"只能访问工作区相对路径：{relative_path}")

    candidate = (root / requested_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise WorkspacePathError(f"路径超出任务工作区：{relative_path}") from exc
    return candidate
