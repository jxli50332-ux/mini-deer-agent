"""验证模型节点的依赖注入、执行路径和消息合并行为。"""

import asyncio
import json
from collections.abc import Sequence
from typing import Any, Self

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from mini_deer_agent.agents import (
    AgentPromptContext,
    BuiltAgentPrompt,
    async_model_node,
    build_agent_graph,
    model_node,
)
from mini_deer_agent.tools import web_fetch, web_search


class ToolAwareFakeModel(FakeMessagesListChatModel):
    """记录绑定工具并按顺序返回预设消息，避免测试访问 DeepSeek。"""

    bound_tool_names: list[str] = Field(default_factory=list)
    received_histories: list[list[BaseMessage]] = Field(default_factory=list)

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Self:
        """模拟模型绑定并保存模型实际收到的工具名称。"""
        self.bound_tool_names = [tool.name for tool in tools]
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        """保存模型边界消息后复用假模型的固定响应实现。"""
        self.received_histories.append(list(messages))
        return super()._generate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


def test_model_node_returns_injected_model_response() -> None:
    """模型节点应把当前消息交给注入模型，并返回模型生成的消息。"""
    state = {"messages": [HumanMessage(content="你好，LangGraph！")]}
    # 使用 LangChain 的假模型返回预设结果，避免测试访问网络或消耗额度。
    model = FakeMessagesListChatModel(
        responses=[AIMessage(content="这是测试模型生成的回复。")]
    )

    update = model_node(
        state,
        model,
        SystemMessage(content="你是测试 Agent。"),
    )

    assert list(update) == ["messages"]
    assert len(update["messages"]) == 1
    assert isinstance(update["messages"][0], AIMessage)
    assert update["messages"][0].text == "这是测试模型生成的回复。"


def test_sync_and_async_model_nodes_repair_dangling_tool_history() -> None:
    """同步和异步模型入口都不能把缺失工具结果的 checkpoint 直接交给模型。"""
    received_histories: list[list[BaseMessage]] = []

    def capture_messages(messages: list[BaseMessage]) -> AIMessage:
        """记录模型边界实际收到的消息，不调用任何外部模型。"""
        received_histories.append(list(messages))
        return AIMessage(content="已恢复。")

    dangling_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "get_weather",
                "args": {"city": "北京"},
                "id": "call-interrupted",
                "type": "tool_call",
            }
        ],
    )
    state = {
        "messages": [dangling_call, HumanMessage(content="继续刚才的任务。")]
    }
    model = RunnableLambda(capture_messages)

    system_message = SystemMessage(content="你是测试 Agent。")
    model_node(state, model, system_message)
    asyncio.run(async_model_node(state, model, system_message))

    assert len(received_histories) == 2
    for history in received_histories:
        assert [type(message).__name__ for message in history] == [
            "SystemMessage",
            "AIMessage",
            "ToolMessage",
            "HumanMessage",
        ]
        assert history[0] is system_message
        assert history[2].tool_call_id == "call-interrupted"
        assert history[2].status == "error"


def test_compiled_graph_injects_prompt_without_persisting_system_message() -> None:
    """默认图必须把 Prompt 交给模型，但 MessagesState 只保存真实对话。"""
    model = ToolAwareFakeModel(responses=[AIMessage(content="我是 Mini Deer Agent。")])
    graph = build_agent_graph(model)

    result = graph.invoke({"messages": [HumanMessage(content="你是谁？")]})

    assert len(model.received_histories) == 1
    assert [type(message).__name__ for message in model.received_histories[0]] == [
        "SystemMessage",
        "HumanMessage",
    ]
    prompt_text = model.received_histories[0][0].text
    assert "你是 Mini Deer Agent" in prompt_text
    assert "`get_weather`" not in prompt_text
    assert "`web_search`" in prompt_text
    assert "`web_fetch`" in prompt_text
    assert "deepseek" not in prompt_text.lower()
    assert "claude" not in prompt_text.lower()
    assert [type(message).__name__ for message in result["messages"]] == [
        "HumanMessage",
        "AIMessage",
    ]


def test_graph_uses_registered_tools_instead_of_prompt_context_claims() -> None:
    """Prompt 工具清单必须由真实注册表覆盖，不能相信调用方声明。"""
    captured_contexts: list[AgentPromptContext] = []

    class CapturingPromptBuilder:
        """记录 Graph 传给 Prompt Builder 的最终可信上下文。"""

        def build(self, context: AgentPromptContext) -> BuiltAgentPrompt:
            """返回固定系统消息，避免测试依赖默认模板正文。"""
            captured_contexts.append(context)
            return BuiltAgentPrompt(
                version="test/v1",
                system_message=SystemMessage(content="测试系统提示。"),
            )

    model = ToolAwareFakeModel(responses=[AIMessage(content="完成。")])
    graph = build_agent_graph(
        model,
        prompt_builder=CapturingPromptBuilder(),
        prompt_context=AgentPromptContext(
            agent_name="定制 Agent",
            available_tool_names=("forged_tool",),
        ),
    )

    graph.invoke({"messages": [HumanMessage(content="开始。")]})

    assert captured_contexts == [
        AgentPromptContext(
            agent_name="定制 Agent",
            available_tool_names=("web_search", "web_fetch"),
        )
    ]


