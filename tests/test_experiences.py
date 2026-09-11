"""验证经验标签和失败轨迹提取。"""

from uuid import uuid4

import pytest

from evodev.domain.experiences import Experience
from evodev.evaluation.experiences import (
    build_experience_tags,
    extract_failure_experience,
)
from evodev.evaluation.retrieval import (
    MINIMUM_MATCH_SCORE,
    rank_experience_matches,
    score_experience_match,
)


def test_build_experience_tags_uses_task_terms_and_files() -> None:
    tags = build_experience_tags(
        issue_title="Fix Calculator add() 函数",
        issue_body="calculator.py returns subtraction",
        relevant_files=["src/calculator.py"],
    )

    assert "task:bug_fix" in tags
    assert "term:calculator" in tags
    assert "term:add" in tags
    assert "function:add" in tags
    assert "file:calculator.py" in tags
    assert "ext:py" in tags
    assert "error:calculation" in tags


def test_calculator_experience_matches_calculator_task() -> None:
    experience = _experience(
        tags=[
            "task:bug_fix",
            "error:calculation",
            "file:calculator.py",
            "function:add",
            "ext:py",
        ]
    )
    query_tags = build_experience_tags(
        issue_title="修复 add 函数的计算错误",
        issue_body="calculator.py 应返回两数之和",
    )

    match = score_experience_match(experience, query_tags)

    assert match is not None
    assert match.score >= MINIMUM_MATCH_SCORE
    assert "function:add" in match.matched_tags
    assert "函数名匹配：add" in match.reasons


def test_generic_tags_do_not_match_unrelated_text_task() -> None:
    calculator = _experience(
        tags=["task:bug_fix", "ext:py", "term:py", "term:calculator"]
    )
    query_tags = build_experience_tags(
        issue_title="修复文本规范化",
        issue_body="normalizer.py 没有正确清理空白字符",
    )

    assert score_experience_match(calculator, query_tags) is None


def test_search_returns_empty_when_no_features_overlap() -> None:
    calculator = _experience(tags=["error:calculation", "file:calculator.py"])

    assert rank_experience_matches([calculator], ["tech:async"]) == []


def test_low_quality_experience_is_downranked() -> None:
    low_quality = _experience(tags=["function:add"], quality_score=0.2)
    high_quality = _experience(tags=["function:add"], quality_score=0.9)

    matches = rank_experience_matches(
        [low_quality, high_quality],
        ["function:add"],
    )

    assert [match.experience.id for match in matches] == [high_quality.id]
    assert matches[0].score == pytest.approx(4.2)


def _experience(*, tags: list[str], quality_score: float = 0.5) -> Experience:
    return Experience(
        source_run_id=uuid4(),
        tags=tags,
        failure_pattern="历史测试失败",
        lesson="先核对对应实现",
        quality_score=quality_score,
    )


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
