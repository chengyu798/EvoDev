"""定义环境检查、工作流冒烟测试和服务启动命令。"""

import json
import time
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer
import uvicorn

from evodev.application.cleanup import DemoCleanupService
from evodev.application.evolution import build_prompt_evolution_worker
from evodev.application.repair import build_repair_workflow_service
from evodev.config import get_settings
from evodev.domain.tasks import TaskCreate, TaskRead
from evodev.observability.logging import configure_logging
from evodev.persistence.artifacts import LocalArtifactStore
from evodev.persistence.checkpoints import PostgresCheckpointStore
from evodev.persistence.evolution import PostgresPromptEvolutionStore
from evodev.runtime.sandbox import docker_is_available
from evodev.runtime.workspace import WorkspaceManager
from evodev.workflows.compiler import build_bug_fix_graph

app = typer.Typer(no_args_is_help=True, help="EvoDev 本地开发命令。")


@app.command()
def doctor() -> None:
    """检查本地依赖，不修改系统状态。"""
    settings = get_settings()
    settings.ensure_directories()
    checkpoint_store = PostgresCheckpointStore(settings.database_url)
    report = {
        "environment": settings.environment,
        "docker_available": docker_is_available(),
        "sandbox_image": settings.sandbox_image,
        "sandbox_network": settings.sandbox_network,
        "sandbox_cpus": settings.sandbox_cpus,
        "sandbox_memory": settings.sandbox_memory,
        "sandbox_pids_limit": settings.sandbox_pids_limit,
        "command_timeout_seconds": settings.command_timeout_seconds,
        "max_command_output_bytes": settings.max_command_output_bytes,
        "database_backend": "postgresql",
        "database_available": checkpoint_store.is_available(),
        "outputs_dir": str(settings.outputs_dir.resolve()),
        "workspaces_dir": str(settings.workspaces_dir.resolve()),
        "llm_model_configured": bool(settings.llm_model),
        "llm_api_key_configured": bool(settings.llm_api_key),
    }
    typer.echo(json.dumps(report, indent=2, ensure_ascii=False))


@app.command("graph-smoke")
def graph_smoke() -> None:
    """在不调用模型和仓库的情况下验证工作流。"""
    graph = build_bug_fix_graph()
    result = graph.invoke(
        {
            "run_id": "smoke-run",
            "task_id": "smoke-task",
            "status": "created",
            "repository_path": ".",
            "issue_title": "工作流冒烟测试",
            "issue_body": "验证工作流路由是否正确。",
            "test_command": "pytest -q",
            "changed_files": [],
            "retrieved_experience_ids": [],
            "iteration": 0,
            "max_iterations": 3,
            "tests_passed": True,
            "review_passed": True,
        }
    )
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))


@app.command()
def repair(
    repository: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, help="本地 Git 仓库"),
    ],
    issue_title: Annotated[str, typer.Option(help="问题标题")],
    issue_body: Annotated[str, typer.Option(help="问题描述")],
    test_command: Annotated[str, typer.Option(help="pytest 测试命令")] = "pytest -q",
    max_iterations: Annotated[
        int,
        typer.Option(min=1, max=3, help="最大自动修复次数"),
    ] = 3,
    verbose: Annotated[bool, typer.Option("--verbose", help="显示 Docker 等调试细节")] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="只输出完整 JSON 结果"),
    ] = False,
) -> None:
    """执行一次完整的多智能体软件修复任务。"""
    configure_logging(verbose=verbose, quiet=json_output)
    payload = TaskCreate(
        repository_path=repository,
        issue_title=issue_title,
        issue_body=issue_body,
        test_command=test_command,
        max_iterations=max_iterations,
    )
    task = TaskRead(**payload.model_dump())
    result = build_repair_workflow_service(get_settings()).execute(
        run_id=uuid4().hex,
        task=task,
    )
    if json_output:
        typer.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return
    typer.echo(format_repair_summary(result, get_settings().outputs_dir))


def format_repair_summary(result: dict[str, object], outputs_dir: Path) -> str:
    """将完整工作流状态转换为便于阅读的终端摘要。"""
    run_id = str(result["run_id"])
    succeeded = result["status"] == "succeeded"
    title = "修复任务执行成功" if succeeded else "修复任务执行失败"
    changed_files = result.get("changed_files") or []
    changed_text = "、".join(str(path) for path in changed_files) or "无"
    lines = [
        "",
        title,
        f"运行编号：{run_id}",
        f"执行状态：{'成功' if succeeded else '失败'}",
        f"修复轮次：{result.get('iteration', 0)}/{result.get('max_iterations', 3)}",
        f"修改文件：{changed_text}",
        f"测试结果：{format_check_result(result.get('tests_passed'))}",
        f"审查结果：{format_check_result(result.get('review_passed'))}",
        f"历史经验：使用 {len(result.get('retrieved_experience_ids') or [])} 条",
        "Token 用量："
        f"输入 {result.get('prompt_tokens', 0)} / "
        f"输出 {result.get('completion_tokens', 0)}",
        f"执行耗时：{result.get('duration_ms', 0)} 毫秒",
        f"运行输出：{(outputs_dir / run_id).resolve()}",
    ]
    if not succeeded:
        lines.extend(
            [
                f"错误代码：{result.get('error_code') or '未知'}",
                f"失败原因：{result.get('error_message') or '未提供'}",
                f"生成经验：{result.get('generated_experience_id') or '未生成'}",
            ]
        )
    return "\n".join(lines)


