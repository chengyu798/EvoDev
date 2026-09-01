from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from evodev.application.services import RunNotFoundError, TaskNotFoundError


def register_error_handlers(app: FastAPI) -> None:
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
