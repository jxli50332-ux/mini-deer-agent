"""验证项目沙箱挂载工具只使用构图时冻结的 Project 根。"""

import asyncio
import json
from dataclasses import dataclass

from mini_deer_agent.domain.workspaces import FileAccessScope
from mini_deer_agent.tools import project_sandbox
from mini_deer_agent.tools.project_sandbox import create_project_sandbox_tools


@dataclass
class FakeAccess:
    scope: FileAccessScope
    validations: int = 0

    def list_files(self, *, path: str = "", limit: int = 200) -> dict:
        self.validations += 1
        return {"path": path, "items": [], "limit": limit}


def test_project_sandbox_tool_uses_frozen_root_without_arguments(
    tmp_path, monkeypatch
) -> None:
    """模型 schema 不含路径，工具调用前复核绑定并传入冻结根。"""
    captured = []
    access = FakeAccess(
        FileAccessScope(
            source="project",
            target_path=str(tmp_path),
            target_identity="identity",
            target_kind="directory",
            project_id="project-1",
        )
    )
    monkeypatch.setattr(
        project_sandbox,
        "verify_docker_project_mount",
        lambda path: captured.append(path)
        or {
            "mount_ready": True,
            "entries": ["README.md"],
            "released": True,
            "message": "完成。",
        },
    )

    tool, _command_tool = create_project_sandbox_tools(access)
    result = json.loads(tool.invoke({}))

    assert tool.args_schema.model_json_schema().get("required", []) == []
    assert captured == [tmp_path]
    assert access.validations == 1
    assert result["mount_ready"] is True
    assert result["released"] is True


def test_non_project_scope_does_not_receive_mount_tool(tmp_path) -> None:
    """普通 Thread 与明确路径 Scope 不获得单项目根挂载工具。"""
    explicit = FakeAccess(
        FileAccessScope(
            source="explicit",
            target_path=str(tmp_path),
            target_identity="identity",
            target_kind="directory",
        )
    )

    assert create_project_sandbox_tools(explicit) == ()


def test_project_command_tool_returns_bound_container_result(
    tmp_path, monkeypatch
) -> None:
    """命令工具只接收说明和命令，项目根仍来自冻结 Scope。"""
    captured = []
    access = FakeAccess(
        FileAccessScope(
            source="project",
            target_path=str(tmp_path),
            target_identity="identity",
            target_kind="directory",
            project_id="project-1",
        )
    )
    monkeypatch.setattr(
        project_sandbox,
        "run_docker_project_command",
        lambda path, command, **kwargs: captured.append((path, command, kwargs))
        or {
            "command_completed": True,
            "exit_code": 0,
            "stdout": "ok\n",
            "stderr": "",
            "released": True,
        },
    )

    _inspect_tool, command_tool = create_project_sandbox_tools(access)
    result = json.loads(
        command_tool.invoke(
            {"description": "运行入口", "command": "python src/main.py"}
        )
    )

    assert command_tool.args_schema.model_json_schema()["required"] == [
        "description",
        "command",
    ]
    assert captured == [
        (tmp_path, "python src/main.py", {"timeout_seconds": 30})
    ]
    assert result["exit_code"] == 0
    assert result["released"] is True


def test_async_project_command_tool_propagates_cancellation(
    tmp_path, monkeypatch
) -> None:
    """异步工具不吞掉 Run 取消，底层回收完成后取消继续向上层传播。"""
    access = FakeAccess(
        FileAccessScope(
            source="project",
            target_path=str(tmp_path),
            target_identity="identity",
            target_kind="directory",
            project_id="project-1",
        )
    )

    async def scenario() -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def run_until_cancelled(*_args: object, **_kwargs: object) -> dict:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        monkeypatch.setattr(
            project_sandbox,
            "run_docker_project_command_async",
            run_until_cancelled,
        )
        _inspect_tool, command_tool = create_project_sandbox_tools(access)
        task = asyncio.create_task(
            command_tool.ainvoke(
                {
                    "description": "等待后停止",
                    "command": "sleep 30",
                    "timeout_seconds": 60,
                }
            )
        )
        await started.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("取消没有从异步命令工具向上传播")
        assert cancelled.is_set()

    asyncio.run(scenario())
    assert access.validations == 1
