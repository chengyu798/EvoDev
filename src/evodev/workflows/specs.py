from evodev.domain.workflows import (
    WorkflowEdge,
    WorkflowLimits,
    WorkflowRoute,
    WorkflowSpec,
)

BUG_FIX_V1 = WorkflowSpec(
    id="bug_fix",
    version=1,
    entrypoint="prepare_workspace",
    nodes=[
        "prepare_workspace",
        "run_baseline_tests",
        "analyze_issue",
        "implement_patch",
        "run_tests",
        "diagnose_failure",
        "review_patch",
        "final_evaluation",
        "finalize_succeeded",
        "finalize_failed",
    ],
    edges=[
        WorkflowEdge(source="prepare_workspace", target="run_baseline_tests"),
        WorkflowEdge(source="run_baseline_tests", target="analyze_issue"),
        WorkflowEdge(source="analyze_issue", target="implement_patch"),
        WorkflowEdge(source="implement_patch", target="run_tests"),
        WorkflowEdge(source="diagnose_failure", target="implement_patch"),
        WorkflowEdge(source="final_evaluation", target="finalize_succeeded"),
    ],
    routes=[
        WorkflowRoute(
            source="run_tests",
            router="route_after_tests",
            targets=["review_patch", "diagnose_failure", "finalize_failed"],
        ),
        WorkflowRoute(
            source="review_patch",
            router="route_after_review",
            targets=["final_evaluation", "implement_patch", "finalize_failed"],
        ),
    ],
    terminal_nodes=["finalize_succeeded", "finalize_failed"],
    limits=WorkflowLimits(max_repair_iterations=2, max_review_iterations=1),
)
