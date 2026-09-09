"""验证 MCP 配置、工具发现隔离和运行时状态。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from langchain_core.tools import StructuredTool

from mini_deer_agent.mcp import (
    McpConfigurationError,
    initialize_mcp_runtime,
    load_mcp_configuration,
)


def _tool(name: str) -> StructuredTool:
    """创建不访问外部服务的 MCP 工具替身。"""

    def invoke(value: str) -> str:
        return value

    return StructuredTool.from_function(
        invoke,
        name=name,
        description="测试 MCP 工具",
    )


def test_missing_mcp_config_means_not_configured(tmp_path: Path) -> None:
    """默认配置文件不存在时应保持 Agent 可用，而不是启动失败。"""
    path = tmp_path / "missing.json"

    loaded = load_mcp_configuration(path)

    assert loaded.configured is False
    assert loaded.path == path.resolve()
    assert loaded.configuration.mcp_servers == {}


def test_mcp_config_parses_stdio_http_and_environment_references(
    tmp_path: Path,
) -> None:
    """本地与远程服务器使用同一配置文件，敏感值从宿主环境解析。"""
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "local_math": {
                        "transport": "stdio",
                        "command": "python",
                        "args": ["server.py"],
                        "env": {"TOKEN": "$MATH_TOKEN"},
                    },
                    "remote_docs": {
                        "transport": "http",
                        "url": "https://example.invalid/mcp",
                        "headers": {"Authorization": "Bearer ${DOCS_TOKEN}"},
                    },
                    "disabled": {
                        "enabled": False,
                        "transport": "stdio",
                        "command": "ignored",
                    },
                },
                "toolRoutingKeywords": {
                    "local_math_add": ["加法", "add numbers"],
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = load_mcp_configuration(
        path,
        environ={"MATH_TOKEN": "math-secret", "DOCS_TOKEN": "docs-secret"},
    )

    assert loaded.configured is True
    assert loaded.configuration.mcp_servers["local_math"].connection == {
        "transport": "stdio",
        "command": "python",
        "args": ["server.py"],
        "env": {"TOKEN": "math-secret"},
    }
    assert loaded.configuration.mcp_servers["remote_docs"].connection == {
        "transport": "http",
        "url": "https://example.invalid/mcp",
        "headers": {"Authorization": "Bearer docs-secret"},
    }
    assert loaded.configuration.mcp_servers["disabled"].enabled is False
    assert loaded.configuration.tool_routing_keywords == {
        "local_math_add": ("加法", "add numbers")
    }


@pytest.mark.parametrize(
    "routing",
    [
        {"unsafe tool": ["query"]},
        {"safe_tool": []},
        {"safe_tool": ["same", " SAME "]},
        {"safe_tool": ["x" * 65]},
    ],
)
def test_mcp_config_rejects_invalid_routing_keywords(
    tmp_path: Path,
    routing: dict[str, list[str]],
) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {},
                "toolRoutingKeywords": routing,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(McpConfigurationError, match="routing"):
        load_mcp_configuration(path)


def test_mcp_config_rejects_missing_environment_reference(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(
        '{"mcpServers":{"private":{"command":"python","env":{"TOKEN":"$MISSING"}}}}',
        encoding="utf-8",
    )

    with pytest.raises(McpConfigurationError, match="MISSING"):
        load_mcp_configuration(path, environ={})


def test_mcp_config_rejects_transport_without_required_endpoint(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(
        '{"mcpServers":{"broken":{"transport":"http"}}}',
        encoding="utf-8",
    )

    with pytest.raises(McpConfigurationError, match="broken"):
        load_mcp_configuration(path)


def test_disabled_mcp_server_may_keep_incomplete_secret_configuration(
    tmp_path: Path,
) -> None:
    """禁用项不会连接，因此不应要求命令或解析尚未配置的密钥。"""
    path = tmp_path / "mcp.json"
    path.write_text(
        '{"mcpServers":{"later":{"enabled":false,"env":{"TOKEN":"$MISSING"}}}}',
        encoding="utf-8",
    )

    loaded = load_mcp_configuration(path, environ={})

    assert loaded.configuration.mcp_servers["later"].enabled is False


def test_mcp_runtime_isolates_failed_servers_and_keeps_healthy_tools(
    tmp_path: Path,
) -> None:
    """一个外部服务器不可用时，其他服务器仍应进入 Agent 注册表。"""
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "healthy": {"command": "healthy-server"},
                    "broken": {"command": "broken-server"},
                    "disabled": {"enabled": False, "command": "unused"},
                },
                "toolRoutingKeywords": {
                    "healthy_echo": ["健康回显", "echo health"],
                    "missing_tool": ["不可用工具"],
                },
            }
        ),
        encoding="utf-8",
    )
    factory_calls: list[tuple[dict[str, dict[str, object]], bool]] = []

    class FakeClient:
        async def get_tools(self, *, server_name: str):
            if server_name == "broken":
                raise RuntimeError("connection refused")
            return [_tool("healthy_echo")]

    def client_factory(
        connections: dict[str, dict[str, object]],
        *,
        tool_name_prefix: bool,
    ) -> FakeClient:
        factory_calls.append((connections, tool_name_prefix))
        return FakeClient()

    runtime = asyncio.run(
        initialize_mcp_runtime(
            path,
            timeout_seconds=0.5,
            client_factory=client_factory,
            reserved_tool_names={"web_search"},
        )
    )

    assert runtime.tool_names == ("healthy_echo",)
    assert runtime.tool_routing_keywords == {
        "healthy_echo": ("健康回显", "echo health")
    }
    assert factory_calls == [
        (
            {
                "healthy": {
                    "transport": "stdio",
                    "command": "healthy-server",
                    "args": [],
                },
                "broken": {
                    "transport": "stdio",
                    "command": "broken-server",
                    "args": [],
                },
            },
            True,
        )
    ]
    statuses = {status.name: status for status in runtime.servers}
    assert statuses["healthy"].state == "loaded"
    assert statuses["healthy"].tool_names == ("healthy_echo",)
    assert statuses["broken"].state == "failed"
    assert "connection refused" in (statuses["broken"].error or "")
    assert statuses["disabled"].state == "disabled"


def test_mcp_runtime_times_out_hung_server_without_losing_fast_server(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(
        '{"mcpServers":{"hung":{"command":"hung"},"fast":{"command":"fast"}}}',
        encoding="utf-8",
    )

    class FakeClient:
        async def get_tools(self, *, server_name: str):
            if server_name == "hung":
                await asyncio.Event().wait()
            return [_tool("fast_echo")]

    runtime = asyncio.run(
        initialize_mcp_runtime(
            path,
            timeout_seconds=0.01,
            client_factory=lambda connections, *, tool_name_prefix: FakeClient(),
        )
    )

    statuses = {status.name: status for status in runtime.servers}
    assert runtime.tool_names == ("fast_echo",)
    assert statuses["hung"].state == "failed"
    assert "TimeoutError" in (statuses["hung"].error or "")
    assert statuses["fast"].state == "loaded"


@pytest.mark.parametrize("tool_name", ["unsafe tool", "web_search"])
def test_mcp_runtime_rejects_unsafe_or_reserved_tool_names(
    tmp_path: Path,
    tool_name: str,
) -> None:
    """外部工具不能伪造 Prompt 结构，也不能覆盖 Agent 内置工具。"""
    path = tmp_path / "mcp.json"
    path.write_text(
        '{"mcpServers":{"external":{"command":"server"}}}',
        encoding="utf-8",
    )

    class FakeClient:
        async def get_tools(self, *, server_name: str):
            assert server_name == "external"
            return [_tool(tool_name)]

    runtime = asyncio.run(
        initialize_mcp_runtime(
            path,
            client_factory=lambda connections, *, tool_name_prefix: FakeClient(),
            reserved_tool_names={"web_search"},
        )
    )

    assert runtime.tools == ()
    assert runtime.servers[0].state == "failed"
    assert tool_name in (runtime.servers[0].error or "")


def test_real_stdio_mcp_server_discovers_and_executes_tool(
    tmp_path: Path,
) -> None:
    """真实 SDK 子进程应完成 initialize、tools/list 和 tools/call。"""
    server_path = (
        Path(__file__).parents[1] / "examples" / "mcp_learning_server.py"
    ).resolve()
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "learning": {
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": [str(server_path)],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    async def scenario() -> tuple[object, object, object]:
        runtime = await initialize_mcp_runtime(
            config_path,
            timeout_seconds=10,
            reserved_tool_names={"web_search"},
        )
        tool = next(
            item for item in runtime.tools if item.name == "learning_add_numbers"
        )
        result = await tool.ainvoke({"left": 19, "right": 23})
        return runtime, tool, result

    runtime, tool, result = asyncio.run(scenario())
    sync_result = tool.invoke({"left": 8, "right": 9})

    assert runtime.tool_names == (
        "learning_add_numbers",
        "learning_reverse_text",
    )
    assert runtime.servers[0].state == "loaded"
    assert result[0]["text"] == "42"
    assert sync_result[0]["text"] == "17"
