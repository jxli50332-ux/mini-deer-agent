"""验证 FastAPI 应用工厂、探针语义和资源生命周期。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import importlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mini_deer_agent.api import app
from mini_deer_agent.agents.middleware import (
    RunOutputStore,
    ToolOutputBudgetPolicy,
)
from mini_deer_agent.core import Settings
from mini_deer_agent.mcp import McpRuntime, McpServerStatus
from mini_deer_agent.server import create_app


server_app_module = importlib.import_module("mini_deer_agent.server.app")


def test_default_app_can_be_imported() -> None:
    """稳定 ASGI 入口应继续导出 FastAPI 实例。"""
    assert isinstance(app, FastAPI)


def test_openapi_exposes_only_versioned_public_contract() -> None:
    """旧兼容端点应继续可用，但不能再引导新客户端依赖旧路径。"""
    documented_paths = set(app.openapi()["paths"])

    assert documented_paths == {
        "/api/v1/benchmarks/cases",
        "/api/v1/benchmarks/attempts",
        "/api/v1/benchmarks/attempts/{run_id}",
            "/api/v1/benchmarks/attempts/{run_id}/score",
            "/api/v1/benchmarks/regression",
        "/api/v1/health",
        "/api/v1/attachments/{message_id}/{position}/download",
        "/api/v1/mcp/status",
        "/api/v1/office/documents",
        "/api/v1/office/documents/text-preview",
        "/api/v1/office/documents/text-download",
        "/api/v1/office/documents/{filename}/preview",
        "/api/v1/office/documents/{filename}/download",
        "/api/v1/models",
        "/api/v1/models/{name}/probe",
        "/api/v1/projects",
        "/api/v1/projects/pick-directory",
        "/api/v1/projects/{project_id}",
        "/api/v1/projects/{project_id}/threads",
        "/api/v1/projects/{project_id}/directory",
        "/api/v1/projects/{project_id}/file",
        "/api/v1/ready",
        "/api/v1/skills",
        "/api/v1/skills/agent-settings",
        "/api/v1/skills/recoverable",
        "/api/v1/settings/model-selection",
        "/api/v1/skill-market/catalog",
        "/api/v1/skill-market/providers",
        "/api/v1/skill-market/refresh",
        "/api/v1/skill-market/items/{provider}/{owner}/{slug}",
        "/api/v1/skill-market/items/{provider}/{owner}/{slug}/versions",
        "/api/v1/skill-market/items/{provider}/{owner}/{slug}/preview",
        "/api/v1/skill-market/items/{provider}/{owner}/{slug}/install",
        "/api/v1/skill-market/items/{provider}/{owner}/{slug}/update",
        "/api/v1/skill-market/items/{provider}/{owner}/{slug}/installation",
        "/api/v1/skill-market/items/{provider}/{owner}/{slug}/rollback",
        "/api/v1/skills/drafts",
        "/api/v1/skills/drafts/{draft_id}",
        "/api/v1/skills/drafts/{draft_id}/check",
        "/api/v1/skills/drafts/{draft_id}/install",
        "/api/v1/skills/install-authorizations",
        "/api/v1/skills/import",
        "/api/v1/skills/install",
        "/api/v1/skills/{name}",
        "/api/v1/skills/{name}/history",
        "/api/v1/skills/{name}/history/{history_id}",
        "/api/v1/skills/{name}/rollback",
        "/api/v1/threads",
        "/api/v1/threads/{thread_id}",
        "/api/v1/threads/{thread_id}/goal",
        "/api/v1/threads/{thread_id}/goal/resume",
        "/api/v1/threads/{thread_id}/goal/stop",
        "/api/v1/threads/{thread_id}/messages",
        "/api/v1/threads/{thread_id}/runs",
        "/api/v1/threads/{thread_id}/runs/{run_id}",
        "/api/v1/threads/{thread_id}/runs/{run_id}/events",
        "/api/v1/threads/{thread_id}/runs/{run_id}/cancel",
        "/api/v1/threads/{thread_id}/runs/stream",
    }
    assert "/health" not in documented_paths
    assert "/chat/stream" not in documented_paths


def test_health_is_live_without_starting_lifespan() -> None:
    """存活探针不依赖数据库或模型，进程可响应时就应返回成功。"""
    client = TestClient(app)
    try:
        assert client.get("/api/v1/health").json() == {"status": "ok"}
        assert client.get("/health").json() == {"status": "ok"}
        # 未进入 TestClient 上下文时 lifespan 尚未运行，就绪探针必须明确失败。
        assert client.get("/api/v1/ready").status_code == 503
        assert client.get("/api/v1/mcp/status").status_code == 503
    finally:
        client.close()


def test_lifespan_initializes_and_closes_shared_resources_once(
    tmp_path: Path,
) -> None:
    """应用启动和关闭应各操作一次 checkpointer，并在期间暴露 run service。"""
    database_path = tmp_path / "lifespan.sqlite"
    lifecycle_events: list[str] = []
    fake_checkpointer = object()
    fake_service = object()
    fake_repository = object()

    @asynccontextmanager
    async def open_fake_checkpointer(path: str) -> AsyncIterator[object]:
        """记录资源开关顺序，避免本测试依赖真实 SQLite。"""
        lifecycle_events.append(f"open:{path}")
        yield fake_checkpointer
        lifecycle_events.append("close")

    @asynccontextmanager
    async def open_fake_conversation_repository(
        path: str,
    ) -> AsyncIterator[object]:
        """记录业务数据库在 checkpointer 内层打开并优先关闭。"""
        lifecycle_events.append(f"open-history:{path}")
        yield fake_repository
        lifecycle_events.append("close-history")

    def create_fake_service(
        checkpointer: object,
        repository: object,
    ) -> object:
        """确认 application service 使用 lifespan 创建的同一个资源。"""
        assert checkpointer is fake_checkpointer
        assert repository is fake_repository
        lifecycle_events.append("service")
        return fake_service

    settings = Settings(
        checkpoint_database_path=database_path,
        application_database_path=tmp_path / "application.sqlite",
        user_skills_directory=tmp_path / "skills",
        mcp_config_path=tmp_path / "missing-mcp.json",
        _env_file=None,
    )
    application = create_app(
        settings_factory=lambda: settings,
        checkpointer_context_factory=open_fake_checkpointer,
        conversation_repository_context_factory=(
            open_fake_conversation_repository
        ),
        run_stream_service_factory=create_fake_service,
    )

    assert not hasattr(application.state, "run_stream_service")
    assert not hasattr(application.state, "mcp_runtime")
    with TestClient(application) as client:
        assert lifecycle_events == [
            f"open:{database_path}",
            f"open-history:{settings.application_database_path}",
            "service",
        ]
        assert application.state.run_stream_service is fake_service
        assert hasattr(application.state, "run_execution_manager")
        assert hasattr(application.state, "conversation_history_service")
        assert hasattr(application.state, "run_event_history_service")
        assert application.state.mcp_runtime.tools == ()
        assert application.state.user_skill_manager.root == (
            tmp_path / "skills"
        ).resolve()
        assert client.get("/api/v1/ready").json() == {"status": "ready"}
        assert client.get("/api/v1/mcp/status").json() == {
            "configured": False,
            "config_path": str(settings.mcp_config_path.resolve()),
            "tool_names": [],
            "servers": [],
        }

    assert lifecycle_events == [
        f"open:{database_path}",
        f"open-history:{settings.application_database_path}",
        "service",
        "close-history",
        "close",
    ]
    assert not hasattr(application.state, "run_stream_service")
    assert not hasattr(application.state, "run_execution_manager")
    assert not hasattr(application.state, "conversation_history_service")
    assert not hasattr(application.state, "run_event_history_service")
    assert not hasattr(application.state, "mcp_runtime")
    assert not hasattr(application.state, "user_skill_manager")


def test_default_lifespan_injects_configured_tool_output_storage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """冻结模型不应使完整工具输出存储静默退化为有界样本。"""
    captured: dict[str, object] = {}

    class CapturingRunStreamService:
        def __init__(self, checkpointer: object, **kwargs: object) -> None:
            captured["checkpointer"] = checkpointer
            captured.update(kwargs)

    fake_checkpointer = object()
    fake_repository = object()

    @asynccontextmanager
    async def open_fake_checkpointer(_path: str) -> AsyncIterator[object]:
        yield fake_checkpointer

    @asynccontextmanager
    async def open_fake_repository(_path: str) -> AsyncIterator[object]:
        yield fake_repository

    async def create_empty_runtime(*_args, **_kwargs) -> McpRuntime:
        return McpRuntime(
            configured=False,
            config_path=tmp_path / "mcp.json",
            tools=(),
            servers=(),
        )

    monkeypatch.setattr(
        server_app_module,
        "RunStreamService",
        CapturingRunStreamService,
    )
    output_directory = tmp_path / "private-run-outputs"
    settings = Settings(
        checkpoint_database_path=tmp_path / "checkpoint.sqlite",
        application_database_path=tmp_path / "application.sqlite",
        user_skills_directory=tmp_path / "skills",
        tool_output_directory=output_directory,
        tool_output_max_inline_chars=4_096,
        tool_output_sample_chars=256,
        tool_output_read_chunk_chars=2_048,
        workspace_allowed_roots=(),
        _env_file=None,
    )
    application = create_app(
        settings_factory=lambda: settings,
        checkpointer_context_factory=open_fake_checkpointer,
        conversation_repository_context_factory=open_fake_repository,
        mcp_runtime_factory=create_empty_runtime,
    )

    with TestClient(application):
        store = captured["tool_output_store"]
        policy = captured["tool_output_policy"]
        assert isinstance(store, RunOutputStore)
        assert store.root == output_directory.resolve()
        assert isinstance(policy, ToolOutputBudgetPolicy)
        assert policy.max_inline_chars == 4_096
        assert policy.sample_chars == 256
        assert policy.read_chunk_chars == 2_048


def test_mcp_status_projects_lifespan_runtime_without_secrets(
    tmp_path: Path,
) -> None:
    """状态接口只暴露连接结果与工具名，不回传命令、环境变量或请求头。"""
    runtime = McpRuntime(
        configured=True,
        config_path=(tmp_path / "mcp.json").resolve(),
        tools=(),
        servers=(
            McpServerStatus(
                name="docs",
                transport="http",
                state="loaded",
                tool_names=("docs_search",),
            ),
            McpServerStatus(
                name="broken",
                transport="stdio",
                state="failed",
                error="connection refused",
            ),
        ),
    )

    async def create_runtime(*args, **kwargs) -> McpRuntime:
        return runtime

    application = create_app(mcp_runtime_factory=create_runtime)

    with TestClient(application) as client:
        assert client.get("/api/v1/mcp/status").json() == {
            "configured": True,
            "config_path": str(runtime.config_path),
            "tool_names": [],
            "servers": [
                {
                    "name": "docs",
                    "transport": "http",
                    "state": "loaded",
                    "tool_names": ["docs_search"],
                    "error": None,
                },
                {
                    "name": "broken",
                    "transport": "stdio",
                    "state": "failed",
                    "tool_names": [],
                    "error": "connection refused",
                },
            ],
        }
