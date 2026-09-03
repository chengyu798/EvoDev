"""验证 pytest 在 Docker 沙箱中的通过、失败和超时结果。"""

from pathlib import Path

import pytest

from evodev.runtime.sandbox import (
    DockerCommandRunner,
    DockerSandboxConfig,
    docker_image_is_available,
)
from evodev.runtime.testing import InvalidTestCommandError, PytestRunner

SANDBOX_IMAGE = "evodev-python:3.13"
sandbox_required = pytest.mark.skipif(
    not docker_image_is_available(SANDBOX_IMAGE),
    reason="本地 Docker 沙箱镜像不可用",
)


def create_runner() -> PytestRunner:
    command_runner = DockerCommandRunner(DockerSandboxConfig(image=SANDBOX_IMAGE))
    return PytestRunner(command_runner)


def test_reject_non_pytest_command(tmp_path: Path) -> None:
    with pytest.raises(InvalidTestCommandError, match="必须使用 pytest"):
        create_runner().run(tmp_path, "python app.py")


@sandbox_required
def test_pytest_runner_records_passing_test(tmp_path: Path) -> None:
    (tmp_path / "test_example.py").write_text(
        "def test_example():\n    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )

    result = create_runner().run(tmp_path, "pytest -q", kind="baseline")

    assert result.kind == "baseline"
    assert result.passed is True
    assert result.exit_code == 0
    assert "1 passed" in result.stdout


@sandbox_required
def test_pytest_runner_records_failing_test(tmp_path: Path) -> None:
    (tmp_path / "test_example.py").write_text(
        "def test_example():\n    assert False\n",
        encoding="utf-8",
    )

    result = create_runner().run(tmp_path, ["python", "-m", "pytest", "-q"])

    assert result.kind == "verification"
    assert result.passed is False
    assert result.exit_code == 1
    assert "1 failed" in result.stdout


@sandbox_required
def test_pytest_runner_records_timeout(tmp_path: Path) -> None:
    (tmp_path / "test_example.py").write_text(
        "import time\n\ndef test_example():\n    time.sleep(10)\n",
        encoding="utf-8",
    )

    result = create_runner().run(tmp_path, timeout_seconds=0.2)

    assert result.passed is False
    assert result.timed_out is True
    assert result.exit_code == -1
