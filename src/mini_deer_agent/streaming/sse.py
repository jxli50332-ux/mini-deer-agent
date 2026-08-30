"""把 Mini Deer Agent 内部消息转换为标准 SSE 文本帧。"""

import asyncio
import json
import logging
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator, Mapping
from typing import Any

from langchain_core.messages import AIMessageChunk, ToolMessage

from mini_deer_agent.streaming.events import AgentMessageEvent, RunEvent


logger = logging.getLogger(__name__)
DEFAULT_SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0
_SSE_HEARTBEAT_FRAME = ": heartbeat\n\n"


def _validate_sse_field(field_name: str, value: str) -> None:
    """拒绝可以注入额外 SSE 行的换行字符。"""
    if "\n" in value or "\r" in value:
        raise ValueError(f"SSE {field_name}不能包含换行")


def format_sse(
    event: str,
    data: Mapping[str, Any],
    *,
    event_id: str | None = None,
) -> str:
    """把事件名和 JSON 数据编码为一个以空行结尾的 SSE 帧。"""
    # 事件名会直接写入协议字段，禁止换行可避免注入额外 event 或 data 行。
    _validate_sse_field("事件名", event)
    if event_id is not None:
        _validate_sse_field("事件 ID", event_id)

    # 紧凑 JSON 保证 data 只有一行；正文换行会被编码为字符串中的 \n。
    payload = json.dumps(
        dict(data),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    # v1 事件携带 id；旧兼容事件不传 event_id，因而保持原始字节格式。
    id_line = f"id: {event_id}\n" if event_id is not None else ""
    # 最后的两个换行产生一个空行，SSE 客户端据此判断当前事件已经结束。
    return f"{id_line}event: {event}\ndata: {payload}\n\n"


def iter_sse_frames(events: Iterable[AgentMessageEvent]) -> Iterator[str]:
    """按抵达顺序把 Agent 消息流转换为客户端可消费的 SSE 帧。"""
    try:
        for message, metadata in events:
            node_name = str(metadata.get("langgraph_node", "unknown"))

            if isinstance(message, AIMessageChunk):
                if message.text:
                    # 正文 chunk 必须立即独立发送，客户端才能逐步追加模型回答。
                    yield format_sse(
                        "ai_delta",
                        {
                            "id": message.id,
                            "content": message.text,
                            "node": node_name,
                        },
                    )

                if message.tool_call_chunks:
                    # 工具名和 JSON 参数可能分片抵达，保留原始 chunk 供客户端展示或聚合。
                    yield format_sse(
                        "tool_call_chunk",
                        {
                            "id": message.id,
                            "chunks": message.tool_call_chunks,
                            "node": node_name,
                        },
                    )
                continue

            if isinstance(message, ToolMessage):
                # 工具结果一次性发送，并保留 tool_call_id 关联原工具请求。
                yield format_sse(
                    "tool_result",
                    {
                        "id": message.id,
                        "tool_call_id": message.tool_call_id,
                        "name": message.name,
                        "content": message.text,
                        "node": node_name,
                    },
                )
    except Exception as exc:
        # 脱敏日志接入前不记录异常正文，避免第三方错误携带密钥或用户敏感内容。
        logger.error(
            "Agent 消息流转换失败：error_type=%s",
            type(exc).__name__,
        )
        yield format_sse("error", {"message": "Agent execution failed"})

    # 正常结束和已处理异常都发送终止帧，让客户端不依赖 TCP 关闭判断业务结束。
    yield format_sse("end", {})


def iter_run_sse_frames(events: Iterable[RunEvent]) -> Iterator[str]:
    """把版本化 run 事件编码为带 SSE ID 的公开协议帧。"""
    for run_event in events:
        yield format_sse(
            run_event.event,
            run_event.to_data(),
            event_id=run_event.event_id,
        )


async def aiter_sse_frames(
    events: AsyncIterable[AgentMessageEvent],
) -> AsyncIterator[str]:
    """异步编码旧消息协议，迁移期也不再阻塞 ASGI 事件循环。"""
    try:
        async for message, metadata in events:
            node_name = str(metadata.get("langgraph_node", "unknown"))
            if isinstance(message, AIMessageChunk):
                if message.text:
                    yield format_sse(
                        "ai_delta",
                        {
                            "id": message.id,
                            "content": message.text,
                            "node": node_name,
                        },
                    )
                if message.tool_call_chunks:
                    yield format_sse(
                        "tool_call_chunk",
                        {
                            "id": message.id,
                            "chunks": message.tool_call_chunks,
                            "node": node_name,
                        },
                    )
                continue
            if isinstance(message, ToolMessage):
                yield format_sse(
                    "tool_result",
                    {
                        "id": message.id,
                        "tool_call_id": message.tool_call_id,
                        "name": message.name,
                        "content": message.text,
                        "node": node_name,
                    },
                )
    except Exception as exc:
        logger.error(
            "Agent 异步消息流转换失败：error_type=%s",
            type(exc).__name__,
        )
        yield format_sse("error", {"message": "Agent execution failed"})
    yield format_sse("end", {})


async def aiter_run_sse_frames(
    events: AsyncIterable[RunEvent],
    *,
    heartbeat_interval: float = DEFAULT_SSE_HEARTBEAT_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    """编码版本化 RunEvent，并在静默期发送不占业务序号的 SSE 注释。"""
    if heartbeat_interval <= 0:
        raise ValueError("SSE 心跳间隔必须大于 0")

    iterator = events.__aiter__()
    pending_event: asyncio.Task[RunEvent] | None = None
    try:
        while True:
            if pending_event is None:
                pending_event = asyncio.create_task(anext(iterator))

            # asyncio.wait 超时不会取消 anext Task；同一次上游读取可跨越多个
            # 心跳周期继续等待，避免把传输层保活误判成业务 Run 取消。
            completed, _pending = await asyncio.wait(
                {pending_event},
                timeout=heartbeat_interval,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not completed:
                # 注释帧没有 id、event 或 data，浏览器会忽略它，业务 sequence
                # 仍只由持久化 RunEvent 推进。
                yield _SSE_HEARTBEAT_FRAME
                continue

            completed_event = pending_event
            pending_event = None
            try:
                run_event = completed_event.result()
            except StopAsyncIteration:
                return
            yield format_sse(
                run_event.event,
                run_event.to_data(),
                event_id=run_event.event_id,
            )
    finally:
        if pending_event is not None and not pending_event.done():
            # StreamingResponse 因客户端断开而关闭本生成器时，必须把取消传给
            # 上游订阅；RunExecutionManager 才能物化 client_disconnected 终态。
            pending_event.cancel()
            await asyncio.gather(pending_event, return_exceptions=True)

        close_iterator = getattr(iterator, "aclose", None)
        if close_iterator is not None:
            await close_iterator()
