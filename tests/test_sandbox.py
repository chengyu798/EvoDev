"""验证 Docker 命令执行的成功、失败、超时和输出限制。"""

from pathlib import Path

import pytest

from evodev.runtime.sandbox import (
    DockerCommandRunner,
    DockerSandboxConfig,
    InvalidCommandError,
    docker_image_is_available,
)

SANDBOX_IMAGE = "evodev-python:3.13"
sandbox_required = pytest.mark.skipif(
    not docker_image_is_available(SANDBOX_IMAGE),
    reason="本地 Docker 沙箱镜像不可用",
)


def test_reject_empty_command_before_starting_docker(tmp_path: Path) -> None:
    with pytest.raises(InvalidCommandError, match="命令不能为空"):
        DockerCommandRunner().run(tmp_path, [])


@sandbox_required
def test_run_command_and_write_workspace_file(tmp_path: Path) -> None:
    runner = DockerCommandRunner(DockerSandboxConfig(image=SANDBOX_IMAGE))

    result = runner.run(
        tmp_path,
        [
            "python",
            "-c",
            "from pathlib import Path; Path('output.txt').write_text('完成'); print('执行成功')",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == "执行成功\n"
    assert result.stderr == ""
    assert result.timed_out is False
    assert (tmp_path / "output.txt").read_text() == "完成"


@sandbox_required
def test_return_nonzero_exit_code(tmp_path: Path) -> None:
    runner = DockerCommandRunner(DockerSandboxConfig(image=SANDBOX_IMAGE))

    result = runner.run(tmp_path, ["python", "-c", "raise SystemExit(7)"])

    assert result.exit_code == 7
    assert result.timed_out is False


@sandbox_required
def test_run_as_non_root_without_external_network(tmp_path: Path) -> None:
    runner = DockerCommandRunner(DockerSandboxConfig(image=SANDBOX_IMAGE))
    script = (
        "import os, socket; "
        "assert os.geteuid() != 0; "
        "connection = socket.socket(); connection.settimeout(0.5); "
        "result = connection.connect_ex(('1.1.1.1', 53)); "
        "assert result != 0; print('隔离生效')"
    )

    result = runner.run(tmp_path, ["python", "-c", script])

    assert result.exit_code == 0
    assert result.stdout == "隔离生效\n"


@sandbox_required
def test_force_remove_container_after_timeout(tmp_path: Path) -> None:
    runner = DockerCommandRunner(DockerSandboxConfig(image=SANDBOX_IMAGE, timeout_seconds=0.2))

    result = runner.run(tmp_path, ["python", "-c", "import time; time.sleep(10)"])

    assert result.exit_code == -1
    assert result.timed_out is True
    assert result.duration_ms < 5_000


@sandbox_required
def test_truncate_combined_command_output(tmp_path: Path) -> None:
    runner = DockerCommandRunner(DockerSandboxConfig(image=SANDBOX_IMAGE, max_output_bytes=64))

    result = runner.run(
        tmp_path,
        ["python", "-c", "import sys; print('a' * 100); print('b' * 100, file=sys.stderr)"],
    )

    retained_bytes = len(result.stdout.encode()) + len(result.stderr.encode())
    assert result.exit_code == 0
    assert result.output_truncated is True
    assert retained_bytes <= 64
