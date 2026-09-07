"""验证最小 Docker SandboxProvider 的创建、查找、探针和回收闭环。"""

import asyncio
import subprocess

import pytest

from mini_deer_agent.sandbox import (
    DockerSandboxProvider,
    run_docker_project_command,
    run_docker_project_command_async,
    verify_docker_project_mount,
    verify_docker_sandbox_lifecycle,
)


def completed(
    returncode: int,
    *,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        [], returncode, stdout=stdout, stderr=stderr
    )


def test_provider_acquires_runs_fixed_probe_and_releases() -> None:
    """Provider 只运行固定探针，并在 release 后移除本地句柄。"""
    commands: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[1] == "create":
            return completed(0, stdout="container-123\n")
        if command[1] == "start":
            return completed(0, stdout="mini-deer-sandbox-ready\n")
        return completed(0, stdout="container-123\n")

    provider = DockerSandboxProvider(run_command=runner)
    sandbox = provider.acquire("run-1")

    assert provider.get("run-1") == sandbox
    assert "--pull" in commands[0]
    assert "never" in commands[0]
    assert commands[0][-3:] == [
        "python",
        "-c",
        "print('mini-deer-sandbox-ready')",
    ]
    assert provider.execute_probe(sandbox) == "mini-deer-sandbox-ready"
    assert provider.release("run-1") is True
    assert provider.get("run-1") is None
    assert commands[-1] == ["docker", "rm", "--force", "container-123"]


def test_lifecycle_probe_releases_container_after_probe_failure() -> None:
    """固定探针失败也必须进入 release，并把回收事实返回给调用方。"""
    commands: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[1] == "create":
            return completed(0, stdout="container-456\n")
        if command[1] == "start":
            return completed(1, stderr="probe failed")
        return completed(0, stdout="container-456\n")

    result = verify_docker_sandbox_lifecycle(runner)

    assert result == {
        "lifecycle_ready": False,
        "stage": "probe",
        "reason": "sandbox_probe_failed",
        "created": True,
        "retrieved": True,
        "released": True,
        "message": "临时沙箱已创建，但固定探针执行失败。",
    }
    assert commands[-1] == ["docker", "rm", "--force", "container-456"]


def test_project_mount_probe_returns_container_entries_and_releases(tmp_path) -> None:
    """项目根由调用方绑定，固定探针返回容器内条目并完成回收。"""
    commands: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[1] == "create":
            return completed(0, stdout="container-789\n")
        if command[1] == "start":
            return completed(
                0,
                stdout='{"entries":["README.md","src"],"truncated":false}\n',
            )
        return completed(0, stdout="container-789\n")

    result = verify_docker_project_mount(tmp_path, runner)

    assert result["mount_ready"] is True
    assert result["entries"] == ["README.md", "src"]
    assert result["container_path"] == "/workspace"
    assert result["released"] is True
    mount = commands[0][commands[0].index("--mount") + 1]
    assert mount == (
        f"type=bind,source={tmp_path.resolve()},target=/workspace,readonly"
    )
    assert commands[-1] == ["docker", "rm", "--force", "container-789"]


def test_project_command_returns_real_exit_code_output_and_release(tmp_path) -> None:
    """单命令容器固定 cwd，退出码来自 inspect，结束后删除容器。"""
    commands: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[1] == "create":
            return completed(0, stdout="container-command\n")
        if command[1] == "start":
            return completed(0, stdout="Hello, Mini Deer!\n")
        if command[1] == "inspect":
            return completed(0, stdout="0\n")
        return completed(0, stdout="container-command\n")

    result = run_docker_project_command(
        tmp_path, "python src/main.py", runner
    )

    assert result["command_completed"] is True
    assert result["exit_code"] == 0
    assert result["stdout"] == "Hello, Mini Deer!\n"
    assert result["stderr"] == ""
    assert result["released"] is True
    create = commands[0]
    mount = create[create.index("--mount") + 1]
    assert mount == f"type=bind,source={tmp_path.resolve()},target=/workspace"
    assert create[create.index("--workdir") + 1] == "/workspace"
    assert create[-3:] == ["sh", "-lc", "python src/main.py"]
    assert commands[-1] == ["docker", "rm", "--force", "container-command"]


def test_failed_project_command_preserves_nonzero_exit_and_stderr(tmp_path) -> None:
    """命令失败是已完成的真实结果，不能被折叠为 Provider 异常。"""
    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[1] == "create":
            return completed(0, stdout="container-failed-command\n")
        if command[1] == "start":
            return completed(2, stderr="missing file\n")
        if command[1] == "inspect":
            return completed(0, stdout="2\n")
        return completed(0, stdout="container-failed-command\n")

    result = run_docker_project_command(
        tmp_path, "python missing-file.py", runner
    )

    assert result["command_completed"] is True
    assert result["exit_code"] == 2
    assert result["stdout"] == ""
    assert result["stderr"] == "missing file\n"
    assert result["released"] is True


def test_timed_out_project_command_is_released_without_fake_exit_code(tmp_path) -> None:
    """Docker attach 超时后强制删除容器，并返回明确超时事实。"""
    commands: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[1] == "create":
            return completed(0, stdout="container-timeout\n")
        if command[1] == "start":
            raise subprocess.TimeoutExpired(command, 1)
        return completed(0, stdout="container-timeout\n")

    result = run_docker_project_command(
        tmp_path,
        "sleep 5",
        runner,
        timeout_seconds=1,
    )

    assert result == {
        "command_completed": False,
        "stage": "command",
        "reason": "project_command_timeout",
        "timed_out": True,
        "timeout_seconds": 1,
        "released": True,
        "message": "项目命令运行超过 1 秒，已终止并回收容器。",
    }
    assert not any(command[1] == "inspect" for command in commands)
    assert commands[-1] == ["docker", "rm", "--force", "container-timeout"]


def test_cancelled_async_project_command_forces_container_removal(tmp_path) -> None:
    """Run 取消必须穿透 Docker 等待，并按唯一名称强制删除容器。"""
    commands: list[list[str]] = []

    async def scenario() -> None:
        started = asyncio.Event()

        async def runner(
            command: list[str], _timeout: int
        ) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            if command[1] == "create":
                return completed(0, stdout="container-cancelled\n")
            if command[1] == "start":
                started.set()
                await asyncio.Event().wait()
            return completed(0, stdout="container-cancelled\n")

        task = asyncio.create_task(
            run_docker_project_command_async(
                tmp_path,
                "sleep 30",
                runner,
                timeout_seconds=60,
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    create = commands[0]
    container_name = create[create.index("--name") + 1]
    assert container_name.startswith("mini-deer-command-")
    assert commands[-1] == ["docker", "rm", "--force", container_name]
    assert not any(command[1] == "inspect" for command in commands)
