"""提供系统默认的智能体角色和工具权限。"""

from evodev.domain.agents import AgentDefinition


def default_agent_catalog(model: str) -> dict[str, AgentDefinition]:
    return {
        "analyst": AgentDefinition(
            id="analyst@1",
            name="问题分析智能体",
            role="结合问题描述和仓库内容生成修改计划。",
            prompt_file="analyst.md",
            prompt_version="4",
            model=model,
            allowed_tools=["list_files", "read_file", "search_text", "git_diff"],
            output_schema="IssueAnalysis",
        ),
        "conversation": AgentDefinition(
            id="conversation@1",
            name="对话智能体",
            role="基于会话和仓库事实回答问题，并保守判断用户是否明确要求修改代码。",
            prompt_file="conversation.md",
            prompt_version="2",
            model=model,
            allowed_tools=["list_files", "read_file", "search_text", "git_diff"],
            output_schema="ConversationReply",
            max_tool_calls=10,
        ),
        "developer": AgentDefinition(
            id="developer@1",
            name="代码开发智能体",
            role=(
                "通过受控仓库工具实现范围最小的正确补丁。必须使用 apply_patch 工具实际"
                "应用修改，并根据工具错误修正补丁，最后使用测试和 Git Diff 验证结果。"
            ),
            prompt_file="developer.md",
            prompt_version="3",
            model=model,
            allowed_tools=[
                "list_files",
                "read_file",
                "search_text",
                "apply_patch",
                "git_diff",
                "run_command",
            ],
            output_schema="ImplementationResult",
        ),
        "failure_analyzer": AgentDefinition(
            id="failure-analyzer@1",
            name="失败分析智能体",
            role="解释测试失败原因并给出针对性的修复建议。",
            prompt_file="failure_analyzer.md",
            prompt_version="2",
            model=model,
            allowed_tools=["read_file", "search_text", "git_diff"],
            output_schema="FailureAnalysis",
        ),
        "reviewer": AgentDefinition(
            id="reviewer@1",
            name="代码审查智能体",
            role="检查需求覆盖、补丁范围、测试情况和回归风险。",
            prompt_file="reviewer.md",
            prompt_version="2",
            model=model,
            allowed_tools=["read_file", "search_text", "git_diff"],
            output_schema="ReviewResult",
        ),
        "prompt_optimizer": AgentDefinition(
            id="prompt-optimizer@1",
            name="提示词优化智能体",
            role="从带真实反馈的经验中生成受限的候选 Prompt 指导层。",
            prompt_file="prompt_optimizer.md",
            prompt_version="1",
            model=model,
            allowed_tools=[],
            output_schema="PromptOptimization",
            max_tool_calls=2,
        ),
    }
