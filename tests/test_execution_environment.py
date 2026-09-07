"""验证执行环境诊断不会开放或伪造项目命令能力。"""

import json
import subprocess

from mini_deer_agent.tools import execution_environment
from mini_deer_agent.tools.execution_environment import (
    inspect_docker_environment,
    inspect_execution_environment,
)
from mini_deer_agent.tools.registry import get_agent_tools


def completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess[str]:
    """构造固定 Docker 探测结果，单测不访问真实容器引擎。"""
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="ignored")


def test_docker_environment_reports_available_server_version() -> None:
    """只有固定命令成功并返回服务端版本时才标记环境可用。"""
    captured: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append(command)
        return completed(0, "29.0.1\n")

    result = inspect_docker_environment(runner)

    assert captured == [["docker", "version", "--format", "{{.Server.Version}}"]]
    assert result["available"] is True
    assert result["server_version"] == "29.0.1"
    assert result["diagnostic_only"] is True


def test_docker_environment_reports_daemon_unavailable_without_stderr() -> None:
    """引擎连接失败返回稳定原因，不把本机错误详情交给模型。"""
    result = inspect_docker_environment(lambda *_args, **_kwargs: completed(1))

    assert result == {
        "ok": True,
        "provider": "docker",
        "available": False,
        "reason": "docker_daemon_unavailable",
        "diagnostic_only": True,
        "message": "Docker CLI 已安装，但 Linux 容器引擎当前不可用。",
    }


def test_execution_environment_tool_returns_current_diagnostic(monkeypatch) -> None:
    """主图注册的工具只序列化受控诊断结果，不接受命令参数。"""
    monkeypatch.setattr(
        execution_environment,
        "inspect_docker_environment",
        lambda: {"ok": True, "available": False, "reason": "test"},
    )

    result = json.loads(inspect_execution_environment.invoke({}))

    assert result == {"ok": True, "available": False, "reason": "test"}
    assert "inspect_execution_environment" in {
        tool.name for tool in get_agent_tools()
    }


def test_execution_environment_tool_can_verify_fixed_lifecycle(monkeypatch) -> None:
    """显式生命周期诊断合并 Provider 结果，仍不接收项目命令。"""
    monkeypatch.setattr(
        execution_environment,
        "inspect_docker_environment",
        lambda: {"ok": True, "available": True, "server_version": "29.6.2"},
    )
    monkeypatch.setattr(
        execution_environment,
        "verify_docker_sandbox_lifecycle",
        lambda: {
            "lifecycle_ready": True,
            "created": True,
            "retrieved": True,
            "released": True,
            "message": "生命周期完成。",
        },
    )

    result = json.loads(
        inspect_execution_environment.invoke({"verify_lifecycle": True})
    )

    assert result["available"] is True
    assert result["lifecycle_ready"] is True
    assert result["released"] is True
    assert result["message"] == "生命周期完成。"
