"""在 Docker 沙箱中执行 pytest 并生成结构化结果。"""

import shlex
from pathlib import Path
from typing import Literal

from evodev.runtime.command import CommandResult
from evodev.runtime.sandbox import DockerCommandRunner

TestKind = Literal["baseline", "verification"]


class InvalidTestCommandError(ValueError):
    """测试命令不是受支持的 pytest 调用。"""


class TestExecutionResult(CommandResult):
    """一次 pytest 执行产生的状态和证据。"""

    kind: TestKind
    passed: bool


class PytestRunner:
    """解析 pytest 命令并交给 Docker Command Runner。"""

    def __init__(self, command_runner: DockerCommandRunner) -> None:
        self.command_runner = command_runner

    def run(
        self,
        workspace: Path,
        test_command: str | list[str] = "pytest -q",
        *,
        kind: TestKind = "verification",
        timeout_seconds: float | None = None,
    ) -> TestExecutionResult:
        """执行测试，并以退出码和超时状态判断是否通过。"""
        command = self._parse_command(test_command)
        result = self.command_runner.run(
            workspace,
            command,
            timeout_seconds=timeout_seconds,
        )
        return TestExecutionResult(
            **result.model_dump(),
            kind=kind,
            passed=result.exit_code == 0 and not result.timed_out,
        )

    @staticmethod
    def _parse_command(test_command: str | list[str]) -> list[str]:
        if isinstance(test_command, str):
            try:
                command = shlex.split(test_command)
            except ValueError as exc:
                raise InvalidTestCommandError(f"pytest 命令解析失败：{exc}") from exc
        else:
            command = list(test_command)

        direct_pytest = bool(command) and Path(command[0]).name in {"pytest", "py.test"}
        module_pytest = (
            len(command) >= 3
            and Path(command[0]).name in {"python", "python3"}
            and command[1:3] == ["-m", "pytest"]
        )
        if not direct_pytest and not module_pytest:
            raise InvalidTestCommandError("测试命令必须使用 pytest 或 python -m pytest")
        return command
