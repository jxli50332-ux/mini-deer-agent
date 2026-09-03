"""加载 Mini Deer 的本地可信 MCP 服务器配置。"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


_ENV_REFERENCE = re.compile(r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))")
_SAFE_SERVER_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


class McpConfigurationError(ValueError):
    """表示 MCP 配置无法安全地转换为运行时连接。"""


class McpServerConfig(BaseModel):
    """一个受信任的本地 MCP Server 声明。"""

    enabled: bool = True
    transport: Literal["stdio", "http"] = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_transport_fields(self) -> "McpServerConfig":
        # 禁用项只用于保留配置，直到重新启用时才要求连接字段完整。
        if not self.enabled:
            return self
        if self.transport == "stdio":
            if self.command is None or not self.command.strip():
                raise ValueError("stdio transport requires a non-empty command")
            if self.url is not None:
                raise ValueError("stdio transport does not accept url")
        else:
            if self.url is None or not self.url.strip():
                raise ValueError("http transport requires a non-empty url")
            if self.command is not None:
                raise ValueError("http transport does not accept command")
            if self.args:
                raise ValueError("http transport does not accept args")
            if self.env:
                raise ValueError("http transport does not accept env")
        return self

    @property
    def connection(self) -> dict[str, object]:
        """返回 `MultiServerMCPClient` 接受的连接参数。"""
        if self.transport == "stdio":
            connection: dict[str, object] = {
                "transport": "stdio",
                "command": self.command or "",
                "args": list(self.args),
            }
            if self.env:
                connection["env"] = dict(self.env)
            return connection

        connection = {
            "transport": "http",
            "url": self.url or "",
        }
        if self.headers:
            connection["headers"] = dict(self.headers)
        return connection


class McpConfiguration(BaseModel):
    """MCP 配置文件的顶层稳定契约。"""

    mcp_servers: dict[str, McpServerConfig] = Field(
        default_factory=dict,
        alias="mcpServers",
    )
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def _validate_server_names(self) -> "McpConfiguration":
        for name in self.mcp_servers:
            if not _SAFE_SERVER_NAME.fullmatch(name):
                raise ValueError(
                    f"MCP server name {name!r} must match {_SAFE_SERVER_NAME.pattern}"
                )
        return self


@dataclass(frozen=True, slots=True)
class LoadedMcpConfiguration:
    """区分“没有配置文件”和“存在但没有服务器”的加载结果。"""

    path: Path
    configured: bool
    configuration: McpConfiguration


def _resolve_environment_references(
    value: str,
    *,
    environ: Mapping[str, str],
) -> str:
    """替换字符串中的 `$NAME`/`${NAME}`，缺失值直接拒绝启动。"""

    def replace(match: re.Match[str]) -> str:
        name = match.group("braced") or match.group("plain")
        if name not in environ:
            raise McpConfigurationError(
                f"MCP configuration references missing environment variable {name!r}"
            )
        return environ[name]

    return _ENV_REFERENCE.sub(replace, value)


def _resolve_server_secrets(
    raw: object,
    *,
    environ: Mapping[str, str],
) -> object:
    """只解析 env/header 的值，不把命令和 URL 当作模板执行。"""
    if not isinstance(raw, dict):
        return raw
    data = dict(raw)
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return data
    resolved_servers: dict[object, object] = {}
    for server_name, server_value in servers.items():
        if not isinstance(server_value, dict):
            resolved_servers[server_name] = server_value
            continue
        server = dict(server_value)
        if server.get("enabled", True) is False:
            resolved_servers[server_name] = server
            continue
        for field_name in ("env", "headers"):
            values = server.get(field_name)
            if not isinstance(values, dict):
                continue
            server[field_name] = {
                key: _resolve_environment_references(value, environ=environ)
                if isinstance(value, str)
                else value
                for key, value in values.items()
            }
        resolved_servers[server_name] = server
    data["mcpServers"] = resolved_servers
    return data


def load_mcp_configuration(
    path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> LoadedMcpConfiguration:
    """读取一次 MCP 配置；默认文件缺失表示 MCP 未启用。"""
    resolved_path = path.resolve()
    if not resolved_path.exists():
        return LoadedMcpConfiguration(
            path=resolved_path,
            configured=False,
            configuration=McpConfiguration(),
        )
    try:
        raw = json.loads(resolved_path.read_text(encoding="utf-8"))
        resolved = _resolve_server_secrets(
            raw,
            environ=os.environ if environ is None else environ,
        )
        configuration = McpConfiguration.model_validate(resolved)
    except McpConfigurationError:
        raise
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise McpConfigurationError(
            f"Invalid MCP configuration at {resolved_path}: {exc}"
        ) from exc
    return LoadedMcpConfiguration(
        path=resolved_path,
        configured=True,
        configuration=configuration,
    )
