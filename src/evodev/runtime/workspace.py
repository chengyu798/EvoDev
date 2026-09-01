"""描述任务工作区并生成隔离目录路径。"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Workspace:
    run_id: str
    source_repository: Path
    path: Path
    base_commit: str


class WorkspaceManager:
    """生成任务隔离工作区路径。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def workspace_path(self, run_id: str) -> Path:
        return self.root / run_id
