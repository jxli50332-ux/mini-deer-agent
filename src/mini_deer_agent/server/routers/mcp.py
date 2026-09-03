"""公开只读 MCP 连接状态，不返回任何配置密钥。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from mini_deer_agent.mcp import McpRuntime
from mini_deer_agent.server.dependencies import get_mcp_runtime
from mini_deer_agent.server.schemas import (
    McpServerStatusResponse,
    McpStatusResponse,
)


router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])


@router.get("/status", response_model=McpStatusResponse)
def get_mcp_status(
    runtime: Annotated[McpRuntime, Depends(get_mcp_runtime)],
) -> McpStatusResponse:
    """投影当前进程的启动快照；修改配置后需要重启应用。"""
    return McpStatusResponse(
        configured=runtime.configured,
        config_path=str(runtime.config_path),
        tool_names=list(runtime.tool_names),
        servers=[
            McpServerStatusResponse(
                name=status.name,
                transport=status.transport,
                state=status.state,
                tool_names=list(status.tool_names),
                error=status.error,
            )
            for status in runtime.servers
        ],
    )
