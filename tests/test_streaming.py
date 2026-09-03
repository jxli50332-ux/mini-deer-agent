"""验证节点级流式更新的惰性执行、节点顺序和消息类型。"""

import json
from collections.abc import Iterator, Sequence
from typing import Any, Self, cast

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGenerationChunk
from langgraph.graph.state import CompiledStateGraph
from pydantic import Field

from mini_deer_agent.agents import build_agent_graph
from mini_deer_agent.streaming import stream_agent_messages, stream_agent_updates
from mini_deer_agent.tools import web_search


class ToolAwareFakeModel(FakeMessagesListChatModel):
    """模拟支持工具绑定的聊天模型，避免流式图测试访问 DeepSeek。"""

    bound_tool_names: list[str] = Field(default_factory=list)

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Self:
        """记录模型可选择的工具，并继续返回当前假模型。"""
        self.bound_tool_names = [tool.name for tool in tools]
        return self


class ToolAwareStreamingFakeModel(ToolAwareFakeModel):
    """把预设 AIMessage 转成文本或工具调用 chunk，模拟真实模型流。"""

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """按字符发送正文，并把结构化工具请求作为 tool_call_chunks 发送。"""
        response = self.responses[self.i]
        # 每次模型调用消费一条预设响应，工具循环会继续读取下一条。
        self.i = self.i + 1 if self.i < len(self.responses) - 1 else 0
        if not isinstance(response, AIMessage):
            raise TypeError("流式测试响应必须是 AIMessage")

        if response.tool_calls:
            for index, tool_call in enumerate(response.tool_calls):
                # 真实模型会逐步返回工具名和 JSON 参数；测试用一个完整 chunk 表达同一语义。
                yield ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="",
                        id=response.id,
                        tool_call_chunks=[
                            {
                                "name": tool_call["name"],
                                "args": json.dumps(
                                    tool_call["args"],
                                    ensure_ascii=False,
                                ),
                                "id": tool_call["id"],
                                "index": index,
                                "type": "tool_call_chunk",
                            }
                        ],
                        chunk_position=(
                            "last" if index == len(response.tool_calls) - 1 else None
                        ),
                    )
                )
            return

        for index, content in enumerate(response.text):
            # 每个字符代表一个可独立观察的模型增量，最后一块显式标记消息结束。
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=content,
                    id=response.id,
                    chunk_position=(
                        "last" if index == len(response.text) - 1 else None
                    ),
                )
            )


class RecordingStreamGraph:
    """记录迭代何时真正开始，用于验证生成器没有预先执行整张图。"""

    def __init__(self) -> None:
        """初始化尚未开始迭代的观察标记。"""
        self.started = False

    def stream(
        self,
        input_state: dict[str, list[HumanMessage]],
        *,
        config: dict[str, Any] | None,
        stream_mode: str,
    ) -> Iterator[dict[str, Any]]:
        """开始消费时设置标记，并返回一个最小 model 更新。"""
        self.started = True
        yield {
            "model": {
                "messages": [AIMessage(content="惰性流已开始。")],
            }
        }


def test_stream_agent_updates_stays_lazy_until_iteration() -> None:
    """创建流对象不应执行图，第一次迭代才应开始节点运行。"""
    recording_graph = RecordingStreamGraph()
    # 测试替身只实现本功能使用的 stream 接口，cast 避免伪造完整编译图。
    graph = cast(CompiledStateGraph, recording_graph)

    updates = stream_agent_updates(
        graph,
        [HumanMessage(content="开始测试")],
    )

    assert recording_graph.started is False
    first_update = next(updates)
    assert recording_graph.started is True
    assert first_update["model"]["messages"][0].text == "惰性流已开始。"


def test_stream_agent_updates_yields_direct_model_answer() -> None:
    """模型无需工具时，节点级流只应产生一次 model 更新。"""
    model = ToolAwareFakeModel(
        responses=[AIMessage(content="你好，我是 Mini Deer Agent。")]
    )
    graph = build_agent_graph(model)

    updates = list(
        stream_agent_updates(
            graph,
            [HumanMessage(content="你好！")],
        )
    )

    assert [list(update) for update in updates] == [["model"]]
    response = updates[0]["model"]["messages"][0]
    assert isinstance(response, AIMessage)
    assert response.text == "你好，我是 Mini Deer Agent。"


