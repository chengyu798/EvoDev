"""验证任务工作区的创建、路径边界和清理行为。"""

import subprocess
from pathlib import Path

import pytest

from evodev.runtime.workspace import (
    InvalidRunIdError,
    WorkspaceAlreadyExistsError,
    WorkspaceManager,
    WorkspacePrepareError,
)


def initialize_repository(path: Path) -> str:
    path.mkdir()
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "测试用户"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
    (path / "example.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "example.py"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "--quiet", "-m", "初始提交"], check=True)
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_create_workspace_in_configured_root(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspaces")

    workspace = manager.create("run-123")

    assert workspace == (tmp_path / "workspaces" / "run-123").resolve()
    assert workspace.is_dir()
    assert list(workspace.iterdir()) == []
    assert manager.exists("run-123") is True


@pytest.mark.parametrize(
    "run_id",
    ["", ".", "..", "../outside", "run/child", r"run\child", " run-1"],
)
def test_reject_unsafe_run_id(tmp_path: Path, run_id: str) -> None:
    manager = WorkspaceManager(tmp_path / "workspaces")

    with pytest.raises(InvalidRunIdError, match="不能用作工作区目录名"):
        manager.workspace_path(run_id)


def test_create_does_not_overwrite_existing_workspace(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspaces")
    workspace = manager.create("run-123")
    existing_file = workspace / "existing.txt"
    existing_file.write_text("保留内容", encoding="utf-8")

    with pytest.raises(WorkspaceAlreadyExistsError, match="工作区已经存在"):
        manager.create("run-123")

    assert existing_file.read_text(encoding="utf-8") == "保留内容"


def test_remove_only_deletes_selected_workspace(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspaces")
    first = manager.create("run-first")
    second = manager.create("run-second")
    (first / "result.txt").write_text("运行产物", encoding="utf-8")

    assert manager.remove("run-first") is True
    assert first.exists() is False
    assert second.is_dir()
    assert manager.remove("run-first") is False


def test_remove_symlink_does_not_follow_external_target(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspaces")
    manager.root.mkdir()
    external_directory = tmp_path / "external"
    external_directory.mkdir()
    external_file = external_directory / "important.txt"
    external_file.write_text("不能删除", encoding="utf-8")
    workspace_link = manager.workspace_path("run-link")
    workspace_link.symlink_to(external_directory, target_is_directory=True)

    assert manager.remove("run-link") is True
    assert workspace_link.exists() is False
    assert external_file.read_text(encoding="utf-8") == "不能删除"


def test_prepare_repository_creates_independent_detached_clone(tmp_path: Path) -> None:
    source = tmp_path / "source"
    base_commit = initialize_repository(source)
    manager = WorkspaceManager(tmp_path / "workspaces")

    workspace = manager.prepare_repository("run-123", source)
    (workspace.path / "example.py").write_text("value = 2\n", encoding="utf-8")

    assert workspace.source_repository == source.resolve()
    assert workspace.base_commit == base_commit
    assert (source / "example.py").read_text(encoding="utf-8") == "value = 1\n"
    assert (workspace.path / ".git").is_dir()
    branch_result = subprocess.run(
        ["git", "-C", str(workspace.path), "symbolic-ref", "--quiet", "HEAD"],
        capture_output=True,
        check=False,
    )
    assert branch_result.returncode == 1


def test_prepare_repository_does_not_create_workspace_for_invalid_revision(tmp_path: Path) -> None:
    source = tmp_path / "source"
    initialize_repository(source)
    manager = WorkspaceManager(tmp_path / "workspaces")

    with pytest.raises(WorkspacePrepareError):
        manager.prepare_repository("run-invalid", source, revision="missing-revision")

    assert manager.exists("run-invalid") is False
