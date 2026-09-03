"""发现 MCP 工具，并生成供 Agent 与状态接口共享的启动快照。"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from langchain_core.tools import BaseTool

from mini_deer_agent.mcp.config import load_mcp_configuration


logger = logging.getLogger(__name__)
_SAFE_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_ERROR_LENGTH = 1000


class McpToolClient(Protocol):
    """隔离上游适配器，便于测试每个服务器的发现行为。"""

    async def get_tools(self, *, server_name: str) -> list[BaseTool]: ...


type McpClientFactory = Callable[..., McpToolClient]


@dataclass(frozen=True, slots=True)
class McpServerStatus:
    """一个服务器在当前进程启动快照中的可观测状态。"""

    name: str
    transport: Literal["stdio", "http"]
    state: Literal["disabled", "loaded", "failed"]
    tool_names: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class McpRuntime:
    """MCP 工具与状态必须来自同一次发现，避免接口和 Agent 漂移。"""

    configured: bool
    config_path: Path
    tools: tuple[BaseTool, ...]
    servers: tuple[McpServerStatus, ...]

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self.tools)


def _default_client_factory(
    connections: dict[str, dict[str, object]],
    *,
    tool_name_prefix: bool,
) -> McpToolClient:
    """在真正配置 MCP 时才导入可选协议适配器。"""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    return MultiServerMCPClient(
        connections,
        tool_name_prefix=tool_name_prefix,
    )


def _bounded_error(exc: BaseException) -> str:
    rendered = str(exc).strip() or type(exc).__name__
    return rendered[:_MAX_ERROR_LENGTH]


async def _discover_server_tools(
    client: McpToolClient,
    server_name: str,
    timeout_seconds: float,
) -> tuple[BaseTool, ...] | BaseException:
    try:
        tools = await asyncio.wait_for(
            client.get_tools(server_name=server_name),
            timeout=timeout_seconds,
        )
        return tuple(tools)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
            raise
        return exc


def _validate_server_tools(
    server_name: str,
    tools: tuple[BaseTool, ...],
    *,
    unavailable_names: set[str],
) -> str | None:
    names: set[str] = set()
    for tool in tools:
        name = tool.name
        if not _SAFE_TOOL_NAME.fullmatch(name or ""):
            return f"MCP tool {name!r} from server {server_name!r} has an unsafe name"
        if name in names:
            return f"MCP server {server_name!r} returned duplicate tool name {name!r}"
        if name in unavailable_names:
            return f"MCP tool {name!r} from server {server_name!r} conflicts with an existing tool"
        names.add(name)
    return None


def _add_sync_invocation(tool: BaseTool) -> None:
    """让现有同步学习入口也能调用上游只提供 coroutine 的 MCP 工具。"""
    coroutine = getattr(tool, "coroutine", None)
    if getattr(tool, "func", None) is not None or not callable(coroutine):
        return

    def invoke_sync(**kwargs: object) -> object:
        async def invoke() -> object:
            return await coroutine(**kwargs)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(invoke())

        # 同步调用若发生在已有事件循环线程，必须换线程运行完整的短生命周期 session。
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, invoke()).result()

    tool.func = invoke_sync


async def initialize_mcp_runtime(
    config_path: Path,
    *,
    timeout_seconds: float = 10.0,
    client_factory: McpClientFactory = _default_client_factory,
    reserved_tool_names: Collection[str] = (),
) -> McpRuntime:
    """并行发现所有启用服务器；单服务器失败不会阻止应用启动。"""
    loaded = load_mcp_configuration(config_path)
    server_items = tuple(loaded.configuration.mcp_servers.items())
    enabled_items = tuple(
        (name, config) for name, config in server_items if config.enabled
    )
    if not enabled_items:
        return McpRuntime(
            configured=loaded.configured,
            config_path=loaded.path,
            tools=(),
            servers=tuple(
                McpServerStatus(
                    name=name,
                    transport=config.transport,
                    state="disabled",
                )
                for name, config in server_items
            ),
        )

    connections = {
        name: config.connection for name, config in enabled_items
    }
    try:
        client = client_factory(connections, tool_name_prefix=True)
    except Exception as exc:
        error = _bounded_error(exc)
        statuses = tuple(
            McpServerStatus(
                name=name,
                transport=config.transport,
                state="failed" if config.enabled else "disabled",
                error=error if config.enabled else None,
            )
            for name, config in server_items
        )
        return McpRuntime(
            configured=loaded.configured,
            config_path=loaded.path,
            tools=(),
            servers=statuses,
        )

    discoveries = await asyncio.gather(
        *(
            _discover_server_tools(client, name, timeout_seconds)
            for name, _config in enabled_items
        )
    )
    discovered_by_name = {
        name: result
        for (name, _config), result in zip(
            enabled_items,
            discoveries,
            strict=True,
        )
    }
    accepted_tools: list[BaseTool] = []
    unavailable_names = set(reserved_tool_names)
    statuses: list[McpServerStatus] = []
    for name, config in server_items:
        if not config.enabled:
            statuses.append(
                McpServerStatus(
                    name=name,
                    transport=config.transport,
                    state="disabled",
                )
            )
            continue
        result = discovered_by_name[name]
        if isinstance(result, BaseException):
            error = _bounded_error(result)
            logger.warning("MCP server %s discovery failed: %s", name, error)
            statuses.append(
                McpServerStatus(
                    name=name,
                    transport=config.transport,
                    state="failed",
                    error=error,
                )
            )
            continue
        validation_error = _validate_server_tools(
            name,
            result,
            unavailable_names=unavailable_names,
        )
        if validation_error is not None:
            logger.warning(validation_error)
            statuses.append(
                McpServerStatus(
                    name=name,
                    transport=config.transport,
                    state="failed",
                    error=validation_error,
                )
            )
            continue
        tool_names = tuple(tool.name for tool in result)
        for tool in result:
            _add_sync_invocation(tool)
        unavailable_names.update(tool_names)
        accepted_tools.extend(result)
        statuses.append(
            McpServerStatus(
                name=name,
                transport=config.transport,
                state="loaded",
                tool_names=tool_names,
            )
        )

    return McpRuntime(
        configured=loaded.configured,
        config_path=loaded.path,
        tools=tuple(accepted_tools),
        servers=tuple(statuses),
    )
