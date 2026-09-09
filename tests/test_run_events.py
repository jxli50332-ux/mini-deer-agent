"""验证 LangGraph 消息到生产级 run 事件契约的投影规则。"""

import asyncio

from collections.abc import Iterator
from uuid import UUID

import pytest
from langchain_core.messages import AIMessageChunk, ToolMessage

from mini_deer_agent.streaming import AgentMessageEvent
from mini_deer_agent.streaming.projector import (
    aproject_run_events,
    project_run_events,
)


def test_projector_sequences_text_tool_chunks_and_result() -> None:
    """分片工具参数应保持同一调用身份，并与工具结果正确关联。"""
    events: list[AgentMessageEvent] = [
        (
            AIMessageChunk(
                content="正在查询",
                id="message-tool-request-1",
                tool_call_chunks=[
                    {
                        "name": "get_weather",
                        "args": "{",
                        "id": "call-weather-1",
                        "index": 0,
                        "type": "tool_call_chunk",
                    }
                ],
            ),
            {"langgraph_node": "model"},
        ),
        (
            AIMessageChunk(
                content="",
                id="message-tool-request-1",
                tool_call_chunks=[
                    {
                        "name": None,
                        "args": '"city":"北京"}',
                        "id": None,
                        "index": 0,
                        "type": "tool_call_chunk",
                    }
                ],
            ),
            {"langgraph_node": "model"},
        ),
        (
            ToolMessage(
                content="北京当前天气：晴。",
                name="get_weather",
                tool_call_id="call-weather-1",
                id="message-tool-result-1",
            ),
            {"langgraph_node": "tools"},
        ),
        (
            AIMessageChunk(content="北京晴。", id="message-final-1"),
            {"langgraph_node": "model"},
        ),
    ]

    run_events = list(
        project_run_events(
            events,
            run_id="run-projector-1",
            thread_id="thread-projector-1",
        )
    )

    assert [event.event for event in run_events] == [
        "run_started",
        "ai_delta",
        "tool_call_delta",
        "tool_result",
        "ai_delta",
        "run_completed",
    ]
    assert [event.sequence for event in run_events] == list(range(1, 7))
    first_tool_delta = run_events[2]
    tool_result = run_events[3]
    assert first_tool_delta.payload == {
        "tool_call_id": "call-weather-1",
        "name": "get_weather",
        "arguments_delta": '{"city":"北京"}',
        "index": 0,
    }
    assert tool_result.payload["tool_call_id"] == "call-weather-1"
    # 同一 provider 消息的文字与工具分片共享产品 ID，不同模型消息则使用不同 UUID。
    assert UUID(str(run_events[1].message_id))
    assert run_events[1].message_id == first_tool_delta.message_id
    assert run_events[4].message_id != run_events[1].message_id
    assert run_events[-1].event_id == "run-projector-1:6"


def test_projector_redacts_internal_failure_and_ends_with_run_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """上游流失败后不得泄露异常详情，也不能错误发送 run_completed。"""

    def failing_events() -> Iterator[AgentMessageEvent]:
        """先产生部分正文，再模拟包含敏感信息的模型异常。"""
        yield (
            AIMessageChunk(content="部分回答", id="message-error-1"),
            {"langgraph_node": "model"},
        )
        raise RuntimeError("内部密钥 sk-private 不得进入公开事件")

    run_events = list(
        project_run_events(
            failing_events(),
            run_id="run-projector-error",
            thread_id="thread-projector-error",
        )
    )

    assert [event.event for event in run_events] == [
        "run_started",
        "ai_delta",
        "run_error",
    ]
    assert run_events[-1].payload == {
        "code": "agent_execution_failed",
        "message": "Agent execution failed",
        "retryable": True,
    }
    assert "sk-private" not in str(run_events[-1].to_data())
    assert "sk-private" not in caplog.text


def test_projector_marks_clarification_as_successful_completed_run() -> None:
    """提出澄清是正常完成的回合，应区别于取消、失败和普通停止。"""
    events: list[AgentMessageEvent] = [
        (
            AIMessageChunk(
                content="",
                id="message-clarification-request",
                tool_call_chunks=[
                    {
                        "name": "ask_clarification",
                        "args": '{"question":"报告主题是什么？"}',
                        "id": "call-clarification-event",
                        "index": 0,
                        "type": "tool_call_chunk",
                    }
                ],
            ),
            {"langgraph_node": "model"},
        ),
        (
            ToolMessage(
                content='{"kind":"human_input_request"}',
                name="ask_clarification",
                tool_call_id="call-clarification-event",
                id="clarification:call-clarification-event",
            ),
            {"langgraph_node": "clarification"},
        ),
    ]

    run_events = list(
        project_run_events(
            events,
            run_id="run-clarification",
            thread_id="thread-clarification",
        )
    )

    assert [event.event for event in run_events] == [
        "run_started",
        "tool_call_delta",
        "tool_result",
        "run_completed",
    ]
    assert run_events[-1].payload == {
        "finish_reason": "clarification_requested",
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "model_calls": 0,
    }


def test_async_projector_uses_explicit_terminal_budget_snapshot() -> None:
    """节点最终元数据即使不在 token chunk 中，也必须进入正式终态。"""

    async def empty_events():
        if False:
            yield None

    async def collect():
        return [
            event
            async for event in aproject_run_events(
                empty_events(),
                run_id="run-terminal-snapshot",
                thread_id="thread-terminal-snapshot",
                terminal_payload=lambda: {
                    "finish_reason": "token_capped",
                    "input_tokens": 70,
                    "output_tokens": 30,
                    "total_tokens": 100,
                    "model_calls": 4,
                },
            )
        ]

    events = asyncio.run(collect())

    assert events[-1].payload == {
        "finish_reason": "token_capped",
        "input_tokens": 70,
        "output_tokens": 30,
        "total_tokens": 100,
        "model_calls": 4,
    }


def test_projector_batches_token_flood_without_changing_answer() -> None:
    """大量单字符 chunk 应保留全文，但不能再制造同数量的 SQLite 事件。"""
    chunks: list[AgentMessageEvent] = [
        (
            AIMessageChunk(content="字", id="one-streamed-answer"),
            {"langgraph_node": "model"},
        )
        for _ in range(300)
    ]

    events = list(
        project_run_events(
            chunks,
            run_id="run-token-batching",
            thread_id="thread-token-batching",
        )
    )
    deltas = [event for event in events if event.event == "ai_delta"]

    assert "".join(str(event.payload["text"]) for event in deltas) == "字" * 300
    assert len(deltas) == 3
    assert [event.sequence for event in events] == list(
        range(1, len(events) + 1)
    )
