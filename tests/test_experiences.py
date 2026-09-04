"""验证经验标签和失败轨迹提取。"""

from uuid import uuid4

from evodev.evaluation.experiences import (
    build_experience_tags,
    extract_failure_experience,
)


def test_build_experience_tags_uses_task_terms_and_files() -> None:
    tags = build_experience_tags(
        issue_title="Fix Calculator add",
        issue_body="calculator.py returns subtraction",
        relevant_files=["src/calculator.py"],
    )

    assert "task:bug_fix" in tags
    assert "term:calculator" in tags
    assert "term:add" in tags
    assert "file:calculator.py" in tags
    assert "ext:py" in tags


def test_extract_failure_experience_uses_structured_diagnosis() -> None:
    run_id = uuid4().hex
    experience = extract_failure_experience(
        {
            "run_id": run_id,
            "task_id": uuid4().hex,
            "status": "failed",
            "repository_path": "/tmp/demo",
            "issue_title": "修复 add",
            "issue_body": "结果错误",
            "test_command": "pytest -q",
            "max_iterations": 3,
            "changed_files": ["calculator.py"],
            "retrieved_experience_ids": [],
            "iteration": 3,
            "issue_analysis": {
                "likely_root_cause": "运算符错误",
                "relevant_files": ["calculator.py"],
            },
            "failure_analysis": {
                "failure_summary": "断言仍然失败",
                "root_cause": "边界条件遗漏",
                "suggested_changes": ["补充边界处理"],
            },
        }
    )

    assert experience.source_run_id.hex == run_id
    assert experience.failure_pattern == "断言仍然失败"
    assert experience.lesson.endswith("边界条件遗漏")
    assert experience.recommended_actions == ["补充边界处理"]
