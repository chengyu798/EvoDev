"""执行带工具权限和结构化输出约束的智能体。"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from evodev.agents.client import ModelClientProtocol
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
    agent_id: str = ""
    model: str = ""
    prompt_version: str = ""


class AgentExecutor:
    """循环处理模型工具请求，直到模型返回结构化结果。"""

    def __init__(self, client: ModelClientProtocol, toolbox: AgentToolbox) -> None:
        self.client = client
        self.toolbox = toolbox

    def invoke(
        self,
        *,
        agent: AgentDefinition,
        workspace: Path,
        task: dict[str, object],
        output_schema: type[OutputT],
    ) -> AgentInvocation:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self._system_prompt(agent, output_schema),
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
                output = self._validate_output(reply.content, output_schema)
                return AgentInvocation(
                    output=output,
                    tool_calls=trace,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    agent_id=agent.id,
                    model=agent.model,
                    prompt_version=agent.prompt_version,
                )

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
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result,
                    }
                )
        raise AgentExecutionError("Agent 未在限制内返回最终结果")

    @staticmethod
    def _system_prompt(agent: AgentDefinition, output_schema: type[BaseModel]) -> str:
        schema = json.dumps(output_schema.model_json_schema(), ensure_ascii=False)
        return (
            f"你是 EvoDev 的{agent.name}。{agent.role}\n"
            "只能使用已授权工具，不得访问工作区以外的文件。"
            "如果工具返回执行失败，必须根据错误信息修正参数后重试。"
            "完成任务后必须返回符合给定 JSON Schema 的 JSON，不要添加 Markdown。\n"
            f"Prompt 版本：{agent.prompt_version}\nJSON Schema：{schema}"
        )

    @staticmethod
    def _validate_output(content: str | None, schema: type[OutputT]) -> OutputT:
        if not content:
            raise AgentExecutionError("Agent 没有返回最终结果")
        try:
            return schema.model_validate_json(content)
        except ValidationError as exc:
            raise AgentExecutionError("Agent 返回结果不符合结构化输出要求") from exc
