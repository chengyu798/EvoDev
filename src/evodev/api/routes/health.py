from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from evodev import __version__
from evodev.runtime.sandbox import docker_is_available

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    docker_available: bool


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(version=__version__, docker_available=docker_is_available())
