from typing import Literal

from evodev.workflows.state import EvoDevState

TestRoute = Literal["review_patch", "diagnose_failure", "finalize_failed"]
ReviewRoute = Literal["final_evaluation", "implement_patch", "finalize_failed"]


def route_after_tests(state: EvoDevState) -> TestRoute:
    if state.get("tests_passed"):
        return "review_patch"
    if state.get("iteration", 0) < state["max_iterations"]:
        return "diagnose_failure"
    return "finalize_failed"


def route_after_review(state: EvoDevState) -> ReviewRoute:
    if state.get("review_passed"):
        return "final_evaluation"
    if state.get("iteration", 0) < state["max_iterations"]:
        return "implement_patch"
    return "finalize_failed"
