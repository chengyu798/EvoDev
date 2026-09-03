"""在受限 Docker 容器中执行工作区命令。"""

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

import structlog

from evodev.runtime.command import CommandResult

logger = structlog.get_logger(__name__)


class SandboxUnavailableError(RuntimeError):
    """Docker 沙箱当前不可用。"""


class InvalidCommandError(ValueError):
    """命令或工作区参数不合法。"""


@dataclass(frozen=True, slots=True)
class DockerSandboxConfig:
    """Docker 命令执行需要的镜像和资源限制。"""

    image: str = "evodev-python:3.13"
    network: str = "none"
    cpus: float = 2.0
    memory: str = "2g"
    pids_limit: int = 256
    timeout_seconds: float = 120
    max_output_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if not self.image:
            raise ValueError("沙箱镜像不能为空")
        if self.network != "none":
            raise ValueError("正式命令执行阶段必须关闭容器网络")
        if self.cpus <= 0 or self.pids_limit <= 0:
            raise ValueError("CPU 和进程数量限制必须大于零")
        if self.timeout_seconds <= 0 or self.max_output_bytes <= 0:
            raise ValueError("超时时间和输出限制必须大于零")


class DockerCommandRunner:
    """通过参数列表运行命令，不启用宿主机或容器 Shell。"""

    def __init__(self, config: DockerSandboxConfig | None = None) -> None:
        self.config = config or DockerSandboxConfig()

    def run(
        self,
        workspace: Path,
        command: list[str],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        """执行命令并返回退出码、耗时和大小受限的输出。"""
        root = workspace.expanduser().resolve()
        self._validate_request(root, command)
        if not docker_is_available():
            raise SandboxUnavailableError("Docker 客户端或守护进程不可用")

        timeout = self.config.timeout_seconds if timeout_seconds is None else timeout_seconds
        if timeout <= 0:
            raise InvalidCommandError("命令超时时间必须大于零")

        container_name = f"evodev-{uuid4().hex}"
        docker_command = self._docker_command(root, command, container_name)
        logger.debug("Docker 命令开始", 容器=container_name, 命令=command)
        started_at = time.perf_counter()
        timed_out = False

        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                process = subprocess.Popen(
                    docker_command,
                    stdout=stdout_file,
                    stderr=stderr_file,
                )
            except OSError as exc:
                raise SandboxUnavailableError(f"Docker 命令启动失败：{exc}") from exc

            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._force_remove_container(container_name)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

            duration_ms = int((time.perf_counter() - started_at) * 1000)
            stdout, stderr, output_truncated = self._read_output(stdout_file, stderr_file)

        exit_code = -1 if timed_out else process.returncode
        logger.debug(
            "Docker 命令结束",
            容器=container_name,
            退出码=exit_code,
            耗时毫秒=duration_ms,
            是否超时=timed_out,
            输出已截断=output_truncated,
        )
        return CommandResult(
            command=list(command),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            timed_out=timed_out,
            output_truncated=output_truncated,
        )

    def _docker_command(
        self,
        workspace: Path,
        command: list[str],
        container_name: str,
    ) -> list[str]:
        host_uid = os.getuid()
        host_gid = os.getgid()
        user = "10001:10001" if host_uid == 0 else f"{host_uid}:{host_gid}"
        return [
            "docker",
            "run",
            "--rm",
            "--init",
            "--name",
            container_name,
            "--network",
            self.config.network,
            "--cpus",
            str(self.config.cpus),
            "--memory",
            self.config.memory,
            "--pids-limit",
            str(self.config.pids_limit),
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "--user",
            user,
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--volume",
            f"{workspace}:/workspace:rw",
            "--workdir",
            "/workspace",
            self.config.image,
            *command,
        ]

    def _read_output(
        self,
        stdout_file: BinaryIO,
        stderr_file: BinaryIO,
    ) -> tuple[str, str, bool]:
        stdout_size = self._file_size(stdout_file)
        stderr_size = self._file_size(stderr_file)
        limit = self.config.max_output_bytes
        if stdout_size + stderr_size <= limit:
            stdout_budget, stderr_budget = stdout_size, stderr_size
        else:
            stdout_budget = min(stdout_size, limit // 2)
            stderr_budget = min(stderr_size, limit // 2)
            remaining = limit - stdout_budget - stderr_budget
            stdout_budget += min(stdout_size - stdout_budget, remaining)
            remaining = limit - stdout_budget - stderr_budget
            stderr_budget += min(stderr_size - stderr_budget, remaining)

        stdout = self._read_file(stdout_file, stdout_budget)
        stderr = self._read_file(stderr_file, stderr_budget)
        return stdout, stderr, stdout_size + stderr_size > limit

    @staticmethod
    def _file_size(file: BinaryIO) -> int:
        file.seek(0, os.SEEK_END)
        return file.tell()

    @staticmethod
    def _read_file(file: BinaryIO, limit: int) -> str:
        file.seek(0)
        return file.read(limit).decode("utf-8", errors="replace")

    @staticmethod
    def _validate_request(workspace: Path, command: list[str]) -> None:
        if not workspace.is_dir():
            raise InvalidCommandError(f"工作区目录不存在：{workspace}")
        if not command or not command[0]:
            raise InvalidCommandError("命令不能为空")
        if any("\x00" in argument for argument in command):
            raise InvalidCommandError("命令参数不能包含空字符")

    @staticmethod
    def _force_remove_container(container_name: str) -> None:
        try:
            subprocess.run(
                ["docker", "rm", "--force", container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return


def docker_is_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        # 客户端存在不代表守护进程可用，因此使用短超时做无副作用探测。
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def docker_image_is_available(image: str) -> bool:
    """检查本地是否存在指定沙箱镜像。"""
    if not docker_is_available():
        return False
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
