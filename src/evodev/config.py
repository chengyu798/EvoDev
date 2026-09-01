from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from EVODEV_* environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="EVODEV_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = "sqlite:///./data/evodev.db"
    artifacts_dir: Path = Path("artifacts")
    workspaces_dir: Path = Path(".evodev/workspaces")
    sandbox_image: str = "evodev-python:3.13"
    command_timeout_seconds: int = 120
    max_command_output_bytes: int = 1_048_576
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None

    def ensure_directories(self) -> None:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
