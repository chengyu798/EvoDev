"""验证手动测试环境只能按安全范围清理。"""

from pathlib import Path

import pytest

from evodev.application.cleanup import DemoCleanupService, UnsafeCleanupTargetError
from evodev.persistence.artifacts import LocalArtifactStore
from evodev.persistence.checkpoints import SqliteCheckpointStore
from evodev.runtime.workspace import WorkspaceManager


def build_service(tmp_path: Path) -> tuple[DemoCleanupService, SqliteCheckpointStore]:
    checkpoint_store = SqliteCheckpointStore(f"sqlite:///{tmp_path / 'evodev.db'}")
    service = DemoCleanupService(
        WorkspaceManager(tmp_path / "workspaces"),
        LocalArtifactStore(tmp_path / "outputs"),
        checkpoint_store,
        "evodev-python:3.13",
    )
    return service, checkpoint_store


def add_checkpoint(store: SqliteCheckpointStore, run_id: str) -> None:
    with store.open() as saver:
        saver.setup()
        saver.conn.execute(
            """
            INSERT INTO checkpoints (
                thread_id, checkpoint_ns, checkpoint_id, type, checkpoint, metadata
            ) VALUES (?, '', 'checkpoint-1', 'json', ?, ?)
            """,
            (run_id, b"{}", b"{}"),
        )
        saver.conn.commit()


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
