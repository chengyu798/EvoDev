"""验证经验对照实验的输入冻结与指标汇总。"""

import json
from pathlib import Path
from uuid import uuid4

from evodev.domain.experiences import Experience
from evodev.evaluation.comparison import load_inputs, summarize


def test_summarize_keeps_failures_and_missing_metrics() -> None:
    rows = [
        {
            "variant": "baseline",
            "status": "succeeded",
            "tests_passed": True,
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "retry_count": 0,
            "duration_ms": 20,
        },
        {
            "variant": "baseline",
            "status": "failed",
            "tests_passed": False,
            "prompt_tokens": None,
            "completion_tokens": None,
            "retry_count": None,
            "duration_ms": None,
        },
        {
            "variant": "experience",
            "status": "succeeded",
            "tests_passed": True,
            "prompt_tokens": 8,
            "completion_tokens": 2,
            "retry_count": 0,
            "duration_ms": 18,
        },
    ]

    summary = summarize(rows)

    assert summary["baseline"]["task_success_rate"] == 0.5
    assert summary["baseline"]["total_prompt_tokens"] is None
    assert summary["experience"]["task_success_rate"] == 1


def test_load_inputs_requires_distinct_cases_and_active_experience(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    benchmark_file = tmp_path / "benchmarks.json"
    benchmark_file.write_text(
        json.dumps(
            [
                {
                    "name": "第一个缺陷",
                    "source_directory": "first",
                    "issue_title": "修复第一个缺陷",
                    "issue_body": "修复具体行为。",
                    "test_command": "pytest -q",
                    "max_iterations": 3,
                },
                {
                    "name": "第二个缺陷",
                    "source_directory": "second",
                    "issue_title": "修复第二个缺陷",
                    "issue_body": "修复另一个具体行为。",
                    "test_command": "pytest -q",
                    "max_iterations": 3,
                },
            ]
        ),
        encoding="utf-8",
    )
    experience_file = tmp_path / "experience.json"
    experience_file.write_text(
        Experience(
            source_run_id=uuid4(),
            tags=["task:bug_fix"],
            failure_pattern="测试失败",
            lesson="先定位根因",
            recommended_actions=["读取相关实现"],
        ).model_dump_json(),
        encoding="utf-8",
    )

    cases, experiences = load_inputs(benchmark_file, experience_file)

    assert [case.source_directory for case in cases] == [first, second]
    assert len(experiences) == 1
