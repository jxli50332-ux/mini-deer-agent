"""验证 14.4 工具停滞检测的按工具、按 Run 状态隔离。"""

import json
from typing import Any, cast

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from mini_deer_agent.agents.middleware import (
    ToolProgressPolicy,
    ToolProgressTracker,
    normalize_tool_message,
    tool_result_meta,
)


def _request(name: str, call_id: str = "call-1") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call=cast(
            Any,
            {
                "name": name,
                "args": {},
                "id": call_id,
                "type": "tool_call",
            },
        ),
        tool=None,
        state={},
        runtime=cast(Any, None),
    )


def _success(request: ToolCallRequest, content: str = "useful result") -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=str(request.tool_call["id"]),
        name=str(request.tool_call["name"]),
    )


def test_terminal_error_blocks_only_the_corresponding_tool() -> None:
    tracker = ToolProgressTracker()
    tracker.begin_run("run-a")
    calls = 0

    def auth_failure(_request: ToolCallRequest) -> ToolMessage:
        nonlocal calls
        calls += 1
        raise RuntimeError("invalid API key sk-private")

    first = tracker.wrap_tool_call(_request("private_docs"), auth_failure)
    second = tracker.wrap_tool_call(
        _request("private_docs", "call-2"), auth_failure
    )
    alternate = tracker.wrap_tool_call(
        _request("public_search", "call-3"), _success
    )

    assert calls == 1
    assert isinstance(first, ToolMessage)
    assert tool_result_meta(first).status == "terminal_error"
    assert isinstance(second, ToolMessage)
    assert tool_result_meta(second).error_type == "blocked_by_progress_guard"
    assert isinstance(alternate, ToolMessage)
    assert tool_result_meta(alternate).status == "success"


def test_transient_failures_block_at_threshold_and_new_run_resets() -> None:
    tracker = ToolProgressTracker(
        ToolProgressPolicy(transient_failure_limit=2)
    )
    tracker.begin_run("run-a")
    calls = 0

    def timeout(_request: ToolCallRequest) -> ToolMessage:
        nonlocal calls
        calls += 1
        raise TimeoutError("upstream timeout")

    tracker.wrap_tool_call(_request("unstable"), timeout)
    tracker.wrap_tool_call(_request("unstable", "call-2"), timeout)
    blocked = tracker.wrap_tool_call(_request("unstable", "call-3"), timeout)
    assert calls == 2
    assert isinstance(blocked, ToolMessage)
    assert tool_result_meta(blocked).error_type == "blocked_by_progress_guard"

    tracker.begin_run("run-b")
    retried = tracker.wrap_tool_call(_request("unstable", "call-4"), timeout)
    assert calls == 3
    assert isinstance(retried, ToolMessage)
    assert tool_result_meta(retried).error_type == "transient"


def test_success_resets_transient_failure_counter() -> None:
    tracker = ToolProgressTracker(
        ToolProgressPolicy(transient_failure_limit=2)
    )
    tracker.begin_run("run-a")

    def timeout(_request: ToolCallRequest) -> ToolMessage:
        raise TimeoutError("upstream timeout")

    tracker.wrap_tool_call(_request("unstable"), timeout)
    tracker.wrap_tool_call(_request("unstable", "call-2"), _success)
    result = tracker.wrap_tool_call(_request("unstable", "call-3"), timeout)

    assert isinstance(result, ToolMessage)
    assert tool_result_meta(result).error_type == "transient"
    assert tracker.blocked_reason("unstable") is None


def test_no_results_prompts_parameter_change_without_blocking() -> None:
    tracker = ToolProgressTracker()
    tracker.begin_run("run-a")
    calls = 0

    def no_results(request: ToolCallRequest) -> ToolMessage:
        nonlocal calls
        calls += 1
        return normalize_tool_message(
            ToolMessage(
                content=json.dumps({"query": "missing", "results": []}),
                tool_call_id=str(request.tool_call["id"]),
                name=str(request.tool_call["name"]),
            )
        )

    for index in range(4):
        tracker.wrap_tool_call(
            _request("search", f"call-{index}"), no_results
        )
    messages = tracker.append_pending_hints([])

    assert calls == 4
    assert tracker.blocked_reason("search") is None
    assert len(messages) == 1
    assert isinstance(messages[0], HumanMessage)
    assert messages[0].additional_kwargs["hide_from_ui"] is True
    assert "改写查询" in messages[0].text


def test_near_duplicate_success_queues_stagnation_hint() -> None:
    tracker = ToolProgressTracker(
        ToolProgressPolicy(repeated_content_limit=2, minimum_words=5)
    )
    tracker.begin_run("run-a")
    content = (
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet "
        "useful evidence remains unchanged"
    )

    tracker.wrap_tool_call(
        _request("fetch", "call-1"),
        lambda request: _success(request, content),
    )
    tracker.wrap_tool_call(
        _request("fetch", "call-2"),
        lambda request: _success(request, content + " again"),
    )
    messages = tracker.append_pending_hints([])

    assert tracker.blocked_reason("fetch") is None
    assert len(messages) == 1
    assert "近似相同正文" in messages[0].text
