"""将应用层异常转换为统一的 HTTP 错误响应。"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from evodev.application.services import (
    ActiveRunExistsError,
    ConversationExecutionError,
    PlanApprovalRequiredError,
    PlanNotFoundError,
    RunNotFoundError,
    TaskNotFoundError,
)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ConversationExecutionError)
    async def conversation_failed(
        _: Request,
        exc: ConversationExecutionError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={
                "code": "CONVERSATION_EXECUTION_FAILED",
                "message": str(exc),
            },
        )

    @app.exception_handler(TaskNotFoundError)
    async def task_not_found(_: Request, exc: TaskNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"code": "TASK_NOT_FOUND", "message": str(exc)},
        )

    @app.exception_handler(RunNotFoundError)
    async def run_not_found(_: Request, exc: RunNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"code": "RUN_NOT_FOUND", "message": str(exc)},
        )

    @app.exception_handler(PlanNotFoundError)
    async def plan_not_found(_: Request, exc: PlanNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"code": "PLAN_NOT_FOUND", "message": str(exc)},
        )

    @app.exception_handler(PlanApprovalRequiredError)
    async def plan_approval_required(
        _: Request,
        exc: PlanApprovalRequiredError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"code": "PLAN_APPROVAL_REQUIRED", "message": str(exc)},
        )

    @app.exception_handler(ActiveRunExistsError)
    async def active_run_exists(_: Request, exc: ActiveRunExistsError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"code": "ACTIVE_RUN_EXISTS", "message": str(exc)},
        )
