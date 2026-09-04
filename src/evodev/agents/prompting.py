"""加载并渲染独立维护的 Agent 系统提示词。"""

import json
import re
from importlib.resources import files
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from evodev.domain.agents import AgentDefinition

PROMPT_FILE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.md$")
PROMPT_VERSION_PLACEHOLDER = "{{PROMPT_VERSION}}"
OUTPUT_SCHEMA_PLACEHOLDER = "{{OUTPUT_SCHEMA}}"


class PromptTemplateError(ValueError):
    """提示词文件缺失、命名不安全或内容不完整。"""


class PromptSource(Protocol):
    """提示词文本来源需要提供的最小接口。"""

    def read(self, prompt_file: str) -> str: ...


class PackagePromptSource:
    """从安装包内的 prompts 目录读取提示词。"""

    def read(self, prompt_file: str) -> str:
        try:
            return (
                files("evodev.agents.prompts")
                .joinpath(prompt_file)
                .read_text(encoding="utf-8")
            )
        except (FileNotFoundError, ModuleNotFoundError) as exc:
            raise PromptTemplateError(f"找不到 Agent 提示词文件：{prompt_file}") from exc


class DirectoryPromptSource:
    """从指定目录读取提示词，主要用于测试和本地调试。"""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def read(self, prompt_file: str) -> str:
        path = self.root / prompt_file
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise PromptTemplateError(f"找不到 Agent 提示词文件：{prompt_file}") from exc


class PromptRepository:
    """校验提示词文件并注入版本和结构化输出约束。"""

    def __init__(self, source: PromptSource | None = None) -> None:
        self.source = source or PackagePromptSource()

    def render(
        self,
        agent: AgentDefinition,
        output_schema: type[BaseModel],
    ) -> str:
        if not PROMPT_FILE_PATTERN.fullmatch(agent.prompt_file):
            raise PromptTemplateError(f"提示词文件名不合法：{agent.prompt_file}")
        template = self.source.read(agent.prompt_file).strip()
        missing = [
            placeholder
            for placeholder in (PROMPT_VERSION_PLACEHOLDER, OUTPUT_SCHEMA_PLACEHOLDER)
            if placeholder not in template
        ]
        if missing:
            raise PromptTemplateError(
                f"提示词文件 {agent.prompt_file} 缺少占位符：{'、'.join(missing)}"
            )
        schema = json.dumps(
            output_schema.model_json_schema(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return template.replace(
            PROMPT_VERSION_PLACEHOLDER,
            agent.prompt_version,
        ).replace(OUTPUT_SCHEMA_PLACEHOLDER, schema)
