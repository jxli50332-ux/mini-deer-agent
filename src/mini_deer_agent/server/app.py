"""创建 FastAPI 应用并管理后端资源的完整生命周期。"""

from collections.abc import Callable
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
from mini_deer_agent.core import Settings
from mini_deer_agent.persistence import (
    open_async_sqlite_checkpointer,
    open_async_sqlite_conversation_repository,
)
from mini_deer_agent.server.routers import health, runs, threads


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


def create_lifespan(
    *,
    settings_factory: SettingsFactory,
    checkpointer_context_factory: CheckpointerContextFactory,
    conversation_repository_context_factory: ConversationRepositoryContextFactory,
    run_stream_service_factory: RunStreamServiceFactory,
    run_execution_manager_factory: RunExecutionManagerFactory,
    conversation_history_service_factory: ConversationHistoryServiceFactory,
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
                # 路由只能经 dependencies 模块取得服务，不能自行构建模型或数据库连接。
                app.state.settings = settings
                run_stream_service = run_stream_service_factory(
                    checkpointer,
                    conversation_repository,
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
                    del app.state.run_event_history_service
                    del app.state.thread_lifecycle_service
                    del app.state.conversation_history_service
                    del app.state.run_execution_manager
                    del app.state.run_stream_service
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
    run_stream_service_factory: RunStreamServiceFactory = (
        lambda checkpointer, _repository: RunStreamService(checkpointer)
    ),
    run_execution_manager_factory: RunExecutionManagerFactory = (
        RunExecutionManager
    ),
    conversation_history_service_factory: ConversationHistoryServiceFactory = (
        ConversationHistoryService
    ),
) -> FastAPI:
    """创建带版本化路由和可注入生命周期资源的 FastAPI 应用。"""
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
        ),
    )

    # 正式路由和兼容路由集中在工厂注册，避免模块导入时分散修改全局 app。
    application.include_router(health.router)
    application.include_router(threads.router)
    application.include_router(runs.router)
    application.include_router(health.legacy_router)
    application.include_router(runs.legacy_router)
    return application


# Uvicorn 使用稳定的 `mini_deer_agent.api:app`，内部应用仍由工厂统一创建。
app = create_app()
