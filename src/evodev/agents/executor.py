"""执行带工具权限和结构化输出约束的智能体。"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from evodev.agents.client import ModelClientProtocol
from evodev.agents.prompting import PromptRepository
from evodev.agents.tools import AgentToolbox
from evodev.domain.agents import AgentDefinition

OutputT = TypeVar("OutputT", bound=BaseModel)


class JsonStringFieldStreamer:
    """从分块 JSON 中提取一个字符串字段，避免把 JSON 语法推送给调用方。"""

    def __init__(self, field: str, on_delta: Callable[[str], None]) -> None:
        self.marker = f'"{field}"'
        self.on_delta = on_delta
        self.buffer = ""
        self.started = False
        self.finished = False
        self.escaped = False
        self.unicode_escape = ""

    def feed(self, chunk: str) -> None:
        if self.finished:
            return
        self.buffer += chunk
        if not self.started:
            marker_index = self.buffer.find(self.marker)
            if marker_index < 0:
                self.buffer = self.buffer[-len(self.marker) :]
                return
            colon_index = self.buffer.find(":", marker_index + len(self.marker))
            quote_index = self.buffer.find('"', colon_index + 1) if colon_index >= 0 else -1
            if quote_index < 0:
                self.buffer = self.buffer[marker_index:]
                return
            self.started = True
            self.buffer = self.buffer[quote_index + 1 :]
        self._flush_value()

    def _flush_value(self) -> None:
        output: list[str] = []
        consumed = 0
        for index, character in enumerate(self.buffer):
            consumed = index + 1
            if self.unicode_escape:
                self.unicode_escape += character
                if len(self.unicode_escape) == 5:
                    try:
                        output.append(chr(int(self.unicode_escape[1:], 16)))
                    except ValueError:
                        output.append(self.unicode_escape)
                    self.unicode_escape = ""
                    self.escaped = False
                continue
            if self.escaped:
                if character == "u":
                    self.unicode_escape = "u"
                    continue
                output.append({"n": "\n", "r": "\r", "t": "\t"}.get(character, character))
                self.escaped = False
                continue
            if character == "\\":
                self.escaped = True
                continue
            if character == '"':
                self.finished = True
                break
            output.append(character)
        self.buffer = self.buffer[consumed:]
        if output:
            self.on_delta("".join(output))


class AgentExecutionError(RuntimeError):
    """智能体未能在限制内生成合法结果。"""


@dataclass(frozen=True, slots=True)
class AgentInvocation:
    """一次智能体调用的结果和可观测指标。"""

    output: BaseModel
    tool_calls: list[dict[str, object]]
    prompt_tokens: int
    completion_tokens: int
    duration_ms: int = 0
    agent_id: str = ""
    model: str = ""
    prompt_version: str = ""


class AgentExecutor:
    """循环处理模型工具请求，直到模型返回结构化结果。"""

    def __init__(
        self,
        client: ModelClientProtocol,
        toolbox: AgentToolbox,
        prompt_repository: PromptRepository | None = None,
        event_callback: Callable[[str, dict[str, object]], None] | None = None,
    ) -> None:
        self.client = client
        self.toolbox = toolbox
        self.prompt_repository = prompt_repository or PromptRepository()
        self.event_callback = event_callback

    def invoke(
        self,
        *,
        agent: AgentDefinition,
        workspace: Path,
        task: dict[str, object],
        output_schema: type[OutputT],
        output_delta_callback: Callable[[str], None] | None = None,
    ) -> AgentInvocation:
        started_at = time.perf_counter()
        self._emit("agent.started", {"agent_id": agent.id, "agent_name": agent.name})
        rendered_prompt = self.prompt_repository.render_with_version(agent, output_schema)
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": rendered_prompt.content,
            },
            {
                "role": "user",
                "content": json.dumps(task, ensure_ascii=False, default=str),
            },
        ]
        tools = self.toolbox.definitions(agent.allowed_tools)
        trace: list[dict[str, object]] = []
        prompt_tokens = 0
        completion_tokens = 0
        output_repair_attempted = False
        stream_field = {
            "conversation": "response",
            "reviewer": "summary",
        }.get(agent.id.split("@", maxsplit=1)[0])

        for _ in range(agent.max_tool_calls + 1):

            def emit_output_delta(delta: str) -> None:
                self._emit(
                    "agent.output.delta",
                    {
                        "agent_id": agent.id,
                        "agent_name": agent.name,
                        "field": stream_field or "",
                        "delta": delta,
                    },
                )
                if output_delta_callback is not None:
                    output_delta_callback(delta)

            field_streamer = (
                JsonStringFieldStreamer(
                    stream_field,
                    emit_output_delta,
                )
                if stream_field
                and (self.event_callback is not None or output_delta_callback is not None)
                else None
            )
            reply = self.client.complete(
                agent=agent,
                messages=messages,
                tools=tools,
                output_schema=output_schema,
                on_delta=field_streamer.feed if field_streamer else None,
            )
            prompt_tokens += reply.prompt_tokens
            completion_tokens += reply.completion_tokens
            if not reply.tool_calls:
                try:
                    output = self._validate_output(reply.content, output_schema)
                except AgentExecutionError as exc:
                    if output_repair_attempted:
                        raise
                    output_repair_attempted = True
                    messages.extend(
                        [
                            {"role": "assistant", "content": reply.content or ""},
                            {
                                "role": "user",
                                "content": (
                                    "上一条最终结果不符合指定 JSON Schema。请保留原结论，"
                                    "修正缺失字段或字段类型，只返回合法 JSON，不要调用工具。"
                                    f"校验错误：{exc}"
                                ),
                            },
                        ]
                    )
                    continue
                invocation = AgentInvocation(
                    output=output,
                    tool_calls=trace,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                    agent_id=agent.id,
                    model=agent.model,
                    prompt_version=rendered_prompt.effective_version,
                )
                self._emit(
                    "agent.completed",
                    {
                        "agent_id": agent.id,
                        "agent_name": agent.name,
                        "duration_ms": invocation.duration_ms,
                    },
                )
                return invocation

            messages.append(
                {
                    "role": "assistant",
                    "content": reply.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments, ensure_ascii=False),
                            },
                        }
                        for call in reply.tool_calls
                    ],
                }
            )
            for call in reply.tool_calls:
                if len(trace) >= agent.max_tool_calls:
                    raise AgentExecutionError("Agent 工具调用次数已达到上限")
                self._emit(
                    "tool.started",
                    {
                        "agent_id": agent.id,
                        "agent_name": agent.name,
                        "tool": call.name,
                        "arguments": call.arguments,
                    },
                )
                try:
                    result = self.toolbox.execute(
                        workspace=workspace,
                        allowed_tools=agent.allowed_tools,
                        name=call.name,
                        arguments=call.arguments,
                    )
                    succeeded = True
                except Exception as exc:
                    # 工具输入错误应反馈给模型纠正，不应直接终止整个工作流。
                    result = f"工具执行失败：{exc}"
                    succeeded = False
                trace.append(
                    {
                        "tool": call.name,
                        "arguments": call.arguments,
                        "result": result,
                        "succeeded": succeeded,
                    }
                )
                self._emit(
                    "tool.completed",
                    {
                        "agent_id": agent.id,
                        "agent_name": agent.name,
                        "tool": call.name,
                        "succeeded": succeeded,
                    },
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result,
                    }
                )
        raise AgentExecutionError("Agent 未在限制内返回最终结果")

    def _emit(self, event_type: str, payload: dict[str, object]) -> None:
        """向运行服务发送不包含内部思维过程的结构化事件。"""
        if self.event_callback is not None:
            self.event_callback(event_type, payload)

    @staticmethod
    def _validate_output(content: str | None, schema: type[OutputT]) -> OutputT:
        if not content:
            raise AgentExecutionError("Agent 没有返回最终结果")
        try:
            return schema.model_validate_json(content)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(item) for item in error['loc']) or '根对象'}：{error['msg']}"
                for error in exc.errors(include_url=False, include_input=False)
            )
            raise AgentExecutionError(f"Agent 返回结果不符合结构化输出要求：{details}") from exc
