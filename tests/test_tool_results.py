"""验证 14.2 统一工具结果契约和普通异常收敛。"""

import asyncio
import json
from typing import Any, cast

import pytest
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest

from mini_deer_agent.agents.middleware import (
    awrap_tool_call,
    normalize_tool_message,
    tool_result_meta,
    wrap_tool_call,
)


def _call(name: str, call_id: str = "call-1") -> dict:
    return {"name": name, "args": {}, "id": call_id, "type": "tool_call"}


def _request(name: str) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call=cast(Any, _call(name)),
        tool=None,
        state={},
        runtime=cast(Any, None),
    )


def test_empty_and_partial_returns_receive_structured_semantics() -> None:
    first = normalize_tool_message(
        ToolMessage(
            content=json.dumps({"query": "missing", "results": []}),
            tool_call_id="call-1",
            name="search_empty",
        )
    )
    second = normalize_tool_message(
        ToolMessage(
            content=json.dumps({"content": "head", "truncated": True}),
            tool_call_id="call-2",
            name="read_partial",
        )
    )

    assert tool_result_meta(first) is not None
    assert tool_result_meta(first).status == "no_results"
    assert tool_result_meta(first).recommended_next_action == "rewrite_parameters"
    assert tool_result_meta(second) is not None
    assert tool_result_meta(second).status == "partial_success"
    assert tool_result_meta(second).recommended_next_action == "continue_reading"


def test_plain_text_return_remains_success() -> None:
    message = normalize_tool_message(
        ToolMessage(content="北京 24°C", tool_call_id="call-weather", name="get_weather")
    )

    assert tool_result_meta(message) is not None
    assert tool_result_meta(message).status == "success"


def test_builtin_exception_becomes_paired_retryable_tool_message() -> None:
    def fail(_request: ToolCallRequest) -> ToolMessage:
        raise TimeoutError("private upstream address")

    message = wrap_tool_call(_request("unstable_builtin"), fail)
    assert isinstance(message, ToolMessage)
    meta = tool_result_meta(message)
    assert message.tool_call_id == "call-1"
    assert message.status == "error"
    assert meta is not None
    assert meta.status == "retryable_error"
    assert meta.recoverable_by_model is True
    assert "private upstream address" not in message.text


def test_mcp_exception_becomes_terminal_message_and_run_can_continue() -> None:
    async def fail(_request: ToolCallRequest) -> ToolMessage:
        raise RuntimeError("invalid API key sk-secret-value")

    message = asyncio.run(
        awrap_tool_call(_request("mcp_private_docs"), fail)
    )
    assert isinstance(message, ToolMessage)
    meta = tool_result_meta(message)
    assert meta is not None
    assert meta.status == "terminal_error"
    assert meta.recoverable_by_model is False
    assert meta.recommended_next_action == "stop_using_tool"
    assert "sk-secret-value" not in message.text


def test_graph_control_exception_is_not_converted() -> None:
    def interrupt(_request: ToolCallRequest) -> ToolMessage:
        raise GraphBubbleUp()

    with pytest.raises(GraphBubbleUp):
        wrap_tool_call(_request("interrupting_tool"), interrupt)
