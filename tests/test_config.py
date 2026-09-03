"""验证运行目录配置和目录初始化。"""

from pathlib import Path

from evodev.config import Settings


def test_default_output_directory_uses_clear_name() -> None:
    settings = Settings(_env_file=None)

    assert settings.outputs_dir == Path("outputs")
    assert "artifacts_dir" not in Settings.model_fields


def test_ensure_directories_creates_outputs_and_workspaces(tmp_path: Path) -> None:
    outputs_dir = tmp_path / "outputs"
    workspaces_dir = tmp_path / "workspaces"
    settings = Settings(
        _env_file=None,
        outputs_dir=outputs_dir,
        workspaces_dir=workspaces_dir,
    )

    settings.ensure_directories()

    assert outputs_dir.is_dir()
    assert workspaces_dir.is_dir()
