from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Workspace:
    run_id: str
    source_repository: Path
    path: Path
    base_commit: str


class WorkspaceManager:
    """Interface placeholder for isolated task workspace management."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def workspace_path(self, run_id: str) -> Path:
        return self.root / run_id
