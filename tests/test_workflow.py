"""验证工作流成功、失败和非法节点三类路径。"""

import pytest

from evodev.domain.enums import TaskRunStatus
from evodev.domain.workflows import WorkflowEdge
from evodev.workflows.compiler import build_bug_fix_graph, compile_workflow
from evodev.workflows.specs import BUG_FIX_V1


def base_state() -> dict[str, object]:
    return {
        "run_id": "run-1",
        "task_id": "task-1",
        "status": TaskRunStatus.CREATED,
        "repository_path": ".",
        "issue_title": "示例问题",
        "issue_body": "修复示例缺陷。",
        "test_command": "pytest -q",
        "changed_files": [],
        "retrieved_experience_ids": [],
        "iteration": 0,
        "max_iterations": 3,
    }


def test_successful_workflow_reaches_succeeded() -> None:
    assert BUG_FIX_V1.limits.max_repair_iterations == 3
    graph = build_bug_fix_graph()
    state = base_state() | {"tests_passed": True, "review_passed": True}

    result = graph.invoke(state)

    assert result["status"] == TaskRunStatus.SUCCEEDED
    assert result["iteration"] == 1


def test_failed_workflow_stops_at_iteration_limit() -> None:
    graph = build_bug_fix_graph()
    state = base_state() | {"tests_passed": False, "review_passed": False}

    result = graph.invoke(state)

    assert result["status"] == TaskRunStatus.FAILED
    assert result["iteration"] == 3
    assert result["error_code"] == "REPAIR_LIMIT_REACHED"


def test_compiler_rejects_unregistered_node() -> None:
    invalid_spec = BUG_FIX_V1.model_copy(
        update={
            "nodes": [*BUG_FIX_V1.nodes, "unknown_node"],
            "edges": [
                *BUG_FIX_V1.edges,
                WorkflowEdge(source="prepare_workspace", target="unknown_node"),
            ],
        }
    )

    with pytest.raises(ValueError, match="尚未注册"):
        compile_workflow(invalid_spec)
