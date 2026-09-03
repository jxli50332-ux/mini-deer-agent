"""验证动态日期时间只进入可信模型视图，不污染对话状态。"""

import asyncio
import json
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, Self

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from mini_deer_agent.agents import build_agent_graph
from mini_deer_agent.agents.middleware import project_dynamic_context
from mini_deer_agent.tools.task import create_task_tool


class RecordingFakeModel(FakeMessagesListChatModel):
    """记录模型实际收到的工具与消息，避免测试访问真实模型。"""

    bound_tool_name_histories: list[list[str]] = Field(default_factory=list)
    received_histories: list[list[BaseMessage]] = Field(default_factory=list)

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Self:
        """记录每次模型调用可见的工具 schema。"""
        del tool_choice, kwargs
        self.bound_tool_name_histories.append([tool.name for tool in tools])
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        """保存模型边界消息后复用固定响应实现。"""
        self.received_histories.append(list(messages))
        return super()._generate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


def _fixed_time(hour: int, minute: int = 14) -> datetime:
    """创建带可见名称和 UTC+08:00 偏移的确定性测试时间。"""
    return datetime(
        2026,
        8,
        31,
        hour,
        minute,
        46,
        987654,
        tzinfo=timezone(timedelta(hours=8), "Test <Zone>"),
    )


def _task_call(call_id: str) -> dict[str, Any]:
    """构造一次可直接调用的通用子 Agent 委派。"""
    return {
        "name": "task",
        "args": {
            "description": "核对日期",
            "prompt": "说明当前日期。",
            "subagent_type": "general-purpose",
        },
        "id": call_id,
        "type": "tool_call",
    }


def test_dynamic_context_formats_trusted_aware_datetime() -> None:
    """Runtime 时间应形成稳定、转义且保留原消息元数据的系统区块。"""
    original = SystemMessage(
        content="基础系统提示。",
        id="trusted-system",
        additional_kwargs={"source": "prompt-builder"},
    )

    projected = project_dynamic_context(original, clock=lambda: _fixed_time(22))

    assert projected is not original
    assert original.text == "基础系统提示。"
    assert projected.id == "trusted-system"
    assert projected.additional_kwargs == {"source": "prompt-builder"}
    assert '<dynamic_context source="runtime">' in projected.text
    assert (
        "<current_datetime>2026-08-31T22:14:46+08:00</current_datetime>"
        in projected.text
    )
    assert "<current_date>2026-08-31</current_date>" in projected.text
    assert "<current_time>22:14:46</current_time>" in projected.text
    assert "<current_weekday>星期一 / Monday</current_weekday>" in projected.text
    assert "<timezone_name>Test &lt;Zone&gt;</timezone_name>" in projected.text
    assert "<utc_offset>UTC+08:00</utc_offset>" in projected.text


def test_dynamic_context_rejects_naive_datetime() -> None:
    """缺少 UTC 偏移的时间不能伪装成可信本地时间。"""
    with pytest.raises(ValueError, match="timezone-aware"):
        project_dynamic_context(
            SystemMessage(content="基础系统提示。"),
            clock=lambda: datetime(2026, 8, 31, 22, 14, 46),
        )


def test_main_graph_refreshes_context_and_keeps_checkpoint_clean() -> None:
    """同一线程的新 Run 应刷新时间，但状态只保存真实对话消息。"""
    moments = iter((_fixed_time(22), _fixed_time(23, 5)))
    model = RecordingFakeModel(
        responses=[
            AIMessage(content="第一轮回答。"),
            AIMessage(content="第二轮回答。"),
        ]
    )
    graph = build_agent_graph(
        model,
        checkpointer=InMemorySaver(),
        dynamic_context_clock=lambda: next(moments),
    )
    config = {"configurable": {"thread_id": "dynamic-context-thread"}}

    graph.invoke({"messages": [HumanMessage(content="第一轮。")]}, config)
    graph.invoke({"messages": [HumanMessage(content="第二轮。")]}, config)

    assert len(model.received_histories) == 2
    first_system = model.received_histories[0][0]
    second_system = model.received_histories[1][0]
    assert isinstance(first_system, SystemMessage)
    assert isinstance(second_system, SystemMessage)
    assert "<current_time>22:14:46</current_time>" in first_system.text
    assert "<current_time>23:05:46</current_time>" in second_system.text
    assert all(
        sum(isinstance(message, SystemMessage) for message in history) == 1
        for history in model.received_histories
    )

    persisted = graph.get_state(config).values["messages"]
    assert [message.text for message in persisted] == [
        "第一轮。",
        "第一轮回答。",
        "第二轮。",
        "第二轮回答。",
    ]
    assert not any(isinstance(message, SystemMessage) for message in persisted)
    assert all("<dynamic_context" not in message.text for message in persisted)


def test_async_main_graph_receives_same_dynamic_context_contract() -> None:
    """Web 使用的异步图也必须在唯一系统消息中获得可信时间。"""
    model = RecordingFakeModel(responses=[AIMessage(content="异步回答。")])

    result = asyncio.run(
        build_agent_graph(
            model,
            dynamic_context_clock=lambda: _fixed_time(22),
        ).ainvoke({"messages": [HumanMessage(content="现在几点？")]})
    )

    received = model.received_histories[0]
    assert sum(isinstance(message, SystemMessage) for message in received) == 1
    assert "<current_time>22:14:46</current_time>" in received[0].text
    assert all("<dynamic_context" not in message.text for message in result["messages"])


def test_dynamic_context_coexists_with_skill_and_tool_policy_projection() -> None:
    """技能正文、工具白名单和时间必须合并到同一个可信系统消息。"""
    model = RecordingFakeModel(responses=[AIMessage(content="天气说明。")])

    result = build_agent_graph(
        model,
        dynamic_context_clock=lambda: _fixed_time(22),
    ).invoke(
        {
            "messages": [
                HumanMessage(content="/weather-briefing 说明北京今天的天气。")
            ]
        }
    )

    received = model.received_histories[0]
    assert sum(isinstance(message, SystemMessage) for message in received) == 1
    system_text = received[0].text
    assert '<activated_skill name="weather-briefing">' in system_text
    assert '<active_skill_tool_policy name="weather-briefing">' in system_text
    assert '<dynamic_context source="runtime">' in system_text
    assert all("<dynamic_context" not in message.text for message in result["messages"])


def test_task_subagent_receives_dynamic_context_without_echoing_it() -> None:
    """通用子 Agent 应获得同一时间契约，但委派结果不能附带内部区块。"""
    model = RecordingFakeModel(responses=[AIMessage(content="日期核对完成。")])
    task_tool = create_task_tool(
        model,
        dynamic_context_clock=lambda: _fixed_time(22),
    )

    result = task_tool.invoke(_task_call("call-dynamic-context"))

    payload = json.loads(result.text)
    assert payload["result"] == "日期核对完成。"
    received = model.received_histories[0]
    assert sum(isinstance(message, SystemMessage) for message in received) == 1
    assert '<dynamic_context source="runtime">' in received[0].text
    assert "<current_time>22:14:46</current_time>" in received[0].text
    assert "<dynamic_context" not in result.text
