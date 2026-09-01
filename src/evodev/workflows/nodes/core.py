"""定义工作流节点骨架；真实仓库和模型服务将在后续注入。"""

from evodev.domain.enums import TaskRunStatus
from evodev.workflows.state import EvoDevState


def prepare_workspace(_: EvoDevState) -> dict[str, object]:
    return {"status": TaskRunStatus.PREPARING}


def run_baseline_tests(_: EvoDevState) -> dict[str, object]:
    return {"status": TaskRunStatus.BASELINE_TESTING}


def analyze_issue(_: EvoDevState) -> dict[str, object]:
    return {"status": TaskRunStatus.ANALYZING}


def implement_patch(state: EvoDevState) -> dict[str, object]:
    return {
        "status": TaskRunStatus.IMPLEMENTING,
        "iteration": state.get("iteration", 0) + 1,
    }


def run_tests(_: EvoDevState) -> dict[str, object]:
    return {"status": TaskRunStatus.TESTING}


def diagnose_failure(_: EvoDevState) -> dict[str, object]:
    return {"status": TaskRunStatus.DEBUGGING}


def review_patch(_: EvoDevState) -> dict[str, object]:
    return {"status": TaskRunStatus.REVIEWING}


def final_evaluation(_: EvoDevState) -> dict[str, object]:
    return {"status": TaskRunStatus.FINALIZING}


def finalize_succeeded(_: EvoDevState) -> dict[str, object]:
    return {"status": TaskRunStatus.SUCCEEDED}


def finalize_failed(state: EvoDevState) -> dict[str, object]:
    return {
        "status": TaskRunStatus.FAILED,
        "error_code": state.get("error_code") or "REPAIR_LIMIT_REACHED",
        "error_message": state.get("error_message")
        or "自动修复次数已达到上限。",
    }
