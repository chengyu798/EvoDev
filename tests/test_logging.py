"""验证终端日志级别和 CLI 结果摘要。"""

from pathlib import Path

import structlog

from evodev.cli.app import format_repair_summary
from evodev.observability.logging import configure_logging


def test_default_logging_shows_progress_and_hides_debug(capsys) -> None:
    try:
        configure_logging()
        logger = structlog.get_logger("test")

        logger.info("问题分析智能体正在分析问题")
        logger.debug("Docker 命令开始", container="evodev-test")

        output = capsys.readouterr().err
        assert "[进度] 问题分析智能体正在分析问题" in output
        assert "[info" not in output
        assert "Docker 命令开始" not in output
        assert "evodev-test" not in output
    finally:
        structlog.reset_defaults()


def test_verbose_logging_shows_debug_details(capsys) -> None:
    try:
        configure_logging(verbose=True)

        structlog.get_logger("test").debug("Docker 命令开始", container="evodev-test")

        output = capsys.readouterr().err
        assert "Docker 命令开始" in output
        assert "evodev-test" in output
    finally:
        structlog.reset_defaults()


def test_json_mode_can_silence_progress_logs(capsys) -> None:
    try:
        configure_logging(quiet=True)

        structlog.get_logger("test").info("不应显示")

        assert capsys.readouterr().err == ""
    finally:
        structlog.reset_defaults()


def test_repair_summary_only_contains_key_information(tmp_path: Path) -> None:
    summary = format_repair_summary(
        {
            "run_id": "run-1",
            "status": "succeeded",
            "iteration": 1,
            "max_iterations": 3,
            "changed_files": ["calculator.py"],
            "tests_passed": True,
            "review_passed": True,
            "issue_analysis": {"problem_summary": "不应显示在摘要中"},
        },
        tmp_path / "outputs",
    )

    assert "修复任务执行成功" in summary
    assert "运行编号：run-1" in summary
    assert "执行状态：成功" in summary
    assert "修改文件：calculator.py" in summary
    assert "测试结果：通过" in summary
    assert "问题分析" not in summary
    assert str((tmp_path / "outputs" / "run-1").resolve()) in summary
