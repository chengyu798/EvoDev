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

        for _ in range(agent.max_tool_calls + 1):
            reply = self.client.complete(
                agent=agent,
                messages=messages,
                tools=tools,
                output_schema=output_schema,
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
