import shutil
import subprocess


def docker_is_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        # 客户端存在不代表守护进程可用，因此使用短超时做无副作用探测。
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
