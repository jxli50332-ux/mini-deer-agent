"""通过 Docker CLI 提供最小、可回收的临时沙箱生命周期。"""

import asyncio
import json
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4


DEFAULT_SANDBOX_IMAGE = "python:3.12-slim-bookworm"
SANDBOX_PROBE_OUTPUT = "mini-deer-sandbox-ready"
SANDBOX_WORKSPACE_PATH = "/workspace"
SANDBOX_WORKSPACE_PROBE = (
    "import json; from pathlib import Path; "
    "entries=sorted(item.name for item in Path('/workspace').iterdir()); "
    "print(json.dumps({'entries': entries[:50], "
    "'truncated': len(entries) > 50}, ensure_ascii=False))"
)

type CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
type AsyncCommandRunner = Callable[
    [list[str], int], Awaitable[subprocess.CompletedProcess[str]]
]


def _docker_create_command(
    *,
    container_name: str,
    image: str,
    workspace_path: Path | None,
    command: str | None,
) -> list[str]:
    """构造统一的临时容器命令，避免同步与异步执行策略漂移。"""
    mount_mode = "" if command is not None else ",readonly"
    mount_arguments = (
        [
            "--mount",
            (
                f"type=bind,source={workspace_path},"
                f"target={SANDBOX_WORKSPACE_PATH}{mount_mode}"
            ),
            "--workdir",
            SANDBOX_WORKSPACE_PATH,
        ]
        if workspace_path is not None
        else []
    )
    container_command = (
        ["sh", "-lc", command]
        if command is not None
        else [
            "python",
            "-c",
            (
                SANDBOX_WORKSPACE_PROBE
                if workspace_path is not None
                else f"print({SANDBOX_PROBE_OUTPUT!r})"
            ),
        ]
    )
    return [
        "docker",
        "create",
        "--pull",
        "never",
        "--name",
        container_name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--pids-limit",
        "32",
        "--memory",
        "128m",
        "--cpus",
        "0.5",
        *mount_arguments,
        image,
        *container_command,
    ]


