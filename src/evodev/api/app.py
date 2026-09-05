"""创建 FastAPI 应用并装配路由、服务和异常处理。"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from evodev import __version__
from evodev.api.errors import register_error_handlers
from evodev.api.routes import health, runs, tasks
from evodev.application.conversations import build_read_only_agent_service
from evodev.application.repair import build_repair_workflow_service
from evodev.application.services import RunService, TaskService
from evodev.config import get_settings
from evodev.persistence.artifacts import LocalArtifactStore
from evodev.persistence.tasks import (
    PostgresRunStore,
    PostgresTaskRunStore,
    PostgresTaskStore,
)

ServiceFactory = Callable[[], tuple[TaskService, RunService]]


def create_app(service_factory: ServiceFactory | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = get_settings()
        settings.ensure_directories()
        if service_factory is None:
            shared_store = PostgresTaskRunStore(settings.database_url)
            task_service = TaskService(
                PostgresTaskStore(shared_store),
                build_read_only_agent_service(settings) if settings.llm_model else None,
            )
            run_service = RunService(
                task_service,
                store=PostgresRunStore(shared_store),
                workflow_service_factory=lambda: build_repair_workflow_service(settings),
                artifact_store=LocalArtifactStore(settings.outputs_dir),
            )
        else:
            task_service, run_service = service_factory()
        app.state.task_service = task_service
        app.state.run_service = run_service
        yield

    application = FastAPI(
        title="EvoDev API",
        description="多智能体软件修复接口",
        version=__version__,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health.router, prefix="/api")
    application.include_router(tasks.router, prefix="/api")
    application.include_router(runs.router, prefix="/api")
    register_error_handlers(application)
    return application


app = create_app()
