"""保存工作流产生的日志、测试结果和补丁。"""

import json
import shutil
from pathlib import Path
from typing import Any

from evodev.runtime.workspace import RUN_ID_PATTERN


class InvalidArtifactNameError(ValueError):
    """产物名称不能安全地用作相对路径。"""


class LocalArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def run_path(self, run_id: str) -> Path:
        """返回经过校验的单次运行输出目录。"""
        if not RUN_ID_PATTERN.fullmatch(run_id) or run_id in {".", ".."}:
            raise InvalidArtifactNameError("运行标识不合法")
        return self.root.expanduser().resolve() / run_id

    def path_for(self, run_id: str, artifact_name: str) -> Path:
        """返回单个运行输出文件的安全路径。"""
        if Path(artifact_name).name != artifact_name or artifact_name in {"", ".", ".."}:
            raise InvalidArtifactNameError("产物名称必须是不含目录的文件名")
        return self.run_path(run_id) / artifact_name

    def remove_run(self, run_id: str) -> bool:
        """删除指定运行的输出目录，不影响其他运行。"""
        path = self.run_path(run_id)
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

    def list_run_artifacts(self, run_id: str) -> list[str]:
        """按文件名列出一次运行产生的普通文件。"""
        path = self.run_path(run_id)
        if not path.is_dir():
            return []
        return sorted(item.name for item in path.iterdir() if item.is_file())

    def write_text(self, run_id: str, artifact_name: str, content: str) -> str:
        """以 UTF-8 保存文本并返回可写入状态的产物标识。"""
        path = self.path_for(run_id, artifact_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return artifact_name

    def read_text(self, run_id: str, artifact_id: str) -> str:
        """读取指定运行下的文本产物。"""
        return self.path_for(run_id, artifact_id).read_text(encoding="utf-8")

    def write_json(self, run_id: str, artifact_name: str, value: Any) -> str:
        """保存便于人工检查的中文 JSON 产物。"""
        content = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        return self.write_text(run_id, artifact_name, content)

    def read_json(self, run_id: str, artifact_id: str) -> dict[str, Any]:
        """读取 JSON 对象产物。"""
        value = json.loads(self.read_text(run_id, artifact_id))
        if not isinstance(value, dict):
            raise ValueError("产物内容必须是 JSON 对象")
        return value
