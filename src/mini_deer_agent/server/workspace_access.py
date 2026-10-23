"""本地学习模式的项目入口：无需密码，保留连接来源与允许目录检查。"""

from ipaddress import ip_address
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response

from mini_deer_agent.core import Settings


def _local_host(value: str) -> bool:
    """只接受明确的回环主机名；不解析 DNS，也不相信转发头。"""
    try:
        parsed = urlsplit(f"http://{value}")
        return (
            parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            and parsed.username is None
            and parsed.password is None
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
            and (parsed.port is None or 1 <= parsed.port <= 65535)
        )
    except ValueError:
        return False


def require_workspace_access(
    request: Request,
    response: Response,
) -> None:
    """页面可直接加载项目；本地来源检查不引入用户连接或解锁操作。"""
    settings: Settings | None = getattr(request.app.state, "settings", None)
    if (
        settings is None
        or not settings.workspace_allowed_roots
    ):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "workspace_not_configured",
                "message": "请先配置允许访问的本地目录。",
            },
        )
    require_local_request(request, response)


def require_local_request(request: Request, response: Response) -> None:
    """数据库附件和工作区入口共用回环来源检查，附件不依赖文件目录配置。"""
    try:
        local_peer = (
            request.client is not None and ip_address(request.client.host).is_loopback
        )
    except ValueError:
        local_peer = False
    host = request.headers.get("host", "")
    origin = request.headers.get("origin")
    # Vite 开发和预览都使用固定回环端口；后端 Swagger 允许请求自己的同源接口。
    allowed_origins = {f"{request.url.scheme}://{host}"} | {
        f"http://{hostname}:{port}"
        for hostname in ("localhost", "127.0.0.1", "[::1]")
        for port in (5173, 4173)
    }
    if (
        not local_peer
        or not _local_host(host)
        or len(request.headers.getlist("host")) != 1
        or len(request.headers.getlist("origin")) > 1
        or (origin is not None and origin not in allowed_origins)
        or request.headers.get("sec-fetch-site") == "cross-site"
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "workspace_access_denied",
                "message": "本地工作区访问校验失败。",
            },
        )
    # 路径元数据不得被浏览器或中间代理缓存。
    response.headers["Cache-Control"] = "no-store"
