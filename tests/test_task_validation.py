"""使用独立临时仓库检查提交边界，不修改真实项目。"""

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from evodev.domain.tasks import TaskCreate


def git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
    )


def create_task(repository: Path) -> TaskCreate:
    return TaskCreate(repository_path=repository, issue_title="修复", issue_body="修复加法")


def commit(repository: Path) -> None:
    git(
        repository,
        "-c",
        "user.name=测试",
        "-c",
        "user.email=test@example.com",
        "commit",
        "--allow-empty",
        "-qm",
        "初始化",
    )


def test_empty_repository_rejected(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    with pytest.raises(ValidationError, match="有效提交"):
        create_task(tmp_path)


def test_clean_committed_repository_accepted(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    commit(tmp_path)
    assert create_task(tmp_path).repository_path == tmp_path.resolve()


def test_untracked_and_staged_files_rejected(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    commit(tmp_path)
    (tmp_path / "example.py").write_text("print('测试')\n")
    with pytest.raises(ValidationError, match="未提交或未跟踪"):
        create_task(tmp_path)
    git(tmp_path, "add", "example.py")
    with pytest.raises(ValidationError, match="未提交或未跟踪"):
        create_task(tmp_path)
    commit(tmp_path)
    assert create_task(tmp_path)


def test_fake_git_directory_rejected(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    with pytest.raises(ValidationError):
        create_task(tmp_path)


def test_nested_directory_rejected(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    commit(tmp_path)
    nested = tmp_path / "nested"
    nested.mkdir()
    with pytest.raises(ValidationError):
        create_task(nested)


def test_git_timeout_reported_in_chinese(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").mkdir()

    def timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("git", 10)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(ValidationError, match="无法检查 Git 仓库"):
        create_task(tmp_path)


@pytest.mark.parametrize("command", ["npm test", 'pytest "', "pytest -q && echo ok", "pytest\n-q"])
def test_unsupported_test_command_rejected(tmp_path: Path, command: str) -> None:
    git(tmp_path, "init", "-q")
    commit(tmp_path)
    with pytest.raises(ValidationError, match="测试命令"):
        TaskCreate(
            repository_path=tmp_path, issue_title="修复", issue_body="修复", test_command=command
        )


def test_blank_constraint_rejected(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    commit(tmp_path)
    with pytest.raises(ValidationError, match="修改约束"):
        TaskCreate(
            repository_path=tmp_path, issue_title="修复", issue_body="修复", constraints=["  "]
        )
