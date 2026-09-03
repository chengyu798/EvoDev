"""验证仓库读取、补丁应用和 Git 结果生成工具。"""

import subprocess
from pathlib import Path

import pytest

from evodev.runtime.workspace import WorkspaceManager
from evodev.tools.edit import EditTools, PatchApplyError
from evodev.tools.git import GitTools
from evodev.tools.paths import WorkspacePathError
from evodev.tools.repository import RepositoryToolError, RepositoryTools

EXAMPLE_PATCH = """diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
@@ -1 +1 @@
-value = 1
+value = 2
"""


def prepare_workspace(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "config", "user.name", "测试用户"], check=True)
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "test@example.com"], check=True
    )
    (source / "example.py").write_text("value = 1\n", encoding="utf-8")
    (source / "notes.txt").write_text("第一行\n需要查找的内容\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "--quiet", "-m", "初始提交"], check=True)
    manager = WorkspaceManager(tmp_path / "workspaces")
    return manager.prepare_repository("run-tools", source).path


def test_repository_tools_list_read_and_search_text(tmp_path: Path) -> None:
    workspace = prepare_workspace(tmp_path)
    tools = RepositoryTools()

    assert tools.list_files(workspace) == ["example.py", "notes.txt"]
    assert tools.read_file(workspace, "example.py") == "value = 1\n"
    assert tools.search_text(workspace, "需要查找") == ["notes.txt:2:需要查找的内容"]


def test_repository_tools_reject_path_outside_workspace(tmp_path: Path) -> None:
    workspace = prepare_workspace(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("不能读取", encoding="utf-8")
    (workspace / "outside-link").symlink_to(outside)
    tools = RepositoryTools()

    with pytest.raises(WorkspacePathError, match="超出任务工作区"):
        tools.read_file(workspace, "../outside.txt")
    with pytest.raises(WorkspacePathError, match="超出任务工作区"):
        tools.read_file(workspace, "outside-link")
    assert "outside-link" not in tools.list_files(workspace)


def test_repository_tools_reject_large_and_non_text_file(tmp_path: Path) -> None:
    workspace = prepare_workspace(tmp_path)
    (workspace / "large.txt").write_text("内容过长", encoding="utf-8")
    (workspace / "binary.dat").write_bytes(b"\xff\xfe")
    tools = RepositoryTools(max_file_bytes=4)

    with pytest.raises(RepositoryToolError, match="大小限制"):
        tools.read_file(workspace, "large.txt")
    with pytest.raises(RepositoryToolError, match="不是 UTF-8"):
        RepositoryTools().read_file(workspace, "binary.dat")


def test_edit_tools_apply_checked_patch(tmp_path: Path) -> None:
    workspace = prepare_workspace(tmp_path)

    EditTools().apply_patch(workspace, EXAMPLE_PATCH)

    assert (workspace / "example.py").read_text(encoding="utf-8") == "value = 2\n"


def test_edit_tools_do_not_apply_invalid_patch(tmp_path: Path) -> None:
    workspace = prepare_workspace(tmp_path)

    with pytest.raises(PatchApplyError):
        EditTools().apply_patch(workspace, EXAMPLE_PATCH.replace("value = 1", "missing = 1"))

    assert (workspace / "example.py").read_text(encoding="utf-8") == "value = 1\n"


def test_git_tools_return_changed_files_diff_and_patch(tmp_path: Path) -> None:
    workspace = prepare_workspace(tmp_path)
    EditTools().apply_patch(workspace, EXAMPLE_PATCH)
    (workspace / "new.txt").write_text("新增文件\n", encoding="utf-8")
    tools = GitTools()

    changed_files = tools.changed_files(workspace)
    diff = tools.diff(workspace)
    patch = tools.create_patch(workspace)

    assert changed_files == ["example.py", "new.txt"]
    assert "-value = 1" in diff
    assert "+value = 2" in diff
    assert "diff --git a/new.txt b/new.txt" in diff
    assert patch == diff
    assert tools.base_commit(workspace)
