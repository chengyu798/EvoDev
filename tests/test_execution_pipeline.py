"""验证不依赖智能体的代码修改、测试和补丁生成闭环。"""

import subprocess
from pathlib import Path

import pytest

from evodev.application.execution import DeterministicRepairService
from evodev.runtime.sandbox import (
    DockerCommandRunner,
    DockerSandboxConfig,
    docker_image_is_available,
)
from evodev.runtime.testing import PytestRunner
from evodev.runtime.workspace import WorkspaceManager
from evodev.tools.edit import EditTools
from evodev.tools.git import GitTools

SANDBOX_IMAGE = "evodev-python:3.13"
FIX_PATCH = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def add(left, right):
-    return left - right
+    return left + right
"""


def initialize_bug_repository(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "测试用户"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True
    )
    (path / "calculator.py").write_text(
        "def add(left, right):\n    return left - right\n",
        encoding="utf-8",
    )
    (path / "test_calculator.py").write_text(
        "from calculator import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "--quiet", "-m", "缺陷版本"], check=True)


@pytest.mark.skipif(
    not docker_image_is_available(SANDBOX_IMAGE),
    reason="本地 Docker 沙箱镜像不可用",
)
def test_deterministic_repair_pipeline(tmp_path: Path) -> None:
    source = tmp_path / "source"
    initialize_bug_repository(source)
    pytest_runner = PytestRunner(
        DockerCommandRunner(DockerSandboxConfig(image=SANDBOX_IMAGE))
    )
    service = DeterministicRepairService(
        workspace_manager=WorkspaceManager(tmp_path / "workspaces"),
        pytest_runner=pytest_runner,
        edit_tools=EditTools(),
        git_tools=GitTools(),
    )

    result = service.execute(
        run_id="run-e2e",
        source_repository=source,
        patch=FIX_PATCH,
    )

    assert result.baseline.passed is False
    assert result.verification.passed is True
    assert result.changed_files == ["calculator.py"]
    assert "-    return left - right" in result.patch
    assert "+    return left + right" in result.patch
    assert (source / "calculator.py").read_text(encoding="utf-8").endswith(
        "return left - right\n"
    )
