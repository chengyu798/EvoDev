"""验证智能体的工具权限、调用循环和结构化输出。"""

import json
from pathlib import Path

import pytest

from evodev.agents.client import ModelReply, ToolCall
from evodev.agents.executor import AgentExecutionError, AgentExecutor
from evodev.agents.prompting import PromptRepository, PromptTemplateError
from evodev.agents.schemas import IssueAnalysis
from evodev.agents.tools import AgentToolbox
from evodev.domain.agents import AgentDefinition
from evodev.tools.edit import EditTools
from evodev.tools.git import GitTools
from evodev.tools.repository import RepositoryTools


class ScriptedModelClient:
    """按顺序返回预设模型响应。"""

    def __init__(self, replies: list[ModelReply]) -> None:
        self.replies = replies
        self.messages: list[list[dict[str, object]]] = []

    def complete(self, **kwargs: object) -> ModelReply:
        self.messages.append(kwargs["messages"])  # type: ignore[arg-type]
        return self.replies.pop(0)


def analyst_definition(*, max_tool_calls: int = 2) -> AgentDefinition:
    return AgentDefinition(
        id="analyst@1",
        name="问题分析智能体",
        role="分析问题并给出修改计划。",
        prompt_file="analyst.md",
        model="test-model",
        allowed_tools=["list_files"],
        output_schema="IssueAnalysis",
        max_tool_calls=max_tool_calls,
    )


def valid_analysis_json() -> str:
    return json.dumps(
        {
            "problem_summary": "加法实现错误",
            "likely_root_cause": "使用了减法运算符",
            "relevant_files": ["calculator.py"],
            "implementation_steps": ["把减法改为加法"],
            "risks": [],
        },
        ensure_ascii=False,
    )


def test_agent_executes_allowed_tool_then_returns_structured_result(tmp_path: Path) -> None:
    (tmp_path / "calculator.py").write_text("def add(a, b): return a - b\n", encoding="utf-8")
    client = ScriptedModelClient(
        [
            ModelReply(
                content=None,
                tool_calls=[ToolCall(id="call-1", name="list_files", arguments={})],
                prompt_tokens=3,
                completion_tokens=2,
            ),
            ModelReply(content=valid_analysis_json(), prompt_tokens=4, completion_tokens=5),
        ]
    )
    toolbox = AgentToolbox(RepositoryTools(), EditTools(), GitTools())

    invocation = AgentExecutor(client, toolbox).invoke(
        agent=analyst_definition(),
        workspace=tmp_path,
        task={"issue_title": "修复加法"},
        output_schema=IssueAnalysis,
    )

    assert isinstance(invocation.output, IssueAnalysis)
    assert invocation.output.relevant_files == ["calculator.py"]
    assert invocation.tool_calls == [
        {
            "tool": "list_files",
            "arguments": {},
            "result": '["calculator.py"]',
            "succeeded": True,
        }
    ]
    assert invocation.prompt_tokens == 7
    assert invocation.completion_tokens == 7
    assert client.messages[1][-1]["role"] == "tool"
    assert "问题分析智能体" in client.messages[0][0]["content"]
    assert "Prompt 版本：1" in client.messages[0][0]["content"]
    assert "JSON Schema" in client.messages[0][0]["content"]


def test_agent_rejects_invalid_structured_output(tmp_path: Path) -> None:
    client = ScriptedModelClient(
        [
            ModelReply(content='{"problem_summary": "不完整"}'),
            ModelReply(content='{"problem_summary": "仍不完整"}'),
        ]
    )
    toolbox = AgentToolbox(RepositoryTools(), EditTools(), GitTools())

    with pytest.raises(AgentExecutionError, match="结构化输出"):
        AgentExecutor(client, toolbox).invoke(
            agent=analyst_definition(),
            workspace=tmp_path,
            task={"issue_title": "修复加法"},
            output_schema=IssueAnalysis,
        )


