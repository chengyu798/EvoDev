"""封装大模型调用，避免工作流依赖具体服务商。"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

from evodev.domain.agents import AgentDefinition


@dataclass(frozen=True, slots=True)
class ToolCall:
    """大模型请求执行的一次工具调用。"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ModelReply:
    """统一后的模型响应。"""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ModelClientProtocol(Protocol):
    """Agent 执行器需要的最小模型接口。"""

    def complete(
        self,
        *,
        agent: AgentDefinition,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        output_schema: type[BaseModel],
        on_delta: Callable[[str], None] | None = None,
    ) -> ModelReply: ...


class ModelResponseError(RuntimeError):
    """模型响应缺少必要内容或包含非法工具参数。"""


class LiteLLMClient:
    """通过 LiteLLM 调用 OpenAI 兼容或其他模型服务。"""

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url

    def complete(
        self,
        *,
        agent: AgentDefinition,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        output_schema: type[BaseModel],
        on_delta: Callable[[str], None] | None = None,
    ) -> ModelReply:
        # 延迟导入可避免不执行模型任务的命令产生网络初始化开销。
        from litellm import completion, stream_chunk_builder

        chunks = []
        response_stream = completion(
            model=agent.model,
            messages=messages,
            tools=tools or None,
            temperature=agent.temperature,
            timeout=agent.timeout_seconds,
            api_key=self.api_key,
            base_url=self.base_url,
            # DeepSeek Chat Completions 使用 json_object，具体字段继续由 Pydantic 校验。
            response_format={"type": "json_object"},
            stream=True,
        )
        for chunk in response_stream:
            chunks.append(chunk)
            if on_delta is None or not chunk.choices:
                continue
            content = getattr(chunk.choices[0].delta, "content", None)
            if isinstance(content, str) and content:
                on_delta(content)
        response = stream_chunk_builder(chunks=chunks, messages=messages)
        if response is None:
            raise ModelResponseError("模型流式响应为空")
        message = response.choices[0].message
        tool_calls = [self._parse_tool_call(item) for item in message.tool_calls or []]
        usage = response.usage
        return ModelReply(
            content=message.content,
            tool_calls=tool_calls,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )

    @staticmethod
    def _parse_tool_call(raw_call: Any) -> ToolCall:
        try:
            arguments = json.loads(raw_call.function.arguments)
        except (AttributeError, TypeError, json.JSONDecodeError) as exc:
            raise ModelResponseError("模型返回了无法解析的工具参数") from exc
        if not isinstance(arguments, dict):
            raise ModelResponseError("模型工具参数必须是 JSON 对象")
        return ToolCall(
            id=raw_call.id,
            name=raw_call.function.name,
            arguments=arguments,
        )
