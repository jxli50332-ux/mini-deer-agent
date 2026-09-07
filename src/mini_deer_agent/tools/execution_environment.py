"""提供固定、只读的隔离执行环境诊断，不开放任意命令。"""

import json
import subprocess
from collections.abc import Callable

from langchain_core.tools import tool
from pydantic import Field

from mini_deer_agent.sandbox import verify_docker_sandbox_lifecycle


type CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def inspect_docker_environment(
    run_command: CommandRunner = subprocess.run,
) -> dict[str, object]:
    """检查 Docker Linux 引擎是否可连接，只返回稳定诊断字段。"""
    command = ["docker", "version", "--format", "{{.Server.Version}}"]
    try:
        completed = run_command(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        return {
            "ok": True,
            "provider": "docker",
            "available": False,
            "reason": "docker_cli_missing",
            "diagnostic_only": True,
            "message": "未找到 Docker CLI，当前不能在隔离环境运行项目命令。",
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": True,
            "provider": "docker",
            "available": False,
            "reason": "docker_check_timeout",
            "diagnostic_only": True,
            "message": "Docker 状态检查超时，当前不能确认隔离执行环境可用。",
        }
    except OSError:
        return {
            "ok": True,
            "provider": "docker",
            "available": False,
            "reason": "docker_check_failed",
            "diagnostic_only": True,
            "message": "Docker 状态检查失败，当前不能确认隔离执行环境可用。",
        }

    version = completed.stdout.strip()
    if completed.returncode != 0 or not version:
        return {
            "ok": True,
            "provider": "docker",
            "available": False,
            "reason": "docker_daemon_unavailable",
            "diagnostic_only": True,
            "message": "Docker CLI 已安装，但 Linux 容器引擎当前不可用。",
        }
    return {
        "ok": True,
        "provider": "docker",
        "available": True,
        "server_version": version,
        "diagnostic_only": True,
        "message": "Docker 隔离执行环境可连接；当前只开放状态诊断，尚不能运行项目命令。",
    }


@tool
def inspect_execution_environment(
    verify_lifecycle: bool = Field(
        default=False,
        description="是否额外创建临时容器、运行固定探针并销毁；不接受自定义命令",
    ),
) -> str:
    """检查隔离项目命令环境；可验证临时容器生命周期，不执行用户命令。"""
    result = inspect_docker_environment()
    if verify_lifecycle and result.get("available") is True:
        lifecycle = verify_docker_sandbox_lifecycle()
        result = {**result, **lifecycle}
        result["message"] = lifecycle["message"]
    return json.dumps(result, ensure_ascii=False)
