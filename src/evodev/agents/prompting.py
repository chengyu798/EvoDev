"""加载并渲染独立维护的 Agent 系统提示词。"""

import json
import re
from dataclasses import dataclass
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


class PromptGuidanceProvider(Protocol):
    """提供已经通过评测的进化指导层。"""

    def get_active_guidance(self, agent_role: str) -> tuple[str, str] | None: ...


@dataclass(frozen=True, slots=True)
class RenderedPrompt:
    content: str
    effective_version: str


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

    def __init__(
        self,
        source: PromptSource | None = None,
        guidance_provider: PromptGuidanceProvider | None = None,
        guidance_overrides: dict[str, tuple[str, str]] | None = None,
        guidance_roles: tuple[str, ...] = ("analyst", "developer"),
    ) -> None:
        self.source = source or PackagePromptSource()
        self.guidance_overrides = guidance_overrides or {}
        if guidance_provider is not None:
            # 创建一次服务时快照全部可进化角色，防止运行中途切换 Prompt。
            for agent_role in guidance_roles:
                guidance = guidance_provider.get_active_guidance(agent_role)
                if guidance is not None:
                    self.guidance_overrides.setdefault(agent_role, guidance)

    def render(
        self,
        agent: AgentDefinition,
        output_schema: type[BaseModel],
    ) -> str:
        return self.render_with_version(agent, output_schema).content

    def render_with_version(
        self,
        agent: AgentDefinition,
        output_schema: type[BaseModel],
    ) -> RenderedPrompt:
        """渲染固定模板，并附加已激活或显式指定的指导层。"""
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
        content = template.replace(
            PROMPT_VERSION_PLACEHOLDER,
            agent.prompt_version,
        ).replace(OUTPUT_SCHEMA_PLACEHOLDER, schema)
        agent_role = agent.id.partition("@")[0]
        guidance = self.guidance_overrides.get(agent_role)
        if guidance is None:
            return RenderedPrompt(content, agent.prompt_version)
        guidance_content, effective_version = guidance
        return RenderedPrompt(
            f"{content}\n\n已通过评测的进化指导：\n{guidance_content.strip()}",
            effective_version,
        )
