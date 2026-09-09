"""编排一次 Agent 流式运行，不依赖 FastAPI 或具体传输协议。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from functools import partial
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from mini_deer_agent.agents import build_agent_graph
from mini_deer_agent.agents.middleware import RunBudgetPolicy, RunBudgetTracker
from mini_deer_agent.application.memory import MemoryStore
from mini_deer_agent.domain import TextAttachment
from mini_deer_agent.skills import BuiltInSkillCatalog
from mini_deer_agent.streaming import (
    AgentMessageEvent,
    astream_agent_messages,
    stream_agent_messages,
)
from mini_deer_agent.streaming.events import RunEvent
from mini_deer_agent.streaming.projector import aproject_run_events

if TYPE_CHECKING:
    from mini_deer_agent.application.workspaces import FileAccess


type AgentGraphFactory = Callable[..., CompiledStateGraph]
type FileAccessResolver = Callable[[str, str], "FileAccess | None"]
type SkillCatalogFactory = Callable[[], BuiltInSkillCatalog]


def _human_message(
    message: str,
    attachments: tuple[TextAttachment, ...],
    human_input_response: dict[str, object] | None = None,
    internal_continuation: bool = False,
) -> HumanMessage:
    """构造 checkpoint 用户消息；正文、附件和澄清关联保持分离。"""
    additional_kwargs: dict[str, object] = {}
    if internal_continuation:
        additional_kwargs.update(
            {
                "hide_from_ui": True,
                "kind": "goal_continuation",
            }
        )
    if attachments:
        additional_kwargs["text_attachments"] = [
            {
                "filename": item.filename,
                "media_type": item.media_type,
                "size_bytes": item.size_bytes,
                "content": item.content,
            }
            for item in attachments
        ]
    if human_input_response is not None:
        additional_kwargs["hide_from_ui"] = True
        additional_kwargs["human_input_response"] = dict(human_input_response)
    if not additional_kwargs:
        return HumanMessage(content=message)
    return HumanMessage(
        content=message,
        additional_kwargs=additional_kwargs,
    )


def build_default_agent_graph(
    checkpointer: BaseCheckpointSaver,
    file_access: FileAccess | None = None,
    *,
    memory_store: MemoryStore | None = None,
    mcp_tools: tuple[BaseTool, ...] = (),
    mcp_tool_routing_keywords: Mapping[str, tuple[str, ...]] | None = None,
    skill_catalog: BuiltInSkillCatalog | None = None,
    run_budget_tracker: RunBudgetTracker | None = None,
) -> CompiledStateGraph:
    """使用应用持有的 checkpointer 构建默认主 Agent 图。"""
    # 默认路径在真正开始请求时才创建模型，健康检查不依赖模型密钥是否已经配置。
    return build_agent_graph(
        checkpointer=checkpointer,
        memory_store=memory_store,
        mcp_tools=mcp_tools,
        mcp_tool_routing_keywords=mcp_tool_routing_keywords,
        skill_catalog=skill_catalog,
        file_access=file_access,
        run_budget_tracker=run_budget_tracker,
    )


class RunStreamService:
    """把线程消息转换为同步学习流或可取消的异步 Web Run 事件流。"""

    def __init__(
        self,
        checkpointer: BaseCheckpointSaver,
        *,
        memory_store: MemoryStore | None = None,
        mcp_tools: tuple[BaseTool, ...] = (),
        mcp_tool_routing_keywords: Mapping[str, tuple[str, ...]] | None = None,
        graph_factory: AgentGraphFactory = build_default_agent_graph,
        file_access_resolver: FileAccessResolver | None = None,
        skill_catalog_factory: SkillCatalogFactory | None = None,
        run_budget_policy: RunBudgetPolicy | None = None,
    ) -> None:
        """保存 checkpoint 和可替换构图工厂，不负责 HTTP 或 Run 注册。"""
        self._checkpointer = checkpointer
        self._uses_default_graph_factory = graph_factory is build_default_agent_graph
        self._graph_factory = (
            partial(
                graph_factory,
                memory_store=memory_store,
                mcp_tools=mcp_tools,
                mcp_tool_routing_keywords=mcp_tool_routing_keywords,
            )
            if graph_factory is build_default_agent_graph
            else graph_factory
        )
        self._file_access_resolver = file_access_resolver
        self._skill_catalog_factory = skill_catalog_factory
        self._run_budget_policy = run_budget_policy or RunBudgetPolicy()

    def _graph_for_thread(
        self,
        thread_id: str,
        message: str,
        run_budget_tracker: RunBudgetTracker | None = None,
    ) -> CompiledStateGraph:
        """从可信持久归属解析本轮 Scope，再为该 Thread 独立构图。"""
        file_access = (
            self._file_access_resolver(thread_id, message)
            if self._file_access_resolver is not None
            else None
        )
        if self._uses_default_graph_factory:
            return self._graph_factory(
                self._checkpointer,
                file_access,
                run_budget_tracker=run_budget_tracker,
                skill_catalog=(
                    self._skill_catalog_factory()
                    if self._skill_catalog_factory is not None
                    else None
                ),
            )
        return self._graph_factory(self._checkpointer, file_access)

    def stream_messages(
        self,
        message: str,
        thread_id: str,
        attachments: tuple[TextAttachment, ...] = (),
    ) -> Iterator[AgentMessageEvent]:
        """恢复指定线程，只提交本轮用户消息，并惰性产生 LangGraph 消息。"""
        # 每轮构建独立 CompiledStateGraph；共享 checkpointer 负责跨轮状态和线程隔离。
        graph = self._graph_for_thread(thread_id, message)
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
        human_input_response: dict[str, object] | None = None,
        run_id: str | None = None,
        run_budget_tracker: RunBudgetTracker | None = None,
        internal_continuation: bool = False,
    ) -> AsyncIterator[AgentMessageEvent]:
        """异步运行指定 Thread，供后台 asyncio Task 驱动。"""
        graph = self._graph_for_thread(
            thread_id,
            message,
            run_budget_tracker,
        )
        configurable = {"thread_id": thread_id}
        if run_id is not None:
            configurable["run_id"] = run_id
        config = {"configurable": configurable}
        async for event in astream_agent_messages(
            graph,
            [
                _human_message(
                    message,
                    attachments,
                    human_input_response,
                    internal_continuation,
                )
            ],
            config,
        ):
            yield event

    async def astream_run_events(
        self,
        message: str,
        thread_id: str,
        run_id: str,
        attachments: tuple[TextAttachment, ...] = (),
        human_input_response: dict[str, object] | None = None,
        *,
        run_budget_tracker: RunBudgetTracker | None = None,
        internal_continuation: bool = False,
    ) -> AsyncIterator[RunEvent]:
        """把异步 LangGraph 消息投影为当前 Run 的版本化产品事件。"""
        active_budget_tracker = run_budget_tracker or RunBudgetTracker(
            self._run_budget_policy
        )
        active_budget_tracker.pin_run(run_id)
        projected_events = aproject_run_events(
            self.astream_messages(
                message,
                thread_id,
                attachments,
                human_input_response,
                run_id,
                active_budget_tracker,
                internal_continuation,
            ),
            run_id=run_id,
            thread_id=thread_id,
            terminal_payload=active_budget_tracker.terminal_payload,
        )
        async for event in projected_events:
            yield event

    def create_run_budget_tracker(self, run_id: str) -> RunBudgetTracker:
        """创建并固定可跨 Goal 隐藏续轮复用的产品 Run 预算。"""
        tracker = RunBudgetTracker(self._run_budget_policy)
        tracker.pin_run(run_id)
        return tracker
