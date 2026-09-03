"""MCP 启动快照的只读 HTTP 契约。"""

from typing import Literal

from pydantic import BaseModel


class McpServerStatusResponse(BaseModel):
    name: str
    transport: Literal["stdio", "http"]
    state: Literal["disabled", "loaded", "failed"]
    tool_names: list[str]
    error: str | None


class McpStatusResponse(BaseModel):
    configured: bool
    config_path: str
    tool_names: list[str]
    servers: list[McpServerStatusResponse]
