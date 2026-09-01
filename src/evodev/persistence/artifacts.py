"""为每次运行生成本地产物的保存路径。"""

from pathlib import Path


class LocalArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, run_id: str, artifact_name: str) -> Path:
        return self.root / run_id / artifact_name