def test_stream_agent_updates_yields_complete_tool_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """搜索请求应按 model、tools、model 顺序逐步返回三次更新。"""
    def fake_search(query: str, max_results: int = 5) -> str:
        """返回固定搜索结果，避免节点级流测试访问 DDGS。"""
        return json.dumps(
            {
                "query": query,
                "total_results": 1,
                "results": [
                    {
                        "title": "北京天气",
                        "url": "https://example.com/weather",
                        "content": "北京当前晴，温度 26°C。",
                    }
                ],
            },
            ensure_ascii=False,
        )

    # ToolNode 复用已注册工具对象，替换底层函数即可隔离真实 HTTP 请求。
    monkeypatch.setattr(web_search, "func", fake_search)
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": "北京当前天气", "max_results": 3},
                        "id": "call-stream-search-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="北京当前晴，温度 26°C。"),
        ]
    )
    graph = build_agent_graph(model)

    updates = list(
        stream_agent_updates(
            graph,
            [HumanMessage(content="请查询北京当前天气。")],
        )
    )

    assert [list(update) for update in updates] == [
        ["model"],
        ["tools"],
        ["model"],
    ]
    tool_request = updates[0]["model"]["messages"][0]
    tool_result = updates[1]["tools"]["messages"][0]
    final_answer = updates[2]["model"]["messages"][0]
    assert tool_request.tool_calls[0]["name"] == "web_search"
    assert isinstance(tool_result, ToolMessage)
    assert tool_result.tool_call_id == "call-stream-search-1"
    assert "https://example.com/weather" in tool_result.text
    assert isinstance(final_answer, AIMessage)
    assert final_answer.text == "北京当前晴，温度 26°C。"


def test_stream_agent_messages_yields_text_chunks_with_model_metadata() -> None:
    """messages 模式应逐块返回正文，并标明消息来自 model 节点。"""
    model = ToolAwareStreamingFakeModel(
        responses=[AIMessage(content="你好", id="message-direct-1")]
    )
    graph = build_agent_graph(model)

    events = list(
        stream_agent_messages(
            graph,
            [HumanMessage(content="请打招呼。")],
        )
    )

    chunks = [message for message, _metadata in events]
    assert all(isinstance(message, AIMessageChunk) for message in chunks)
    assert "".join(message.text for message in chunks) == "你好"
    assert {message.id for message in chunks} == {"message-direct-1"}
    assert {metadata["langgraph_node"] for _message, metadata in events} == {
        "model"
    }


def test_stream_agent_messages_keeps_tool_result_and_accumulates_by_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """工具循环应流出工具请求、工具结果，并按消息 ID 拼回最终正文。"""
    def fake_search(query: str, max_results: int = 5) -> str:
        """返回固定搜索结果，隔离 token 流测试与真实 DDGS。"""
        return json.dumps(
            {
                "query": query,
                "total_results": 1,
                "results": [
                    {
                        "title": "北京天气",
                        "url": "https://example.com/weather",
                        "content": "北京当前晴，温度 26°C。",
                    }
                ],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(web_search, "func", fake_search)
    model = ToolAwareStreamingFakeModel(
        responses=[
            AIMessage(
                content="",
                id="message-tool-request-1",
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": "北京当前天气"},
                        "id": "call-token-search-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="北京晴。",
                id="message-final-answer-1",
            ),
        ]
    )
    graph = build_agent_graph(model)

    events = list(
        stream_agent_messages(
            graph,
            [HumanMessage(content="请查询北京当前天气。")],
        )
    )

    tool_request = next(
        message
        for message, _metadata in events
        if isinstance(message, AIMessageChunk) and message.tool_calls
    )
    tool_result = next(
        message for message, _metadata in events if isinstance(message, ToolMessage)
    )
    text_by_message_id: dict[str, str] = {}
    for message, _metadata in events:
        # 相同消息 ID 的文本 chunk 必须按抵达顺序累积，不能覆盖前一块。
        if isinstance(message, AIMessageChunk) and message.text and message.id:
            text_by_message_id[message.id] = (
                text_by_message_id.get(message.id, "") + message.text
            )

    assert tool_request.tool_calls[0]["name"] == "web_search"
    assert isinstance(tool_result, ToolMessage)
    assert tool_result.tool_call_id == "call-token-search-1"
    assert "https://example.com/weather" in tool_result.text
    assert text_by_message_id["message-final-answer-1"] == "北京晴。"
    assert [
        metadata["langgraph_node"] for message, metadata in events if message.text
    ] == ["tools", "model", "model", "model", "model"]


def test_projector_emits_reasoning_delta_for_reasoning_content() -> None:
    """携带 reasoning_content 的 assistant chunk 应投影出 reasoning_delta 事件。"""
    from mini_deer_agent.streaming.projector import project_run_events

    chunk = AIMessageChunk(
        content="",
        id="message-1",
        additional_kwargs={"reasoning_content": "先分析问题，再回答。"},
    )
    events = list(
        project_run_events(
            [(chunk, {})],
            run_id="11111111-1111-4111-8111-111111111111",
            thread_id="22222222-2222-4222-8222-222222222222",
        )
    )

    reasoning = [event for event in events if event.event == "reasoning_delta"]
    assert len(reasoning) == 1
    assert reasoning[0].payload["text"] == "先分析问题，再回答。"
    assert reasoning[0].message_id is not None
