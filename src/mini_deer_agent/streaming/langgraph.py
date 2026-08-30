"""把 LangGraph 的同步流式接口适配为项目内部事件迭代器。"""

from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any, cast

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from mini_deer_agent.streaming.events import AgentMessageEvent


def stream_agent_updates(
    graph: CompiledStateGraph,
    messages: Sequence[BaseMessage],
    config: RunnableConfig | None = None,
) -> Iterator[dict[str, Any]]:
    """按节点完成顺序惰性返回 LangGraph 状态增量。"""
    # 只提交本轮消息；启用 Checkpointer 时，旧历史会根据 config 中的 thread_id 恢复。
    input_state = {"messages": list(messages)}

    # yield from 保持底层迭代器的惰性，不能先转成 list 再伪装成流式输出。
    yield from graph.stream(
        input_state,
        config=config,
        stream_mode="updates",
    )


def stream_agent_messages(
    graph: CompiledStateGraph,
    messages: Sequence[BaseMessage],
    config: RunnableConfig | None = None,
) -> Iterator[AgentMessageEvent]:
    """惰性返回模型消息增量、工具消息及其 LangGraph 元数据。"""
    # 与 updates 模式保持相同输入语义，启用 Checkpointer 时仍然只提交本轮消息。
    input_state = {"messages": list(messages)}

    # 单一 messages 模式固定返回 (消息, metadata)；cast 只收窄类型，不消费迭代器。
    events = cast(
        Iterator[AgentMessageEvent],
        graph.stream(
            input_state,
            config=config,
            stream_mode="messages",
        ),
    )
    # 逐项转交可保留 token 到达时机，调用方可按 message.id 累积正文。
    yield from events


async def astream_agent_messages(
    graph: CompiledStateGraph,
    messages: Sequence[BaseMessage],
    config: RunnableConfig | None = None,
) -> AsyncIterator[AgentMessageEvent]:
    """异步返回模型和工具消息，使取消可以传播到 LangGraph 当前等待点。"""
    input_state = {"messages": list(messages)}
    events = cast(
        AsyncIterator[AgentMessageEvent],
        graph.astream(
            input_state,
            config=config,
            stream_mode="messages",
        ),
    )
    async for event in events:
        yield event