def test_agent_asks_model_to_correct_invalid_structured_output(tmp_path: Path) -> None:
    client = ScriptedModelClient(
        [
            ModelReply(
                content='{"problem_summary": "不完整"}',
                prompt_tokens=2,
                completion_tokens=1,
            ),
            ModelReply(
                content=valid_analysis_json(),
                prompt_tokens=3,
                completion_tokens=4,
            ),
        ]
    )
    toolbox = AgentToolbox(RepositoryTools(), EditTools(), GitTools())

    invocation = AgentExecutor(client, toolbox).invoke(
        agent=analyst_definition(),
        workspace=tmp_path,
        task={"issue_title": "修复加法"},
        output_schema=IssueAnalysis,
    )

    assert invocation.output.problem_summary == "加法实现错误"
    assert invocation.prompt_tokens == 5
    assert invocation.completion_tokens == 5
    assert "不符合指定 JSON Schema" in client.messages[1][-1]["content"]
    assert "implementation_steps" in client.messages[1][-1]["content"]


def test_all_agent_prompts_are_loaded_from_independent_files() -> None:
    from evodev.agents.catalog import default_agent_catalog

    repository = PromptRepository()
    prompts = {
        name: repository.render(agent, IssueAnalysis)
        for name, agent in default_agent_catalog("test-model").items()
    }

    assert len(set(prompts.values())) == 5
    assert "只负责分析" in prompts["analyst"]
    assert "必须使用 apply_patch" in prompts["developer"]
    assert "是否适合自动重试" in prompts["failure_analyzer"]
    assert "判断补丁是否可以通过审查" in prompts["reviewer"]
    assert "Prompt 优化智能体" in prompts["prompt_optimizer"]


def test_prompt_repository_appends_active_evolution_guidance() -> None:
    class GuidanceProvider:
        def get_active_guidance(self, agent_role: str) -> tuple[str, str] | None:
            if agent_role == "analyst":
                return "先验证历史经验是否适用于当前代码。", "1+e2"
            return None

    rendered = PromptRepository(
        guidance_provider=GuidanceProvider()
    ).render_with_version(analyst_definition(), IssueAnalysis)

    assert "已通过评测的进化指导" in rendered.content
    assert "先验证历史经验" in rendered.content
    assert rendered.effective_version == "1+e2"


def test_agent_rejects_unsafe_prompt_file_name() -> None:
    agent = analyst_definition()
    agent.prompt_file = "../secret.md"

    with pytest.raises(PromptTemplateError, match="文件名不合法"):
        PromptRepository().render(agent, IssueAnalysis)


def test_agent_stops_at_tool_call_limit(tmp_path: Path) -> None:
    client = ScriptedModelClient(
        [
            ModelReply(
                content=None,
                tool_calls=[ToolCall(id="call-1", name="list_files", arguments={})],
            ),
            ModelReply(
                content=None,
                tool_calls=[ToolCall(id="call-2", name="list_files", arguments={})],
            ),
        ]
    )
    toolbox = AgentToolbox(RepositoryTools(), EditTools(), GitTools())

    with pytest.raises(AgentExecutionError, match="达到上限"):
        AgentExecutor(client, toolbox).invoke(
            agent=analyst_definition(max_tool_calls=1),
            workspace=tmp_path,
            task={"issue_title": "修复加法"},
            output_schema=IssueAnalysis,
        )


def test_agent_can_correct_invalid_tool_input(tmp_path: Path) -> None:
    client = ScriptedModelClient(
        [
            ModelReply(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="apply_patch",
                        arguments={"patch": "这不是标准 Git Diff"},
                    )
                ],
            ),
            ModelReply(content=valid_analysis_json()),
        ]
    )
    toolbox = AgentToolbox(RepositoryTools(), EditTools(), GitTools())
    agent = analyst_definition()
    agent.allowed_tools = ["apply_patch"]

    invocation = AgentExecutor(client, toolbox).invoke(
        agent=agent,
        workspace=tmp_path,
        task={"issue_title": "修复加法"},
        output_schema=IssueAnalysis,
    )

    assert isinstance(invocation.output, IssueAnalysis)
    assert invocation.tool_calls[0]["succeeded"] is False
    assert "No valid patches" in str(invocation.tool_calls[0]["result"])
    assert "工具执行失败" in client.messages[1][-1]["content"]
