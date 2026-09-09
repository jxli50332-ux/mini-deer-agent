"""集中定义 HTTP 路由使用的 FastAPI 依赖。"""

from typing import cast

from fastapi import HTTPException, Request, status

from mini_deer_agent.application import (
    ConversationHistoryService,
    BenchmarkService,
    RunExecutionManager,
    RunEventHistoryService,
    RunStreamService,
    ThreadLifecycleService,
    GoalStateService,
)
from mini_deer_agent.mcp import McpRuntime
from mini_deer_agent.skills import UserSkillManager
from mini_deer_agent.application.workspaces import ProjectService, ProjectThreadService
from mini_deer_agent.workspace.picker import DirectoryPicker


def get_project_service(request: Request) -> ProjectService:
    """取得项目应用服务，禁止请求内临时打开数据库或放宽目录配置。"""
    service = getattr(request.app.state, "project_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail={
            "code": "workspace_not_configured", "message": "项目服务尚未启用。",
        })
    return cast(ProjectService, service)


def get_project_thread_service(request: Request) -> ProjectThreadService:
    """取得项目会话应用服务；配置关闭时不能退回普通 Thread 接口猜测归属。"""
    service = getattr(request.app.state, "project_thread_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "workspace_not_configured",
                "message": "项目服务尚未启用。",
            },
        )
    return cast(ProjectThreadService, service)


def get_directory_picker(request: Request) -> DirectoryPicker:
    """取得生命周期创建的本机选择器；请求不能指定启动程序或初始目录。"""
    picker = getattr(request.app.state, "directory_picker", None)
    if picker is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "directory_picker_unavailable",
                "message": "本机文件夹选择器当前不可用。",
            },
        )
    return cast(DirectoryPicker, picker)


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


def get_benchmark_service(request: Request) -> BenchmarkService:
    """取得固定能力基准服务，未就绪时失败关闭。"""
    service = getattr(request.app.state, "benchmark_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "service_not_ready", "message": "Benchmark service is not ready"},
        )
    return cast(BenchmarkService, service)


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


def get_user_skill_manager(request: Request) -> UserSkillManager:
    """取得本地用户 Skill 管理器，未就绪时返回稳定 503。"""
    manager = getattr(request.app.state, "user_skill_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_not_ready",
                "message": "User skill manager is not ready",
            },
        )
    return cast(UserSkillManager, manager)


def get_goal_state_service(request: Request) -> GoalStateService:
    """取得线程 Goal checkpoint 服务，未就绪时返回稳定 503。"""
    service = getattr(request.app.state, "goal_state_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_not_ready",
                "message": "Goal state service is not ready",
            },
        )
    return cast(GoalStateService, service)
