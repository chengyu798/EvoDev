"""从失败状态中生成经验，并为经验检索构建标签。"""

import re
from pathlib import Path
from uuid import UUID

from evodev.domain.experiences import Experience
from evodev.workflows.state import EvoDevState

TERM_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{1,39}")
IGNORED_TERMS = {
    "and",
    "bug",
    "error",
    "fix",
    "for",
    "from",
    "pytest",
    "test",
    "tests",
    "the",
    "with",
}


def build_experience_tags(
    *,
    issue_title: str,
    issue_body: str,
    relevant_files: list[str] | None = None,
    task_type: str = "bug_fix",
) -> list[str]:
    """从任务文本和相关文件生成稳定、可解释的检索标签。"""
    tags = {f"task:{task_type}"}
    for term in TERM_PATTERN.findall(f"{issue_title} {issue_body}".lower()):
        if term not in IGNORED_TERMS:
            tags.add(f"term:{term}")
    for file_name in relevant_files or []:
        path = Path(file_name)
        tags.add(f"file:{path.name.lower()}")
        if path.suffix:
            tags.add(f"ext:{path.suffix.lower().removeprefix('.')}")
    return sorted(tags)[:20]


def extract_failure_experience(state: EvoDevState) -> Experience:
    """利用已有失败诊断生成一条结构化经验，不再额外调用模型。"""
    failure = state.get("failure_analysis") or {}
    issue = state.get("issue_analysis") or {}
    failure_summary = str(
        failure.get("failure_summary")
        or state.get("error_message")
        or "自动修复达到次数上限后测试仍未通过"
    )
    root_cause = str(
        failure.get("root_cause")
        or issue.get("likely_root_cause")
        or "现有轨迹不足以确认根本原因，需要补充诊断"
    )
    suggested_changes = [str(item) for item in failure.get("suggested_changes", [])]
    if not suggested_changes:
        suggested_changes = ["先复现失败并核对最新测试日志，再缩小修改范围"]
    relevant_files = [str(item) for item in issue.get("relevant_files", [])]
    return Experience(
        source_run_id=UUID(state["run_id"]),
        tags=build_experience_tags(
            issue_title=state["issue_title"],
            issue_body=state["issue_body"],
            relevant_files=relevant_files,
        ),
        failure_pattern=failure_summary,
        lesson=f"本次修复未完成。失败诊断认为：{root_cause}",
        recommended_actions=suggested_changes,
    )
