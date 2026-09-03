"""读取环境配置并准备运行所需目录。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从 EVODEV_ 开头的环境变量加载运行配置。"""

    model_config = SettingsConfigDict(
        env_prefix="EVODEV_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = "sqlite:///./data/evodev.db"
    outputs_dir: Path = Path("outputs")
    workspaces_dir: Path = Path(".evodev/workspaces")
    sandbox_image: str = "evodev-python:3.13"
    sandbox_network: str = "none"
    sandbox_cpus: float = 2.0
    sandbox_memory: str = "2g"
    sandbox_pids_limit: int = 256
    command_timeout_seconds: int = 120
    max_command_output_bytes: int = 1_048_576
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None

    def ensure_directories(self) -> None:
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
