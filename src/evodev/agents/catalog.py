from evodev.domain.agents import AgentDefinition


def default_agent_catalog(model: str) -> dict[str, AgentDefinition]:
    return {
        "analyst": AgentDefinition(
            id="analyst@1",
            name="Analyst",
            role="Analyze the issue and produce a repository-grounded implementation plan.",
            model=model,
            allowed_tools=["list_files", "read_file", "search_text", "git_diff"],
            output_schema="IssueAnalysis",
        ),
        "developer": AgentDefinition(
            id="developer@1",
            name="Developer",
            role="Implement the smallest correct patch using controlled repository tools.",
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
            name="Failure Analyzer",
            role="Explain test failures and recommend a targeted repair.",
            model=model,
            allowed_tools=["read_file", "search_text", "git_diff"],
            output_schema="FailureAnalysis",
        ),
        "reviewer": AgentDefinition(
            id="reviewer@1",
            name="Reviewer",
            role="Review requirement coverage, patch scope, tests, and regression risk.",
            model=model,
            allowed_tools=["read_file", "search_text", "git_diff"],
            output_schema="ReviewResult",
        ),
    }