async def _run_async_command(
    command: list[str], timeout: int
) -> subprocess.CompletedProcess[str]:
    """异步等待 Docker CLI；取消或超时时同时终止本地 CLI 进程。"""
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
    except TimeoutError as exc:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.communicate()
        raise subprocess.TimeoutExpired(command, timeout) from exc
    except asyncio.CancelledError:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.communicate()
        raise
    return subprocess.CompletedProcess(
        command,
        process.returncode,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


@dataclass(frozen=True, slots=True)
class DockerSandbox:
    """一个由 Provider 持有的临时 Docker 容器。"""

    sandbox_id: str
    container_id: str
    image: str
    probe_kind: Literal["lifecycle", "workspace", "command"] = "lifecycle"


class SandboxLifecycleError(RuntimeError):
    """带稳定阶段和原因码的沙箱生命周期错误。"""

    def __init__(self, *, stage: str, reason: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.reason = reason
        self.message = message


class DockerSandboxProvider:
    """创建、查找和销毁单进程内的 Docker 临时沙箱。"""

    def __init__(
        self,
        *,
        run_command: CommandRunner = subprocess.run,
        image: str = DEFAULT_SANDBOX_IMAGE,
    ) -> None:
        self._run_command = run_command
        self._image = image
        self._sandboxes: dict[str, DockerSandbox] = {}

    def _run(self, command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        try:
            return self._run_command(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError as exc:
            raise SandboxLifecycleError(
                stage="acquire",
                reason="docker_cli_missing",
                message="未找到 Docker CLI，无法创建临时沙箱。",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise SandboxLifecycleError(
                stage="docker",
                reason="sandbox_operation_timeout",
                message="Docker 沙箱生命周期操作超时。",
            ) from exc
        except OSError as exc:
            raise SandboxLifecycleError(
                stage="docker",
                reason="sandbox_operation_failed",
                message="Docker 沙箱生命周期操作失败。",
            ) from exc

    def acquire(self, sandbox_id: str) -> DockerSandbox:
        """创建一个不联网、使用只读根文件系统的临时容器。"""
        return self._acquire(sandbox_id, workspace_path=None, command=None)

    def acquire_workspace(
        self, sandbox_id: str, workspace_path: Path
    ) -> DockerSandbox:
        """把已由应用授权的项目根只读挂载到固定容器路径。"""
        return self._acquire(
            sandbox_id,
            workspace_path=workspace_path.resolve(strict=True),
            command=None,
        )

    def acquire_command(
        self,
        sandbox_id: str,
        workspace_path: Path,
        command: str,
    ) -> DockerSandbox:
        """创建以 `/workspace` 为工作目录的一次性项目命令容器。"""
        return self._acquire(
            sandbox_id,
            workspace_path=workspace_path.resolve(strict=True),
            command=command,
        )

    def _acquire(
        self,
        sandbox_id: str,
        *,
        workspace_path: Path | None,
        command: str | None,
    ) -> DockerSandbox:
        """根据固定探针类型构造容器；挂载路径不来自模型参数。"""
        existing = self._sandboxes.get(sandbox_id)
        if existing is not None:
            return existing

        container_name = f"mini-deer-probe-{uuid4().hex}"
        completed = self._run(
            _docker_create_command(
                container_name=container_name,
                image=self._image,
                workspace_path=workspace_path,
                command=command,
            ),
            timeout=15,
        )
        container_id = completed.stdout.strip()
        if completed.returncode != 0 or not container_id:
            reason = (
                "sandbox_image_unavailable"
                if "No such image" in completed.stderr
                else "sandbox_create_failed"
            )
            message = (
                f"本机没有可用的沙箱镜像 {self._image}。"
                if reason == "sandbox_image_unavailable"
                else "Docker 临时沙箱创建失败。"
            )
            raise SandboxLifecycleError(
                stage="acquire",
                reason=reason,
                message=message,
            )

        sandbox = DockerSandbox(
            sandbox_id=sandbox_id,
            container_id=container_id,
            image=self._image,
            probe_kind=(
                "command"
                if command is not None
                else "workspace" if workspace_path is not None else "lifecycle"
            ),
        )
        self._sandboxes[sandbox_id] = sandbox
        return sandbox

    def get(self, sandbox_id: str) -> DockerSandbox | None:
        """返回本 Provider 当前持有的沙箱，不访问 Docker。"""
        return self._sandboxes.get(sandbox_id)

    def execute_probe(self, sandbox: DockerSandbox) -> str:
        """启动容器并读取固定探针输出，不接受外部命令。"""
        if sandbox.probe_kind != "lifecycle":
            raise ValueError("workspace sandbox requires execute_workspace_probe")
        completed = self._run(
            ["docker", "start", "--attach", sandbox.container_id],
            timeout=15,
        )
        output = completed.stdout.strip()
        if completed.returncode != 0 or output != SANDBOX_PROBE_OUTPUT:
            raise SandboxLifecycleError(
                stage="probe",
                reason="sandbox_probe_failed",
                message="临时沙箱已创建，但固定探针执行失败。",
            )
        return output

    def execute_workspace_probe(self, sandbox: DockerSandbox) -> dict[str, object]:
        """读取固定 `/workspace` 根条目探针的结构化输出。"""
        if sandbox.probe_kind != "workspace":
            raise ValueError("lifecycle sandbox requires execute_probe")
        completed = self._run(
            ["docker", "start", "--attach", sandbox.container_id],
            timeout=15,
        )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = None
        if (
            completed.returncode != 0
            or not isinstance(payload, dict)
            or not isinstance(payload.get("entries"), list)
            or not all(isinstance(entry, str) for entry in payload["entries"])
            or not isinstance(payload.get("truncated"), bool)
        ):
            raise SandboxLifecycleError(
                stage="mount_probe",
                reason="sandbox_mount_probe_failed",
                message="项目沙箱已创建，但无法读取容器内的项目根。",
            )
        return payload

    def execute_command(
        self,
        sandbox: DockerSandbox,
        *,
        timeout_seconds: int,
    ) -> dict[str, object]:
        """运行容器创建时冻结的命令，并读取真实容器退出码。"""
        if sandbox.probe_kind != "command":
            raise ValueError("sandbox does not contain a project command")
        try:
            completed = self._run(
                ["docker", "start", "--attach", sandbox.container_id],
                timeout=timeout_seconds,
            )
        except SandboxLifecycleError as exc:
            if exc.reason != "sandbox_operation_timeout":
                raise
            raise SandboxLifecycleError(
                stage="command",
                reason="project_command_timeout",
                message=f"项目命令运行超过 {timeout_seconds} 秒，已终止并回收容器。",
            ) from exc
        inspected = self._run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.ExitCode}}",
                sandbox.container_id,
            ],
            timeout=5,
        )
        try:
            exit_code = int(inspected.stdout.strip())
        except ValueError as exc:
            raise SandboxLifecycleError(
                stage="command_result",
                reason="sandbox_exit_code_unavailable",
                message="项目命令已结束，但无法读取真实退出码。",
            ) from exc
        if inspected.returncode != 0:
            raise SandboxLifecycleError(
                stage="command_result",
                reason="sandbox_exit_code_unavailable",
                message="项目命令已结束，但无法读取真实退出码。",
            )
        return {
            "exit_code": exit_code,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    def release(self, sandbox_id: str) -> bool:
        """强制删除沙箱；不存在的本地句柄视为已释放。"""
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None:
            return False
        completed = self._run(
            ["docker", "rm", "--force", sandbox.container_id],
            timeout=15,
        )
        if completed.returncode != 0:
            raise SandboxLifecycleError(
                stage="release",
                reason="sandbox_release_failed",
                message="临时沙箱探针完成，但容器未能确认销毁。",
            )
        del self._sandboxes[sandbox_id]
        return True


def verify_docker_sandbox_lifecycle(
    run_command: CommandRunner = subprocess.run,
) -> dict[str, object]:
    """执行一次创建、查找、固定探针和销毁闭环。"""
    sandbox_id = f"diagnostic-{uuid4().hex}"
    provider = DockerSandboxProvider(run_command=run_command)
    sandbox: DockerSandbox | None = None
    probe_output: str | None = None
    failure: SandboxLifecycleError | None = None
    retrieved = False
    released = False

    try:
        sandbox = provider.acquire(sandbox_id)
        retrieved = provider.get(sandbox_id) == sandbox
        if not retrieved:
            raise SandboxLifecycleError(
                stage="get",
                reason="sandbox_lookup_failed",
                message="临时沙箱创建后无法从 Provider 取回。",
            )
        probe_output = provider.execute_probe(sandbox)
    except SandboxLifecycleError as exc:
        failure = exc
    finally:
        if sandbox is not None:
            try:
                released = provider.release(sandbox_id)
            except SandboxLifecycleError as exc:
                failure = exc

    if failure is not None:
        return {
            "lifecycle_ready": False,
            "stage": failure.stage,
            "reason": failure.reason,
            "created": sandbox is not None,
            "retrieved": retrieved,
            "released": released,
            "message": failure.message,
        }
    return {
        "lifecycle_ready": True,
        "image": DEFAULT_SANDBOX_IMAGE,
        "created": True,
        "retrieved": True,
        "probe_output": probe_output,
        "released": True,
        "message": "Docker 临时沙箱已创建、执行固定探针并销毁。",
    }


def verify_docker_project_mount(
    workspace_path: Path,
    run_command: CommandRunner = subprocess.run,
) -> dict[str, object]:
    """只读挂载一个可信项目根，读取固定根条目并销毁容器。"""
    sandbox_id = f"project-mount-{uuid4().hex}"
    provider = DockerSandboxProvider(run_command=run_command)
    sandbox: DockerSandbox | None = None
    payload: dict[str, object] | None = None
    failure: SandboxLifecycleError | None = None
    retrieved = False
    released = False

    try:
        sandbox = provider.acquire_workspace(sandbox_id, workspace_path)
        retrieved = provider.get(sandbox_id) == sandbox
        if not retrieved:
            raise SandboxLifecycleError(
                stage="get",
                reason="sandbox_lookup_failed",
                message="项目沙箱创建后无法从 Provider 取回。",
            )
        payload = provider.execute_workspace_probe(sandbox)
    except (OSError, SandboxLifecycleError) as exc:
        failure = (
            exc
            if isinstance(exc, SandboxLifecycleError)
            else SandboxLifecycleError(
                stage="mount",
                reason="project_mount_unavailable",
                message="当前项目根无法挂载到 Docker 沙箱。",
            )
        )
    finally:
        if sandbox is not None:
            try:
                released = provider.release(sandbox_id)
            except SandboxLifecycleError as exc:
                failure = exc

    if failure is not None:
        return {
            "mount_ready": False,
            "stage": failure.stage,
            "reason": failure.reason,
            "created": sandbox is not None,
            "retrieved": retrieved,
            "released": released,
            "message": failure.message,
        }
    assert payload is not None
    return {
        "mount_ready": True,
        "container_path": SANDBOX_WORKSPACE_PATH,
        "access": "read_only",
        "entries": payload["entries"],
        "truncated": payload["truncated"],
        "created": True,
        "retrieved": True,
        "released": True,
        "diagnostic_only": True,
        "message": "当前项目已只读挂载到临时沙箱并完成根目录探针，容器已销毁。",
    }


def run_docker_project_command(
    workspace_path: Path,
    command: str,
    run_command: CommandRunner = subprocess.run,
    *,
    timeout_seconds: int = 30,
) -> dict[str, object]:
    """在一次性项目容器中运行一条命令，返回输出、退出码和回收事实。"""
    normalized_command = command.strip()
    if (
        not normalized_command
        or len(normalized_command) > 4000
        or not 1 <= timeout_seconds <= 60
    ):
        return {
            "command_completed": False,
            "reason": "project_command_invalid",
            "released": False,
            "message": "项目命令不能为空、不能超过 4000 个字符，超时应为 1—60 秒。",
        }

    sandbox_id = f"project-command-{uuid4().hex}"
    provider = DockerSandboxProvider(run_command=run_command)
    sandbox: DockerSandbox | None = None
    command_result: dict[str, object] | None = None
    failure: SandboxLifecycleError | None = None
    released = False

    try:
        sandbox = provider.acquire_command(
            sandbox_id, workspace_path, normalized_command
        )
        command_result = provider.execute_command(
            sandbox, timeout_seconds=timeout_seconds
        )
    except (OSError, SandboxLifecycleError) as exc:
        failure = (
            exc
            if isinstance(exc, SandboxLifecycleError)
            else SandboxLifecycleError(
                stage="mount",
                reason="project_mount_unavailable",
                message="当前项目根无法挂载到 Docker 沙箱。",
            )
        )
    finally:
        if sandbox is not None:
            try:
                released = provider.release(sandbox_id)
            except SandboxLifecycleError as exc:
                failure = exc

    if failure is not None:
        return {
            "command_completed": False,
            "stage": failure.stage,
            "reason": failure.reason,
            "timed_out": failure.reason == "project_command_timeout",
            "timeout_seconds": timeout_seconds,
            "released": released,
            "message": failure.message,
        }
    assert command_result is not None
    stdout = str(command_result["stdout"])
    stderr = str(command_result["stderr"])
    stdout_truncated = len(stdout) > 12000
    stderr_truncated = len(stderr) > 12000
    return {
        "command_completed": True,
        "container_path": SANDBOX_WORKSPACE_PATH,
        "command": normalized_command,
        "timeout_seconds": timeout_seconds,
        "timed_out": False,
        "exit_code": command_result["exit_code"],
        "stdout": stdout[:12000],
        "stderr": stderr[:12000],
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "released": released,
        "message": "项目命令已在临时 Docker 沙箱中结束，容器已销毁。",
    }


async def run_docker_project_command_async(
    workspace_path: Path,
    command: str,
    run_command: AsyncCommandRunner = _run_async_command,
    *,
    timeout_seconds: int = 30,
) -> dict[str, object]:
    """异步运行项目命令；协程取消时先强制删除本次临时容器。"""
    normalized_command = command.strip()
    if (
        not normalized_command
        or len(normalized_command) > 4000
        or not 1 <= timeout_seconds <= 60
    ):
        return {
            "command_completed": False,
            "reason": "project_command_invalid",
            "released": False,
            "message": "项目命令不能为空、不能超过 4000 个字符，超时应为 1—60 秒。",
        }

    try:
        resolved_workspace = workspace_path.resolve(strict=True)
    except OSError:
        return {
            "command_completed": False,
            "stage": "mount",
            "reason": "project_mount_unavailable",
            "timed_out": False,
            "timeout_seconds": timeout_seconds,
            "released": False,
            "message": "当前项目根无法挂载到 Docker 沙箱。",
        }

    container_name = f"mini-deer-command-{uuid4().hex}"
    cleanup_required = False
    released = False
    failure: SandboxLifecycleError | None = None
    command_result: subprocess.CompletedProcess[str] | None = None
    exit_code: int | None = None
    try:
        cleanup_required = True
        created = await run_command(
            _docker_create_command(
                container_name=container_name,
                image=DEFAULT_SANDBOX_IMAGE,
                workspace_path=resolved_workspace,
                command=normalized_command,
            ),
            15,
        )
        if created.returncode != 0 or not created.stdout.strip():
            reason = (
                "sandbox_image_unavailable"
                if "No such image" in created.stderr
                else "sandbox_create_failed"
            )
            raise SandboxLifecycleError(
                stage="acquire",
                reason=reason,
                message=(
                    f"本机没有可用的沙箱镜像 {DEFAULT_SANDBOX_IMAGE}。"
                    if reason == "sandbox_image_unavailable"
                    else "Docker 临时沙箱创建失败。"
                ),
            )
        try:
            command_result = await run_command(
                ["docker", "start", "--attach", container_name],
                timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxLifecycleError(
                stage="command",
                reason="project_command_timeout",
                message=(
                    f"项目命令运行超过 {timeout_seconds} 秒，已终止并回收容器。"
                ),
            ) from exc
        inspected = await run_command(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.ExitCode}}",
                container_name,
            ],
            5,
        )
        try:
            exit_code = int(inspected.stdout.strip())
        except ValueError as exc:
            raise SandboxLifecycleError(
                stage="command_result",
                reason="sandbox_exit_code_unavailable",
                message="项目命令已结束，但无法读取真实退出码。",
            ) from exc
        if inspected.returncode != 0:
            raise SandboxLifecycleError(
                stage="command_result",
                reason="sandbox_exit_code_unavailable",
                message="项目命令已结束，但无法读取真实退出码。",
            )
    except asyncio.CancelledError:
        raise
    except FileNotFoundError:
        failure = SandboxLifecycleError(
            stage="acquire",
            reason="docker_cli_missing",
            message="未找到 Docker CLI，无法创建临时沙箱。",
        )
    except OSError:
        failure = SandboxLifecycleError(
            stage="docker",
            reason="sandbox_operation_failed",
            message="Docker 沙箱生命周期操作失败。",
        )
    except subprocess.TimeoutExpired:
        failure = SandboxLifecycleError(
            stage="docker",
            reason="sandbox_operation_timeout",
            message="Docker 沙箱生命周期操作超时。",
        )
    except SandboxLifecycleError as exc:
        failure = exc
    finally:
        if cleanup_required:
            try:
                removed = await run_command(
                    ["docker", "rm", "--force", container_name], 4
                )
                released = removed.returncode == 0
            except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
                released = False
            if not released and failure is None:
                failure = SandboxLifecycleError(
                    stage="release",
                    reason="sandbox_release_failed",
                    message="项目命令已结束，但临时容器未能确认销毁。",
                )

    if failure is not None:
        return {
            "command_completed": False,
            "stage": failure.stage,
            "reason": failure.reason,
            "timed_out": failure.reason == "project_command_timeout",
            "timeout_seconds": timeout_seconds,
            "released": released,
            "message": failure.message,
        }
    assert command_result is not None
    assert exit_code is not None
    stdout = command_result.stdout
    stderr = command_result.stderr
    return {
        "command_completed": True,
        "container_path": SANDBOX_WORKSPACE_PATH,
        "command": normalized_command,
        "timeout_seconds": timeout_seconds,
        "timed_out": False,
        "exit_code": exit_code,
        "stdout": stdout[:12000],
        "stderr": stderr[:12000],
        "stdout_truncated": len(stdout) > 12000,
        "stderr_truncated": len(stderr) > 12000,
        "released": released,
        "message": "项目命令已在临时 Docker 沙箱中结束，容器已销毁。",
    }
