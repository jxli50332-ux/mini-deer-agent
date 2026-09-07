"""创建 FastAPI 应用并管理后端资源的完整生命周期。"""

import logging
import sys
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import cast

from fastapi import FastAPI
from langgraph.checkpoint.base import BaseCheckpointSaver

from mini_deer_agent.application import (
    ConversationHistoryService,
    ConversationRepository,
    RunExecutionManager,
    RunEventHistoryService,
    RunEventStore,
    RunStreamService,
    ThreadCheckpointStore,
    ThreadLifecycleService,
)
from mini_deer_agent.application.workspaces import (
    ProjectFileAccessResolver,
    ProjectRepositoryProvider,
    ProjectService,
    ProjectThreadRepository,
    ProjectThreadService,
)
from mini_deer_agent.core import Settings
from mini_deer_agent.mcp import McpRuntime, initialize_mcp_runtime
from mini_deer_agent.persistence import (
    open_async_sqlite_checkpointer,
    open_async_sqlite_conversation_repository,
)
from mini_deer_agent.server.routers import health, mcp, projects, runs, threads
from mini_deer_agent.tools import get_reserved_agent_tool_names
from mini_deer_agent.workspace.paths import ProjectRootPolicy
from mini_deer_agent.workspace.picker import NativeDirectoryPicker


def _configure_logging() -> None:
    """把 mini_deer_agent 的 INFO 日志接入 stderr，用于排查 Agent 执行流。

    uvicorn 只配置自己的 logger，不会自动提升应用 logger 的级别；
    这里显式把应用日志设为 INFO，并避免重复添加 handler。
    """
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    app_logger = logging.getLogger("mini_deer_agent")
    app_logger.setLevel(logging.INFO)
    if not app_logger.handlers:
        app_logger.addHandler(handler)
    app_logger.propagate = False


type SettingsFactory = Callable[[], Settings]
type CheckpointerContextFactory = Callable[
    [str],
    AbstractAsyncContextManager[BaseCheckpointSaver],
]
type ConversationRepositoryContextFactory = Callable[
    [str],
    AbstractAsyncContextManager[ConversationRepository],
]
type RunStreamServiceFactory = Callable[
    [BaseCheckpointSaver, ConversationRepository],
    RunStreamService,
]
type RunExecutionManagerFactory = Callable[
    [RunStreamService, ConversationRepository],
    RunExecutionManager,
]
type ConversationHistoryServiceFactory = Callable[
    [ConversationRepository],
    ConversationHistoryService,
]
type McpRuntimeFactory = Callable[..., Awaitable[McpRuntime]]