def test_compiled_graph_executes_web_search_and_returns_final_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注册后的联网搜索应经过同一个 ToolNode 循环回到模型。"""
    called_queries: list[tuple[str, int]] = []

    def fake_web_search(query: str, max_results: int = 5) -> str:
        """记录参数并返回固定来源，避免图测试访问真实搜索服务。"""
        called_queries.append((query, max_results))
        return json.dumps(
            {
                "query": query,
                "total_results": 1,
                "results": [
                    {
                        "title": "Mini Deer",
                        "url": "https://example.com/mini-deer",
                        "content": "示例摘要",
                    }
                ],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(web_search, "func", fake_web_search)
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": "Mini Deer 最新消息", "max_results": 3},
                        "id": "call-search-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="搜索完成：https://example.com/mini-deer"
            ),
        ]
    )
    graph = build_agent_graph(model)

    result = graph.invoke(
        {"messages": [HumanMessage(content="搜索 Mini Deer 最新消息并附来源。")]}
    )

    assert model.bound_tool_names == ["web_search", "web_fetch"]
    assert called_queries == [("Mini Deer 最新消息", 3)]
    assert len(result["messages"]) == 4
    assert isinstance(result["messages"][2], ToolMessage)
    assert result["messages"][2].name == "web_search"
    assert result["messages"][2].tool_call_id == "call-search-1"
    assert "https://example.com/mini-deer" in result["messages"][2].text
    assert result["messages"][3].text.endswith(
        "https://example.com/mini-deer"
    )


def test_compiled_graph_can_search_fetch_and_cite_full_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """主 Agent 应能搜索候选 URL、读取正文，再基于同一来源生成最终引用。"""
    fetched_urls: list[str] = []

    def fake_search(query: str, max_results: int = 5) -> str:
        del query, max_results
        return json.dumps(
            {
                "query": "Mini Deer 架构",
                "total_results": 1,
                "results": [
                    {
                        "title": "架构文档",
                        "url": "https://example.com/architecture",
                        "content": "搜索摘要没有完整细节。",
                    }
                ],
            },
            ensure_ascii=False,
        )

    def fake_fetch(url: str) -> str:
        fetched_urls.append(url)
        return json.dumps(
            {
                "requested_url": url,
                "url": url,
                "title": "架构文档",
                "content": "完整正文说明模型、工具和持久化职责分离。",
                "characters": 23,
                "truncated": False,
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(web_search, "func", fake_search)
    monkeypatch.setattr(web_fetch, "func", fake_fetch)
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": "Mini Deer 架构"},
                        "id": "call-search-deep",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "web_fetch",
                        "args": {"url": "https://example.com/architecture"},
                        "id": "call-fetch-deep",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content=(
                    "模型、工具和持久化职责分离"
                    " [citation:架构文档](https://example.com/architecture)"
                )
            ),
        ]
    )

    result = build_agent_graph(model).invoke(
        {"messages": [HumanMessage(content="搜索并深度阅读 Mini Deer 架构。")]}
    )

    assert fetched_urls == ["https://example.com/architecture"]
    assert [
        message.name
        for message in result["messages"]
        if isinstance(message, ToolMessage)
    ] == ["web_search", "web_fetch"]
    assert "[citation:架构文档]" in result["messages"][-1].text


def test_compiled_graph_ends_when_model_does_not_request_tool() -> None:
    """模型直接回答时，条件边应跳过工具节点并结束。"""
    model = ToolAwareFakeModel(
        responses=[AIMessage(content="你好，我是 Mini Deer Agent。")]
    )
    graph = build_agent_graph(model)

    result = graph.invoke({"messages": [HumanMessage(content="你好！")]})

    assert len(result["messages"]) == 2
    assert result["messages"][1].text == "你好，我是 Mini Deer Agent。"


def test_in_memory_checkpointer_resumes_same_thread_state() -> None:
    """相同 thread_id 的下一轮调用应自动加载并追加已有消息。"""
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(content="第一轮回答。"),
            AIMessage(content="第二轮回答。"),
        ]
    )
    graph = build_agent_graph(model, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "thread-a"}}

    graph.invoke(
        {"messages": [HumanMessage(content="第一轮问题。")]},
        config,
    )
    # 第二次只提交本轮新消息，旧历史应由 checkpointer 自动恢复。
    second_result = graph.invoke(
        {"messages": [HumanMessage(content="第二轮问题。")]},
        config,
    )
    snapshot = graph.get_state(config)

    expected_texts = [
        "第一轮问题。",
        "第一轮回答。",
        "第二轮问题。",
        "第二轮回答。",
    ]
    assert [message.text for message in second_result["messages"]] == expected_texts
    assert [message.text for message in snapshot.values["messages"]] == expected_texts


def test_in_memory_checkpointer_isolates_thread_ids() -> None:
    """不同 thread_id 必须读取互相独立的消息状态。"""
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(content="线程 A 回答。"),
            AIMessage(content="线程 B 回答。"),
        ]
    )
    graph = build_agent_graph(model, checkpointer=InMemorySaver())

    graph.invoke(
        {"messages": [HumanMessage(content="线程 A 问题。")]},
        {"configurable": {"thread_id": "thread-a"}},
    )
    thread_b_result = graph.invoke(
        {"messages": [HumanMessage(content="线程 B 问题。")]},
        {"configurable": {"thread_id": "thread-b"}},
    )

    assert [message.text for message in thread_b_result["messages"]] == [
        "线程 B 问题。",
        "线程 B 回答。",
    ]


def test_checkpointer_requires_thread_id() -> None:
    """启用状态存储后，调用方必须提供用于定位 checkpoint 的 thread_id。"""
    model = ToolAwareFakeModel(
        responses=[AIMessage(content="这条回复不应被生成。")]
    )
    graph = build_agent_graph(model, checkpointer=InMemorySaver())

    with pytest.raises(ValueError, match="thread_id"):
        graph.invoke({"messages": [HumanMessage(content="缺少线程编号。")]})
