"""定义环境检查、工作流冒烟测试和服务启动命令。"""

import json

import typer
import uvicorn

from evodev.config import get_settings
from evodev.runtime.sandbox import docker_is_available
from evodev.workflows.compiler import build_bug_fix_graph

app = typer.Typer(no_args_is_help=True, help="EvoDev 本地开发命令。")


@app.command()
def doctor() -> None:
    """检查本地依赖，不修改系统状态。"""
    settings = get_settings()
    settings.ensure_directories()
    report = {
        "environment": settings.environment,
        "docker_available": docker_is_available(),
        "sandbox_image": settings.sandbox_image,
        "database_url": settings.database_url,
        "artifacts_dir": str(settings.artifacts_dir.resolve()),
        "workspaces_dir": str(settings.workspaces_dir.resolve()),
        "llm_configured": bool(settings.llm_model and settings.llm_api_key),
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
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
    reload: bool = typer.Option(False),
) -> None:
    """启动 FastAPI 开发服务器。"""
    uvicorn.run("evodev.api.app:app", host=host, port=port, reload=reload)