def format_check_result(value: object) -> str:
    """显示通过、未通过或未执行三种检查状态。"""
    if value is True:
        return "通过"
    if value is False:
        return "未通过"
    return "未执行"


@app.command("cleanup-demo")
def cleanup_demo(
    run_id: Annotated[str, typer.Option(help="需要清理的运行编号")],
    demo_repository: Annotated[
        Path | None,
        typer.Option(help="需要删除的 evodev-demo 临时 Git 仓库"),
    ] = None,
    remove_image: Annotated[
        bool,
        typer.Option("--remove-image", help="同时删除 Docker 沙箱镜像"),
    ] = False,
) -> None:
    """安全清理一次手动测试产生的本地资源。"""
    settings = get_settings()
    result = DemoCleanupService(
        WorkspaceManager(settings.workspaces_dir),
        LocalArtifactStore(settings.outputs_dir),
        PostgresCheckpointStore(settings.database_url),
        settings.sandbox_image,
    ).execute(
        run_id=run_id,
        demo_repository=demo_repository,
        remove_image=remove_image,
    )
    typer.echo(
        "\n".join(
            [
                "测试环境清理完成",
                f"运行编号：{result.run_id}",
                f"隔离工作区：{format_removed(result.workspace_removed)}",
                f"运行输出：{format_removed(result.outputs_removed)}",
                f"运行检查点：{format_removed(result.checkpoints_removed)}",
                f"示例仓库：{format_removed(result.demo_repository_removed)}",
                f"Docker 镜像：{format_removed(result.sandbox_image_removed)}",
            ]
        )
    )


def format_removed(removed: bool) -> str:
    """显示资源已删除或未找到。"""
    return "已删除" if removed else "未删除或不存在"


@app.command("evolve-prompt")
def evolve_prompt(
    agent: Annotated[str, typer.Option(help="需要进化的 Agent：analyst 或 developer")],
    min_experiences: Annotated[
        int,
        typer.Option(min=1, max=20, help="生成候选版本所需的最少经验数"),
    ] = 1,
) -> None:
    """只投递 Prompt 进化任务，不占用当前修复进程。"""
    if agent not in {"analyst", "developer"}:
        raise typer.BadParameter("首版只允许 analyst 或 developer")
    settings = get_settings()
    job = PostgresPromptEvolutionStore(settings.database_url).enqueue(
        agent_role=agent,
        min_experiences=min_experiences,
    )
    typer.echo(
        "\n".join(
            [
                "Prompt 进化任务已进入队列",
                f"任务编号：{job.id}",
                f"目标 Agent：{job.agent_role}",
                f"所需经验：{job.min_experiences} 条",
                "请在独立终端运行：uv run evodev evolution-worker --once",
            ]
        )
    )


@app.command("evolution-worker")
def evolution_worker(
    watch: Annotated[
        bool,
        typer.Option("--watch/--once", help="持续轮询或只处理一个任务"),
    ] = False,
) -> None:
    """在独立进程中处理 Prompt 候选生成和 A/B 评测。"""
    configure_logging()
    worker = build_prompt_evolution_worker(get_settings())
    while True:
        result = worker.run_once()
        if result is None:
            if not watch:
                typer.echo("当前没有待处理的 Prompt 进化任务")
                return
            time.sleep(5)
            continue
        job, version = result
        evaluation_reason = (
            (version.evaluation or {}).get("reason", "无") if version else "无"
        )
        typer.echo(
            "\n".join(
                [
                    "Prompt 进化任务处理完成",
                    f"任务编号：{job.id}",
                    f"候选版本：{version.effective_version if version else '未生成'}",
                    f"最终状态：{version.status.value if version else 'failed'}",
                    f"评测结论：{evaluation_reason}",
                ]
            )
        )
        if not watch:
            return


@app.command("prompt-versions")
def prompt_versions(
    agent: Annotated[str, typer.Option(help="需要查询的 Agent")],
) -> None:
    """查看 Prompt 指导层的历史版本和状态。"""
    versions = PostgresPromptEvolutionStore(
        get_settings().database_url
    ).list_versions(agent)
    if not versions:
        typer.echo("当前 Agent 尚无进化 Prompt 版本")
        return
    typer.echo(
        "\n".join(
            f"e{item.revision} | {item.status.value} | {item.id} | {item.created_at}"
            for item in versions
        )
    )


@app.command("evolution-jobs")
def evolution_jobs() -> None:
    """查看最近的 Prompt 进化任务。"""
    jobs = PostgresPromptEvolutionStore(get_settings().database_url).list_jobs()
    if not jobs:
        typer.echo("当前没有 Prompt 进化任务")
        return
    typer.echo(
        "\n".join(
            f"{item.id} | {item.agent_role} | {item.status.value} | "
            f"{item.error_message or '无错误'}"
            for item in jobs
        )
    )


@app.command("rollback-prompt")
def rollback_prompt(
    agent: Annotated[str, typer.Option(help="需要回滚的 Agent")],
) -> None:
    """回滚到上一个曾经激活的 Prompt 指导层。"""
    version = PostgresPromptEvolutionStore(get_settings().database_url).rollback(agent)
    if version is None:
        typer.echo("没有可回滚的历史版本")
        raise typer.Exit(code=1)
    typer.echo(f"已回滚到 {agent} 的 {version.effective_version}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
    reload: bool = typer.Option(False),
) -> None:
    """启动 FastAPI 开发服务器。"""
    uvicorn.run("evodev.api.app:app", host=host, port=port, reload=reload)
