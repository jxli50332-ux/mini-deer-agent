"""验证 Agent 消息到标准 SSE 文本帧的转换行为。"""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator

import pytest
from langchain_core.messages import AIMessageChunk, ToolMessage

from mini_deer_agent.streaming import (
    AgentMessageEvent,
    RunEvent,
    aiter_run_sse_frames,
    format_sse,
    iter_sse_frames,
)


def parse_frame(frame: str) -> tuple[str, dict[str, object]]:
    """解析测试中的最小 SSE 帧，便于断言事件名称和 JSON 数据。"""
    lines = frame.rstrip("\n").splitlines()
    event_name = lines[0].removeprefix("event: ")
    data = json.loads(lines[1].removeprefix("data: "))
    return event_name, data


def test_format_sse_keeps_chinese_and_escapes_content_newlines() -> None:
    """SSE 数据应保持中文，并把正文换行编码在单行 JSON 中。"""
    frame = format_sse(
        "ai_delta",
        {"id": "message-1", "content": "北京\n雷暴"},
    )

    assert frame == (
        'event: ai_delta\n'
        'data: {"id":"message-1","content":"北京\\n雷暴"}\n\n'
    )


def test_format_sse_rejects_event_name_newlines() -> None:
    """事件名不能包含换行，避免额外 SSE 字段被注入响应。"""
    with pytest.raises(ValueError, match="换行"):
        format_sse("ai_delta\nevent: injected", {"content": "危险输入"})


def test_format_sse_rejects_event_id_newlines() -> None:
    """事件 ID 同样不能注入额外 SSE 字段。"""
    with pytest.raises(ValueError, match="事件 ID"):
        format_sse(
            "ai_delta",
            {"content": "安全正文"},
            event_id="run-1:1\ndata: injected",
        )


def test_iter_sse_frames_maps_agent_messages_and_appends_end() -> None:
    """消息转换器应按顺序发送正文、工具增量、工具结果和结束帧。"""
    events: list[AgentMessageEvent] = [
        (
            AIMessageChunk(
                content="北京",
                id="message-model-1",
                tool_call_chunks=[
                    {
                        "name": "get_weather",
                        "args": '{"city":"北京"}',
                        "id": "call-weather-1",
                        "index": 0,
                        "type": "tool_call_chunk",
                    }
                ],
            ),
            {"langgraph_node": "model"},
        ),
        (
            ToolMessage(
                content="北京当前天气：雷暴。",
                name="get_weather",
                tool_call_id="call-weather-1",
                id="message-tool-1",
            ),
            {"langgraph_node": "tools"},
        ),
    ]

    frames = list(iter_sse_frames(events))
    parsed_frames = [parse_frame(frame) for frame in frames]

    assert [event_name for event_name, _data in parsed_frames] == [
        "ai_delta",
        "tool_call_chunk",
        "tool_result",
        "end",
    ]
    assert parsed_frames[0][1] == {
        "id": "message-model-1",
        "content": "北京",
        "node": "model",
    }
    assert parsed_frames[1][1]["chunks"] == [
        {
            "name": "get_weather",
            "args": '{"city":"北京"}',
            "id": "call-weather-1",
            "index": 0,
            "type": "tool_call_chunk",
        }
    ]
    assert parsed_frames[2][1] == {
        "id": "message-tool-1",
        "tool_call_id": "call-weather-1",
        "name": "get_weather",
        "content": "北京当前天气：雷暴。",
        "node": "tools",
    }
    assert parsed_frames[3] == ("end", {})
    assert all(frame.endswith("\n\n") for frame in frames)


def test_iter_sse_frames_hides_internal_error_and_still_ends() -> None:
    """上游异常不能泄露内部详情，并且应在 error 后发送 end。"""
    def failing_events() -> Iterator[AgentMessageEvent]:
        """模拟模型流在已经发送一个 chunk 后发生内部异常。"""
        yield (
            AIMessageChunk(content="部分回答", id="message-error-1"),
            {"langgraph_node": "model"},
        )
        raise RuntimeError("内部密钥 sk-private 不得发送给客户端")

    frames = list(iter_sse_frames(failing_events()))
    parsed_frames = [parse_frame(frame) for frame in frames]

    assert [event_name for event_name, _data in parsed_frames] == [
        "ai_delta",
        "error",
        "end",
    ]
    assert parsed_frames[1][1] == {"message": "Agent execution failed"}
    assert "sk-private" not in "".join(frames)


def test_async_run_sse_emits_comment_heartbeat_without_changing_sequence() -> None:
    """静默期应发送无 ID 的注释心跳，随后业务事件仍保持原始 sequence。"""

    async def scenario() -> None:
        """人为制造静默窗口，再恢复同一个 RunEvent 源。"""
        release_terminal = asyncio.Event()
        run_id = "run-heartbeat-1"
        thread_id = "thread-heartbeat-1"

        async def delayed_events() -> AsyncIterator[RunEvent]:
            """开始事件后等待测试放行，模拟模型或工具长时间没有增量。"""
            yield RunEvent(
                event="run_started",
                run_id=run_id,
                thread_id=thread_id,
                sequence=1,
                message_id=None,
                payload={"created_at": "2026-08-28T00:00:00+00:00"},
            )
            await release_terminal.wait()
            yield RunEvent(
                event="run_completed",
                run_id=run_id,
                thread_id=thread_id,
                sequence=2,
                message_id=None,
                payload={"finish_reason": "stop"},
            )

        frames = aiter_run_sse_frames(
            delayed_events(),
            heartbeat_interval=0.01,
        )
        started = await anext(frames)
        heartbeat = await anext(frames)
        release_terminal.set()
        completed = await asyncio.wait_for(anext(frames), timeout=1)

        assert started.startswith(f"id: {run_id}:1\n")
        assert heartbeat == ": heartbeat\n\n"
        assert completed.startswith(f"id: {run_id}:2\n")
        assert '"sequence":2' in completed
        with pytest.raises(StopAsyncIteration):
            await anext(frames)

    asyncio.run(scenario())


def test_async_run_sse_closes_pending_source_after_client_stops() -> None:
    """客户端在心跳后关闭流时，后台等待中的上游读取任务必须同步结束。"""

    async def scenario() -> None:
        """关闭输出生成器，并观察被阻塞事件源的 finally 是否执行。"""
        source_closed = asyncio.Event()

        async def blocked_events() -> AsyncIterator[RunEvent]:
            """永久等待下一事件，模拟没有业务输出的活动 Run。"""
            try:
                await asyncio.Event().wait()
                # 保留 yield 使本函数成为 AsyncIterator；正常路径永远不会抵达这里。
                yield RunEvent(
                    event="run_completed",
                    run_id="unreachable-run",
                    thread_id="unreachable-thread",
                    sequence=1,
                    message_id=None,
                    payload={"finish_reason": "stop"},
                )
            finally:
                source_closed.set()

        frames = aiter_run_sse_frames(
            blocked_events(),
            heartbeat_interval=0.01,
        )

        assert await anext(frames) == ": heartbeat\n\n"
        await frames.aclose()
        assert source_closed.is_set()

    asyncio.run(scenario())
