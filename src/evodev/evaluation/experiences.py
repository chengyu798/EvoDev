"""从失败状态中生成经验，并为经验检索构建标签。"""

import re
from pathlib import Path
from uuid import UUID

from evodev.domain.experiences import Experience
from evodev.workflows.state import EvoDevState

TERM_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{1,39}")
FILE_PATTERN = re.compile(r"(?:[\w.-]+/)*[\w.-]+\.[a-zA-Z0-9]+")
CALL_PATTERN = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(")
FUNCTION_PATTERNS = (
    re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:函数|方法)"),
    re.compile(r"(?:函数|方法)\s*([a-zA-Z_][a-zA-Z0-9_]*)\b"),
)
IGNORED_TERMS = {
    "and",
    "bug",
    "code",
    "error",
    "fix",
    "for",
    "from",
    "pytest",
    "py",
    "project",
    "python",
    "test",
    "tests",
    "the",
    "with",
}
TECHNOLOGY_TERMS = {
    "async",
    "decimal",
    "docker",
    "fastapi",
    "json",
    "postgresql",
    "pydantic",
    "python",
    "regex",
    "sqlalchemy",
    "unicode",
}
ERROR_FEATURES = {
    "calculation": (
        "amount",
        "arithmetic",
        "calculator",
        "discount",
        "subtotal",
        "金额",
        "折扣",
        "计算",
    ),
    "text_normalization": (
        "normalize",
        "normalizer",
        "strip",
        "whitespace",
        "文本",
        "空白",
        "规范化",
    ),
    "boundary_condition": ("boundary", "threshold", "边界", "门槛", "阈值"),
    "exception_handling": ("exception", "raise", "异常", "报错"),
    "type_error": ("typeerror", "类型错误"),
    "async_context": ("async with", "异步上下文"),
}


def build_experience_tags(
    *,
    issue_title: str,
    issue_body: str,
    relevant_files: list[str] | None = None,
    task_type: str = "bug_fix",
) -> list[str]:
    """从任务文本和相关文件生成稳定、可解释的检索标签。"""
    text = f"{issue_title} {issue_body}".lower()
    tags = {f"task:{task_type}"}

    files = [*FILE_PATTERN.findall(text), *(relevant_files or [])]
    for file_name in files:
        path = Path(file_name)
        tags.add(f"file:{path.name.lower()}")
        if path.suffix:
            tags.add(f"ext:{path.suffix.lower().removeprefix('.')}")

    functions = set(CALL_PATTERN.findall(text))
    for pattern in FUNCTION_PATTERNS:
        functions.update(pattern.findall(text))
    tags.update(f"function:{name}" for name in functions if name not in IGNORED_TERMS)

    for feature, markers in ERROR_FEATURES.items():
        if any(marker in text for marker in markers):
            tags.add(f"error:{feature}")

    terms = TERM_PATTERN.findall(text)
    tags.update(f"tech:{term}" for term in terms if term in TECHNOLOGY_TERMS)
    for term in terms:
        if term not in IGNORED_TERMS and term not in TECHNOLOGY_TERMS:
            tags.add(f"term:{term}")

    priority = {"error": 0, "file": 1, "function": 2, "tech": 3, "term": 4, "task": 5, "ext": 6}
    return sorted(tags, key=lambda tag: (priority.get(tag.partition(":")[0], 7), tag))[:20]


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
