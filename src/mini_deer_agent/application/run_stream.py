"""编排一次 Agent 流式运行，不依赖 FastAPI 或具体传输协议。"""

from collections.abc import AsyncIterator, Callable, Iterator

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from mini_deer_agent.agents import build_agent_graph
from mini_deer_agent.domain import TextAttachment
from mini_deer_agent.streaming import (
    AgentMessageEvent,
    astream_agent_messages,
    stream_agent_messages,
)
from mini_deer_agent.streaming.events import RunEvent
from mini_deer_agent.streaming.projector import aproject_run_events


type AgentGraphFactory = Callable[[BaseCheckpointSaver], CompiledStateGraph]


def _human_message(
    message: str,
    attachments: tuple[TextAttachment, ...],
) -> HumanMessage:
    """构造写入 checkpoint 的用户消息；可见正文与附件元数据保持分离。"""
    if not attachments:
        return HumanMessage(content=message)
    return HumanMessage(
        content=message,
        additional_kwargs={
            "text_attachments": [
                {
                    "filename": item.filename,
                    "media_type": item.media_type,
                    "size_bytes": item.size_bytes,
                    "content": item.content,
                }
                for item in attachments
            ]
        },
    )


def build_default_agent_graph(
    checkpointer: BaseCheckpointSaver,
) -> CompiledStateGraph:
    """使用应用持有的 checkpointer 构建默认主 Agent 图。"""
    # 默认路径在真正开始请求时才创建模型，健康检查不依赖模型密钥是否已经配置。
    return build_agent_graph(checkpointer=checkpointer)


class RunStreamService:
    """把线程消息转换为同步学习流或可取消的异步 Web Run 事件流。"""

    def __init__(
        self,
        checkpointer: BaseCheckpointSaver,
        *,
        graph_factory: AgentGraphFactory = build_default_agent_graph,
    ) -> None:
        """保存 checkpoint 和可替换构图工厂，不负责 HTTP 或 Run 注册。"""
        self._checkpointer = checkpointer
        self._graph_factory = graph_factory

    def stream_messages(
        self,
        message: str,
        thread_id: str,
        attachments: tuple[TextAttachment, ...] = (),
    ) -> Iterator[AgentMessageEvent]:
        """恢复指定线程，只提交本轮用户消息，并惰性产生 LangGraph 消息。"""
        # 每轮构建独立 CompiledStateGraph；共享 checkpointer 负责跨轮状态和线程隔离。
        graph = self._graph_factory(self._checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        yield from stream_agent_messages(
            graph,
            [_human_message(message, attachments)],
            config,
        )

    async def astream_messages(
        self,
        message: str,
        thread_id: str,
        attachments: tuple[TextAttachment, ...] = (),
    ) -> AsyncIterator[AgentMessageEvent]:
        """异步运行指定 Thread，供后台 asyncio Task 驱动。"""
        graph = self._graph_factory(self._checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        async for event in astream_agent_messages(
            graph,
            [_human_message(message, attachments)],
            config,
        ):
            yield event

    async def astream_run_events(
        self,
        message: str,
        thread_id: str,
        run_id: str,
        attachments: tuple[TextAttachment, ...] = (),
    ) -> AsyncIterator[RunEvent]:
        """把异步 LangGraph 消息投影为当前 Run 的版本化产品事件。"""
        projected_events = aproject_run_events(
            self.astream_messages(message, thread_id, attachments),
            run_id=run_id,
            thread_id=thread_id,
        )
        async for event in projected_events:
            yield event
