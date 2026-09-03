"""定义各智能体必须返回的结构化结果。"""

from pydantic import BaseModel, Field


class IssueAnalysis(BaseModel):
    """问题分析智能体给出的定位和实施计划。"""

    problem_summary: str = Field(min_length=1)
    likely_root_cause: str = Field(min_length=1)
    relevant_files: list[str] = Field(default_factory=list)
    implementation_steps: list[str] = Field(min_length=1)
    risks: list[str] = Field(default_factory=list)


class ImplementationResult(BaseModel):
    """代码开发智能体完成一次修改后的结果。"""

    summary: str = Field(min_length=1)
    changed_files: list[str] = Field(default_factory=list)
    patch: str | None = None


class FailureAnalysis(BaseModel):
    """失败分析智能体对测试失败的诊断。"""

    failure_summary: str = Field(min_length=1)
    root_cause: str = Field(min_length=1)
    suggested_changes: list[str] = Field(min_length=1)
    retryable: bool = True


class ReviewResult(BaseModel):
    """代码审查智能体对当前补丁的检查结论。"""

    passed: bool
    summary: str = Field(min_length=1)
    requirement_coverage: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)
