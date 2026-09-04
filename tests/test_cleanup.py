"""验证手动测试环境只能按安全范围清理。"""

from pathlib import Path
from typing import Never

import pytest

from evodev.application.cleanup import DemoCleanupService, UnsafeCleanupTargetError
from evodev.persistence.artifacts import LocalArtifactStore
from evodev.runtime.workspace import WorkspaceManager


class RecordingCheckpointStore:
    """记录测试中的检查点线程，不连接外部 PostgreSQL。"""

    def __init__(self) -> None:
        self.thread_ids: set[str] = set()

    def open(self) -> Never:
        raise AssertionError("清理测试不应直接打开 Checkpointer")

    def delete_thread(self, thread_id: str) -> bool:
        if thread_id not in self.thread_ids:
            return False
        self.thread_ids.remove(thread_id)
        return True


def build_service(tmp_path: Path) -> tuple[DemoCleanupService, RecordingCheckpointStore]:
    checkpoint_store = RecordingCheckpointStore()
    service = DemoCleanupService(
        WorkspaceManager(tmp_path / "workspaces"),
        LocalArtifactStore(tmp_path / "outputs"),
        checkpoint_store,
        "evodev-python:3.13",
    )
    return service, checkpoint_store


def add_checkpoint(store: RecordingCheckpointStore, run_id: str) -> None:
    store.thread_ids.add(run_id)


def test_cleanup_removes_only_selected_demo_resources(tmp_path: Path) -> None:
    run_id = "run-1"
    service, checkpoint_store = build_service(tmp_path)
    workspace = tmp_path / "workspaces" / run_id
    output = tmp_path / "outputs" / run_id
    demo_repository = tmp_path / "evodev-demo.test"
    workspace.mkdir(parents=True)
    output.mkdir(parents=True)
    (output / "result.patch").write_text("patch", encoding="utf-8")
    (demo_repository / ".git").mkdir(parents=True)
    add_checkpoint(checkpoint_store, run_id)

    result = service.execute(run_id=run_id, demo_repository=demo_repository)

    assert result.workspace_removed is True
    assert result.outputs_removed is True
    assert result.checkpoints_removed is True
    assert result.demo_repository_removed is True
    assert result.sandbox_image_removed is False
    assert not workspace.exists()
    assert not output.exists()
    assert not demo_repository.exists()
    assert checkpoint_store.delete_thread(run_id) is False


def test_cleanup_rejects_repository_outside_demo_naming_rule(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path)
    workspace = tmp_path / "workspaces" / "run-1"
    unsafe_repository = tmp_path / "important-project"
    workspace.mkdir(parents=True)
    (unsafe_repository / ".git").mkdir(parents=True)

    with pytest.raises(UnsafeCleanupTargetError, match="evodev-demo"):
        service.execute(run_id="run-1", demo_repository=unsafe_repository)

    assert workspace.exists()
