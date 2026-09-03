"""集中定义 HTTP 路由使用的 FastAPI 依赖。"""

from typing import cast

from fastapi import HTTPException, Request, status

from mini_deer_agent.application import (
    ConversationHistoryService,
    RunExecutionManager,
    RunEventHistoryService,
    RunStreamService,
    ThreadLifecycleService,
)
from mini_deer_agent.mcp import McpRuntime


def get_run_stream_service(request: Request) -> RunStreamService:
    """从应用生命周期状态取得 run service，未就绪时返回 503。"""
    service = getattr(request.app.state, "run_stream_service", None)
    if service is None:
        # 服务缺失说明启动尚未完成或资源已关闭，不能退回到请求内临时创建资源。
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_not_ready",
                "message": "Run stream service is not ready",
            },
        )
    return cast(RunStreamService, service)


def get_run_execution_manager(request: Request) -> RunExecutionManager:
    """取得应用级后台 Run 管理器，禁止路由临时创建 Task 注册表。"""
    manager = getattr(request.app.state, "run_execution_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_not_ready",
                "message": "Run execution manager is not ready",
            },
        )
    return cast(RunExecutionManager, manager)


def get_conversation_history_service(
    request: Request,
) -> ConversationHistoryService:
    """从应用生命周期取得历史查询服务，未就绪时返回 503。"""
    service = getattr(request.app.state, "conversation_history_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_not_ready",
                "message": "Conversation history service is not ready",
            },
        )
    return cast(ConversationHistoryService, service)


def get_thread_lifecycle_service(request: Request) -> ThreadLifecycleService:
    """取得跨业务库与 Checkpointer 的 Thread 生命周期服务。"""
    service = getattr(request.app.state, "thread_lifecycle_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_not_ready",
                "message": "Thread lifecycle service is not ready",
            },
        )
    return cast(ThreadLifecycleService, service)


def get_run_event_history_service(request: Request) -> RunEventHistoryService:
    """取得 Event Store 查询服务，未就绪时返回稳定 503。"""
    service = getattr(request.app.state, "run_event_history_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_not_ready",
                "message": "Run event history service is not ready",
            },
        )
    return cast(RunEventHistoryService, service)


def get_mcp_runtime(request: Request) -> McpRuntime:
    """取得应用启动时冻结的 MCP 工具与状态快照。"""
    runtime = getattr(request.app.state, "mcp_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_not_ready",
                "message": "MCP runtime is not ready",
            },
        )
    return cast(McpRuntime, runtime)
