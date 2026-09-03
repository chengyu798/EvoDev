"""定义 LangGraph 节点之间传递的精简运行状态。"""

from typing import NotRequired, TypedDict


class EvoDevState(TypedDict):
    run_id: str
    task_id: str
    status: str

    repository_path: str
    issue_title: str
    issue_body: str
    test_command: str
    max_iterations: int

    workspace_path: NotRequired[str | None]
    base_commit: NotRequired[str | None]
    repository_summary: NotRequired[dict[str, object] | None]
    issue_analysis: NotRequired[dict[str, object] | None]
    implementation_plan: NotRequired[dict[str, object] | None]
    failure_analysis: NotRequired[dict[str, object] | None]
    review_result: NotRequired[dict[str, object] | None]

    # 状态只保存产物引用，完整日志、代码差异和测试输出由产物仓库管理。
    baseline_result_id: NotRequired[str | None]
    test_result_id: NotRequired[str | None]
    patch_artifact_id: NotRequired[str | None]
    evaluation_result_id: NotRequired[str | None]
    agent_invocation_ids: NotRequired[list[str]]

    changed_files: list[str]
    retrieved_experience_ids: list[str]
    iteration: int
    tests_passed: NotRequired[bool | None]
    baseline_passed: NotRequired[bool | None]
    failure_retryable: NotRequired[bool | None]
    review_passed: NotRequired[bool | None]
    prompt_tokens: NotRequired[int]
    completion_tokens: NotRequired[int]
    error_code: NotRequired[str | None]
    error_message: NotRequired[str | None]
