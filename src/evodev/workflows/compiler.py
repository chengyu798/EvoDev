"""把业务工作流定义编译为可执行的 LangGraph。"""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from evodev.domain.workflows import WorkflowSpec
from evodev.workflows import nodes
from evodev.workflows.routers import (
    route_after_diagnosis,
    route_after_review,
    route_after_tests,
)
from evodev.workflows.specs import BUG_FIX_V1
from evodev.workflows.state import EvoDevState

NODE_REGISTRY = {
    "prepare_workspace": nodes.prepare_workspace,
    "run_baseline_tests": nodes.run_baseline_tests,
    "analyze_issue": nodes.analyze_issue,
    "implement_patch": nodes.implement_patch,
    "run_tests": nodes.run_tests,
    "diagnose_failure": nodes.diagnose_failure,
    "review_patch": nodes.review_patch,
    "final_evaluation": nodes.final_evaluation,
    "finalize_succeeded": nodes.finalize_succeeded,
    "finalize_failed": nodes.finalize_failed,
}

ROUTER_REGISTRY = {
    "route_after_tests": route_after_tests,
    "route_after_diagnosis": route_after_diagnosis,
    "route_after_review": route_after_review,
}


def compile_workflow(
    spec: WorkflowSpec,
    *,
    checkpointer: object | None = None,
    node_registry: dict[str, object] | None = None,
) -> CompiledStateGraph:
    """将 EvoDev 工作流定义编译为 LangGraph。"""
    builder = StateGraph(EvoDevState)
    registered_nodes = NODE_REGISTRY if node_registry is None else node_registry

    for node_name in spec.nodes:
        try:
            node = registered_nodes[node_name]
        except KeyError as exc:
            raise ValueError(f"工作流节点尚未注册：{node_name}") from exc
        builder.add_node(node_name, node)

    builder.add_edge(START, spec.entrypoint)
    for edge in spec.edges:
        builder.add_edge(edge.source, edge.target)

    for route in spec.routes:
        try:
            router = ROUTER_REGISTRY[route.router]
        except KeyError as exc:
            raise ValueError(f"工作流路由尚未注册：{route.router}") from exc
        builder.add_conditional_edges(
            route.source,
            router,
            {target: target for target in route.targets},
        )

    for node_name in spec.terminal_nodes:
        builder.add_edge(node_name, END)

    return builder.compile(checkpointer=checkpointer)


def build_bug_fix_graph(
    *,
    checkpointer: object | None = None,
    node_registry: dict[str, object] | None = None,
) -> CompiledStateGraph:
    return compile_workflow(
        BUG_FIX_V1,
        checkpointer=checkpointer,
        node_registry=node_registry,
    )
