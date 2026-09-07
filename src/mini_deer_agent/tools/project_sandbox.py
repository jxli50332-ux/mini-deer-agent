"""为可信 Project Scope 创建固定的 Docker 挂载诊断工具。"""

import asyncio
import json
from pathlib import Path
from typing import Protocol

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from mini_deer_agent.domain.workspaces import FileAccessScope, ProjectError
from mini_deer_agent.sandbox import (
    run_docker_project_command,
    run_docker_project_command_async,
    verify_docker_project_mount,
)


class ProjectMountAccess(Protocol):
    """挂载诊断只依赖冻结 Scope 与一次绑定复核。"""

    scope: FileAccessScope

    def list_files(self, *, path: str = "", limit: int = 200) -> dict:
        """复核当前绑定并读取项目根。"""


class ProjectCommandInput(BaseModel):
    """模型只提供说明和容器内命令，宿主路径由可信 Scope 绑定。"""

    description: str = Field(
        min_length=1,
        max_length=200,
        description="面向用户的简短执行说明，例如‘运行 Python 入口’",
    )
    command: str = Field(
        min_length=1,
        max_length=4000,
        description="在容器 `/workspace` 中执行的一条非交互 shell 命令",
    )
    timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=60,
        description="命令最长运行秒数，默认 30，范围 1—60",
    )


def create_project_sandbox_tools(
    access: ProjectMountAccess,
) -> tuple[BaseTool, ...]:
    """仅为单一 Project 目录注册不接收参数的挂载诊断。"""
    if access.scope.source != "project" or access.scope.target_kind != "directory":
        return ()

    def inspect_project_sandbox() -> str:
        """把当前项目只读挂载到临时容器，执行固定根目录探针后销毁。"""
        try:
            access.list_files(path="", limit=1)
            result = verify_docker_project_mount(Path(access.scope.target_path))
            return json.dumps(
                {"ok": True, "provider": "docker", **result},
                ensure_ascii=False,
            )
        except ProjectError as exc:
            return json.dumps(
                {
                    "ok": False,
                    "error": {"code": exc.code, "message": exc.message},
                },
                ensure_ascii=False,
            )

    async def inspect_project_sandbox_async() -> str:
        """把阻塞的 Docker 生命周期放到工作线程执行。"""
        return await asyncio.to_thread(inspect_project_sandbox)

    def run_project_command(
        description: str,
        command: str,
        timeout_seconds: int = 30,
    ) -> str:
        """在当前 Project 根的一次性容器中执行一条非交互命令。"""
        del description
        try:
            access.list_files(path="", limit=1)
            result = run_docker_project_command(
                Path(access.scope.target_path),
                command,
                timeout_seconds=timeout_seconds,
            )
            return json.dumps(
                {"ok": True, "provider": "docker", **result},
                ensure_ascii=False,
            )
        except ProjectError as exc:
            return json.dumps(
                {
                    "ok": False,
                    "error": {"code": exc.code, "message": exc.message},
                },
                ensure_ascii=False,
            )

    async def run_project_command_async(
        description: str,
        command: str,
        timeout_seconds: int = 30,
    ) -> str:
        """异步等待 Docker 命令，并把 Run 取消传递到容器回收流程。"""
        del description
        try:
            await asyncio.to_thread(access.list_files, path="", limit=1)
            result = await run_docker_project_command_async(
                Path(access.scope.target_path),
                command,
                timeout_seconds=timeout_seconds,
            )
            return json.dumps(
                {"ok": True, "provider": "docker", **result},
                ensure_ascii=False,
            )
        except ProjectError as exc:
            return json.dumps(
                {
                    "ok": False,
                    "error": {"code": exc.code, "message": exc.message},
                },
                ensure_ascii=False,
            )

    return (
        StructuredTool.from_function(
            func=inspect_project_sandbox,
            coroutine=inspect_project_sandbox_async,
            name="inspect_project_sandbox",
            description=(
                "验证当前 Project 是否能只读挂载到 Docker 临时沙箱。"
                "工具只读取最多 50 个项目根条目，随后销毁容器；不接受命令或路径参数。"
            ),
        ),
        StructuredTool.from_function(
            func=run_project_command,
            coroutine=run_project_command_async,
            name="run_project_command",
            description=(
                "在当前 Project 的临时 Docker 沙箱中执行一条非交互命令，"
                "返回真实退出码及有界 stdout/stderr，并在结束后销毁容器。"
            ),
            args_schema=ProjectCommandInput,
        ),
    )
