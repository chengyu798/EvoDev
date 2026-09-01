"""从应用状态中获取接口所需的服务实例。"""

from fastapi import Request

from evodev.application.services import RunService, TaskService


def get_task_service(request: Request) -> TaskService:
    return request.app.state.task_service


def get_run_service(request: Request) -> RunService:
    return request.app.state.run_service