def create_lifespan(
    *,
    settings_factory: SettingsFactory,
    checkpointer_context_factory: CheckpointerContextFactory,
    conversation_repository_context_factory: ConversationRepositoryContextFactory,
    run_stream_service_factory: RunStreamServiceFactory | None,
    run_execution_manager_factory: RunExecutionManagerFactory,
    conversation_history_service_factory: ConversationHistoryServiceFactory,
    mcp_runtime_factory: McpRuntimeFactory,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """组合可替换的启动依赖，供生产应用和离线测试复用。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """启动时创建共享资源，关闭时按相反顺序释放。"""
        settings = settings_factory()
        async with checkpointer_context_factory(
            str(settings.checkpoint_database_path)
        ) as checkpointer:
            async with conversation_repository_context_factory(
                str(settings.application_database_path)
            ) as conversation_repository:
                mcp_runtime = await mcp_runtime_factory(
                    settings.mcp_config_path,
                    timeout_seconds=settings.mcp_server_init_timeout_seconds,
                    reserved_tool_names=get_reserved_agent_tool_names(),
                )
                # 路由只能经 dependencies 模块取得服务，不能自行构建模型或数据库连接。
                app.state.settings = settings
                app.state.mcp_runtime = mcp_runtime
                # 登记权限是独立管理配置；未配置时保持关闭，不影响普通聊天。
                app.state.project_service = None
                app.state.project_thread_service = None
                app.state.directory_picker = None
                workspace_policy = None
                if settings.workspace_allowed_roots:
                    workspace_policy = ProjectRootPolicy(
                        allowed_roots=settings.workspace_allowed_roots,
                        blocked_roots=(
                            settings.application_database_path.resolve().parent,
                            settings.checkpoint_database_path.resolve().parent,
                        ),
                    )
                    app.state.project_service = ProjectService(
                        cast(ProjectRepositoryProvider, conversation_repository).projects,
                        workspace_policy,
                    )
                    app.state.project_thread_service = ProjectThreadService(
                        app.state.project_service,
                        cast(ProjectThreadRepository, conversation_repository),
                    )
                    app.state.directory_picker = NativeDirectoryPicker(
                        settings.workspace_allowed_roots[0]
                    )
                run_stream_service = (
                    run_stream_service_factory(
                        checkpointer,
                        conversation_repository,
                    )
                    if run_stream_service_factory is not None
                    else RunStreamService(
                        checkpointer,
                        memory_store=conversation_repository,
                        mcp_tools=mcp_runtime.tools,
                        file_access_resolver=ProjectFileAccessResolver(
                            conversation_repository,
                            app.state.project_service,
                            workspace_policy,
                        ),
                    )
                )
                run_execution_manager = run_execution_manager_factory(
                    run_stream_service,
                    conversation_repository,
                )
                app.state.run_stream_service = run_stream_service
                app.state.run_execution_manager = run_execution_manager
                app.state.conversation_history_service = (
                    conversation_history_service_factory(
                        conversation_repository
                    )
                )
                app.state.thread_lifecycle_service = ThreadLifecycleService(
                    conversation_repository,
                    cast(ThreadCheckpointStore, checkpointer),
                )
                # Event Store 与产品历史共享物理 SQLite，但通过独立应用服务暴露，
                # 未来替换存储后端时 Router 不需要感知具体适配器。
                app.state.run_event_history_service = RunEventHistoryService(
                    cast(RunEventStore, conversation_repository)
                )
                try:
                    yield
                finally:
                    # 先等待后台 Run 收束，再关闭它们仍会访问的两个 SQLite 资源。
                    await run_execution_manager.shutdown()
                    del app.state.project_thread_service
                    del app.state.project_service
                    del app.state.directory_picker
                    del app.state.run_event_history_service
                    del app.state.thread_lifecycle_service
                    del app.state.conversation_history_service
                    del app.state.run_execution_manager
                    del app.state.run_stream_service
                    del app.state.mcp_runtime
                    del app.state.settings

    return lifespan


def create_app(
    *,
    settings_factory: SettingsFactory = Settings,
    checkpointer_context_factory: CheckpointerContextFactory = (
        open_async_sqlite_checkpointer
    ),
    conversation_repository_context_factory: ConversationRepositoryContextFactory = (
        open_async_sqlite_conversation_repository
    ),
    run_stream_service_factory: RunStreamServiceFactory | None = None,
    run_execution_manager_factory: RunExecutionManagerFactory = (
        RunExecutionManager
    ),
    conversation_history_service_factory: ConversationHistoryServiceFactory = (
        ConversationHistoryService
    ),
    mcp_runtime_factory: McpRuntimeFactory = initialize_mcp_runtime,
) -> FastAPI:
    """创建带版本化路由和可注入生命周期资源的 FastAPI 应用。"""
    _configure_logging()
    application = FastAPI(
        title="Mini Deer Agent API",
        description="Mini Deer Agent 的版本化运行与流式事件接口。",
        version="0.1.0",
        lifespan=create_lifespan(
            settings_factory=settings_factory,
            checkpointer_context_factory=checkpointer_context_factory,
            conversation_repository_context_factory=(
                conversation_repository_context_factory
            ),
            run_stream_service_factory=run_stream_service_factory,
            run_execution_manager_factory=run_execution_manager_factory,
            conversation_history_service_factory=(
                conversation_history_service_factory
            ),
            mcp_runtime_factory=mcp_runtime_factory,
        ),
    )

    # 正式路由和兼容路由集中在工厂注册，避免模块导入时分散修改全局 app。
    application.include_router(health.router)
    application.include_router(mcp.router)
    application.include_router(projects.router)
    application.include_router(threads.router)
    application.include_router(runs.router)
    application.include_router(health.legacy_router)
    application.include_router(runs.legacy_router)
    return application


# Uvicorn 使用稳定的 `mini_deer_agent.api:app`，内部应用仍由工厂统一创建。
app = create_app()
