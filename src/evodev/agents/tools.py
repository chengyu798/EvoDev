"""把仓库能力封装为智能体可调用的受控工具。"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from evodev.runtime.sandbox import DockerCommandRunner
from evodev.tools.edit import EditTools
from evodev.tools.git import GitTools
from evodev.tools.repository import RepositoryTools


class AgentToolError(RuntimeError):
    """智能体请求了未授权或不存在的工具。"""


class AgentToolbox:
    """校验工具权限，并把工具操作限制在当前工作区。"""

    def __init__(
        self,
        repository_tools: RepositoryTools,
        edit_tools: EditTools,
        git_tools: GitTools,
        command_runner: DockerCommandRunner | None = None,
    ) -> None:
        self.repository_tools = repository_tools
        self.edit_tools = edit_tools
        self.git_tools = git_tools
        self.command_runner = command_runner

    def definitions(self, allowed_tools: list[str]) -> list[dict[str, Any]]:
        definitions = self._definitions()
        unknown = sorted(set(allowed_tools) - definitions.keys())
        if unknown:
            raise AgentToolError(f"Agent 配置了未知工具：{', '.join(unknown)}")
        if self.command_runner is None and "run_command" in allowed_tools:
            allowed_tools = [name for name in allowed_tools if name != "run_command"]
        return [definitions[name] for name in allowed_tools]

    def execute(
        self,
        *,
        workspace: Path,
        allowed_tools: list[str],
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        if name not in allowed_tools:
            raise AgentToolError(f"Agent 无权调用工具：{name}")
        handlers: dict[str, Callable[..., object]] = {
            "list_files": lambda: self.repository_tools.list_files(workspace),
            "read_file": lambda path: self.repository_tools.read_file(workspace, path),
            "search_text": lambda query: self.repository_tools.search_text(workspace, query),
            "git_diff": lambda: self.git_tools.diff(workspace),
            "apply_patch": lambda patch: self._apply_patch(workspace, patch),
            "run_command": lambda command: self._run_command(workspace, command),
        }
        try:
            result = handlers[name](**arguments)
        except KeyError as exc:
            raise AgentToolError(f"不存在的工具：{name}") from exc
        except TypeError as exc:
            raise AgentToolError(f"工具 {name} 的参数不正确") from exc
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False)

    def _apply_patch(self, workspace: Path, patch: str) -> str:
        self.edit_tools.apply_patch(workspace, patch)
        return "补丁已成功应用。"

    def _run_command(self, workspace: Path, command: list[str]) -> dict[str, object]:
        if self.command_runner is None:
            raise AgentToolError("当前未配置命令执行工具")
        return self.command_runner.run(workspace, command).model_dump()

    @staticmethod
    def _definitions() -> dict[str, dict[str, Any]]:
        def tool(name: str, description: str, properties: dict[str, Any], required: list[str]):
            return {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "additionalProperties": False,
                    },
                },
            }

        return {
            "list_files": tool("list_files", "列出仓库文件", {}, []),
            "read_file": tool(
                "read_file",
                "读取一个 UTF-8 文本文件",
                {"path": {"type": "string", "description": "仓库相对路径"}},
                ["path"],
            ),
            "search_text": tool(
                "search_text",
                "在仓库中搜索文本",
                {"query": {"type": "string", "description": "要搜索的文本"}},
                ["query"],
            ),
            "git_diff": tool("git_diff", "查看当前代码差异", {}, []),
            "apply_patch": tool(
                "apply_patch",
                "应用标准 Git Diff 补丁；内容必须以 diff --git 开头，不能包含 Markdown 代码围栏",
                {
                    "patch": {
                        "type": "string",
                        "description": "以 diff --git 开头的完整 Git Diff",
                    }
                },
                ["patch"],
            ),
            "run_command": tool(
                "run_command",
                "在 Docker 沙箱中执行参数化命令",
                {
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "命令及参数列表",
                    }
                },
                ["command"],
            ),
        }
