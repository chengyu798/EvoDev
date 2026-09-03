"""提供系统默认的智能体角色和工具权限。"""

from evodev.domain.agents import AgentDefinition


def default_agent_catalog(model: str) -> dict[str, AgentDefinition]:
    return {
        "analyst": AgentDefinition(
            id="analyst@1",
            name="问题分析智能体",
            role="结合问题描述和仓库内容生成修改计划。",
            model=model,
            allowed_tools=["list_files", "read_file", "search_text", "git_diff"],
            output_schema="IssueAnalysis",
        ),
        "developer": AgentDefinition(
            id="developer@1",
            name="代码开发智能体",
            role=(
                "通过受控仓库工具实现范围最小的正确补丁。必须使用 apply_patch 工具实际"
                "应用修改，并根据工具错误修正补丁，最后使用测试和 Git Diff 验证结果。"
            ),
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
            model=model,
            allowed_tools=["read_file", "search_text", "git_diff"],
            output_schema="FailureAnalysis",
        ),
        "reviewer": AgentDefinition(
            id="reviewer@1",
            name="代码审查智能体",
            role="检查需求覆盖、补丁范围、测试情况和回归风险。",
            model=model,
            allowed_tools=["read_file", "search_text", "git_diff"],
            output_schema="ReviewResult",
        ),
    }
