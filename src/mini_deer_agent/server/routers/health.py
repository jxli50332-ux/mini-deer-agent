"""提供存活探针、就绪探针和旧健康检查兼容入口。"""

from fastapi import APIRouter, HTTPException, Request, status


router = APIRouter(prefix="/api/v1", tags=["system"])
legacy_router = APIRouter()


def _health_payload() -> dict[str, str]:
    """返回稳定存活状态，不访问模型或外部 API。"""
    return {"status": "ok"}


@router.get("/health")
def health() -> dict[str, str]:
    """表示 HTTP 进程可以正常处理请求。"""
    return _health_payload()


@router.get("/ready")
def ready(request: Request) -> dict[str, str]:
    """确认 lifespan 已完成并且运行与历史服务都可以接受请求。"""
    if (
        getattr(request.app.state, "run_stream_service", None) is None
        or getattr(request.app.state, "run_execution_manager", None) is None
        or getattr(request.app.state, "conversation_history_service", None)
        is None
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_not_ready",
                "message": "Run stream service is not ready",
            },
        )
    return {"status": "ready"}


@legacy_router.get("/health", include_in_schema=False)
def legacy_health() -> dict[str, str]:
    """兼容已有启动命令和测试；正式客户端应改用 `/api/v1/health`。"""
    return _health_payload()
