"""验证模型节点的依赖注入、执行路径和消息合并行为。"""

import asyncio
import json
from collections.abc import Sequence
from importlib import import_module
from pathlib import Path
from typing import Any, Self
from uuid import uuid4

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
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from mini_deer_agent.agents import (
    AgentPromptContext,
    BuiltAgentPrompt,
    async_model_node,
    build_agent_graph,
    model_node,
)
from mini_deer_agent.agents.middleware import (
    RunOutputStore,
    ToolOutputBudgetPolicy,
    tool_result_meta,
)
from mini_deer_agent.skills import (
    BuiltInSkill,
    BuiltInSkillCatalog,
    SkillCatalogError,
    SkillManagementService,
    UserSkillManager,
)
from mini_deer_agent.streaming import astream_agent_messages
from mini_deer_agent.streaming.projector import aproject_run_events
from mini_deer_agent.tools import get_weather, web_fetch, web_search


class ToolAwareFakeModel(FakeMessagesListChatModel):
    """记录绑定工具并按顺序返回预设消息，避免测试访问 DeepSeek。"""

    bound_tool_names: list[str] = Field(default_factory=list)
    bound_tool_name_histories: list[list[str]] = Field(default_factory=list)
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
        self.bound_tool_name_histories.append(list(self.bound_tool_names))
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


def _delegation_task_call(
    call_id: str,
    description: str,
) -> dict[str, Any]:
    """构造一个自包含的通用子 Agent 调用。"""
    return {
        "name": "task",
        "args": {
            "description": description,
            "prompt": f"独立完成：{description}",
            "subagent_type": "research",
        },
        "id": call_id,
        "type": "tool_call",
    }


def _skill_activation_call(call_id: str, name: str) -> dict[str, Any]:
    """构造一个只携带精确技能名称的自动激活调用。"""
    return {
        "name": "activate_skill",
        "args": {"name": name},
        "id": call_id,
        "type": "tool_call",
    }


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
    assert "`/structured-explainer`" in prompt_text
    assert '<activated_skill name="structured-explainer">' not in prompt_text
    assert [type(message).__name__ for message in result["messages"]] == [
        "HumanMessage",
        "AIMessage",
    ]


def test_compiled_graph_activates_builtin_skill_without_persisting_projection() -> None:
    """显式 slash 应清理模型任务视图并注入技能，但 checkpoint 保留原始用户消息。"""
    model = ToolAwareFakeModel(responses=[AIMessage(content="结构化解释完成。")])
    graph = build_agent_graph(model)

    result = graph.invoke(
        {
            "messages": [
                HumanMessage(
                    content=(
                        "/structured-explainer 解释什么是 LangGraph checkpoint"
                    )
                )
            ]
        }
    )

    assert len(model.received_histories) == 1
    received = model.received_histories[0]
    assert '<activated_skill name="structured-explainer">' in received[0].text
    assert received[-1].text == "解释什么是 LangGraph checkpoint"
    assert result["messages"][0].text == (
        "/structured-explainer 解释什么是 LangGraph checkpoint"
    )
    assert all(
        '<activated_skill name="structured-explainer">' not in message.text
        for message in result["messages"]
    )


def test_compiled_graph_automatically_activates_skill_before_final_answer() -> None:
    """模型的可见激活调用完成后，下一次模型调用才获得技能正文。"""
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    _skill_activation_call(
                        "call-auto-activate",
                        "structured-explainer",
                    )
                ],
            ),
            AIMessage(content="已按结构化技能完成。"),
        ]
    )
    graph = build_agent_graph(model)

    result = graph.invoke(
        {
            "messages": [
                HumanMessage(content="请分层、通俗地解释 LangGraph checkpoint。")
            ]
        }
    )

    assert "activate_skill" in model.bound_tool_names
    assert len(model.received_histories) == 2
    assert '<activated_skill name="structured-explainer">' not in (
        model.received_histories[0][0].text
    )
    assert '<activated_skill name="structured-explainer">' in (
        model.received_histories[1][0].text
    )
    assert model.received_histories[1][1].text == (
        "请分层、通俗地解释 LangGraph checkpoint。"
    )
    tool_result = next(
        message for message in result["messages"] if isinstance(message, ToolMessage)
    )
    assert tool_result.name == "activate_skill"
    assert json.loads(tool_result.text) == {
        "version": 1,
        "kind": "skill_activation",
        "status": "activated",
        "name": "structured-explainer",
        "message": "技能已为当前 Run 激活。",
    }
    assert "### 一句话结论" not in tool_result.text


def test_manual_skill_draft_tool_is_bound_when_automatic_install_is_disabled(
    tmp_path: Path,
) -> None:
    """关闭自动安装后，Agent 仍应能创建等待用户确认的 Skill 草稿。"""
    builtin_root = tmp_path / "builtin"
    builtin_root.mkdir()
    service = SkillManagementService(
        UserSkillManager(tmp_path / "managed", builtin_root=builtin_root)
    )
    service.update_agent_settings(creation_enabled=False, expected_revision=0)
    model = ToolAwareFakeModel(responses=[AIMessage(content="草稿已提交确认。")])

    build_agent_graph(
        model,
        skill_management_service=service,
        skill_creation_enabled=False,
    ).invoke({"messages": [HumanMessage(content="帮我写一个会议纪要 Skill。")]})

    assert "skill_manage" in model.bound_tool_names


def test_passive_run_cannot_execute_specialized_weather_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未激活天气技能时，模型契约和执行边界都必须拒绝专用工具。"""
    called_cities: list[str] = []

    def unexpected_weather(city: str) -> str:
        called_cities.append(city)
        return "不应执行"

    monkeypatch.setattr(get_weather, "func", unexpected_weather)
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_weather",
                        "args": {"city": "北京"},
                        "id": "call-passive-weather",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="天气专用工具当前不可用。"),
        ]
    )

    result = build_agent_graph(model).invoke(
        {"messages": [HumanMessage(content="普通回答，不要激活技能。")]}
    )

    assert "get_weather" not in model.bound_tool_name_histories[0]
    assert called_cities == []
    blocked = next(
        message
        for message in result["messages"]
        if isinstance(message, ToolMessage) and message.name == "get_weather"
    )
    assert blocked.status == "error"
    assert json.loads(blocked.text)["reason"] == "skill_tool_not_allowed"


def test_automatic_weather_skill_filters_schema_and_executes_allowed_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """自动激活后只绑定框架工具与天气工具，并把真实结果交回模型。"""
    called_cities: list[str] = []

    def fake_weather(city: str) -> str:
        called_cities.append(city)
        return "北京当前天气：晴；温度 26°C；来源 Open-Meteo。"

    monkeypatch.setattr(get_weather, "func", fake_weather)
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    _skill_activation_call(
                        "call-activate-weather",
                        "weather-briefing",
                    )
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_weather",
                        "args": {"city": "北京"},
                        "id": "call-weather-allowed",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="北京现在晴，26°C。"),
        ]
    )

    result = build_agent_graph(model).invoke(
        {"messages": [HumanMessage(content="北京现在天气怎么样？")]}
    )

    restricted_names = [
        "write_todos",
        "ask_clarification",
        "activate_skill",
        "get_weather",
    ]
    assert "get_weather" not in model.bound_tool_name_histories[0]
    assert model.bound_tool_name_histories[1:] == [
        restricted_names,
        restricted_names,
    ]
    assert called_cities == ["北京"]
    assert "实际可用工具清单" in model.received_histories[1][0].text
    assert "`get_weather`" in model.received_histories[1][0].text
    assert "`web_search`" not in model.received_histories[1][0].text.split(
        '<active_skill_tool_policy name="weather-briefing">', 1
    )[1]
    weather_result = next(
        message
        for message in result["messages"]
        if isinstance(message, ToolMessage) and message.name == "get_weather"
    )
    assert "Open-Meteo" in weather_result.text
    assert result["messages"][-1].text == "北京现在晴，26°C。"


def test_slash_weather_skill_is_restricted_from_first_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式 slash 不需要激活工具，首次模型调用便只能看到天气权限集合。"""
    monkeypatch.setattr(
        get_weather,
        "func",
        lambda city: f"{city}当前天气：多云；来源 Open-Meteo。",
    )
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_weather",
                        "args": {"city": "上海"},
                        "id": "call-slash-weather",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="上海当前多云。"),
        ]
    )

    result = build_agent_graph(model).invoke(
        {"messages": [HumanMessage(content="/weather-briefing 上海现在天气怎么样？")]}
    )

    assert model.bound_tool_name_histories == [
        [
            "write_todos",
            "ask_clarification",
            "activate_skill",
            "get_weather",
        ],
        [
            "write_todos",
            "ask_clarification",
            "activate_skill",
            "get_weather",
        ],
    ]
    assert not any(
        isinstance(message, ToolMessage) and message.name == "activate_skill"
        for message in result["messages"]
    )
    assert result["messages"][-1].text == "上海当前多云。"


def test_weather_skill_blocks_disallowed_execution_as_an_exclusive_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """受限技能伪造联网调用时不得执行，且同批获准调用也必须安全跳过。"""
    search_queries: list[str] = []
    weather_cities: list[str] = []
    monkeypatch.setattr(
        web_search,
        "func",
        lambda query, max_results=5: search_queries.append(query) or "不应执行",
    )
    monkeypatch.setattr(
        get_weather,
        "func",
        lambda city: weather_cities.append(city) or "不应执行",
    )
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": "北京天气"},
                        "id": "call-weather-denied-search",
                        "type": "tool_call",
                    },
                    {
                        "name": "get_weather",
                        "args": {"city": "北京"},
                        "id": "call-weather-skipped-allowed",
                        "type": "tool_call",
                    },
                ],
            ),
            AIMessage(content="已停止未授权工具批次。"),
        ]
    )

    result = build_agent_graph(model).invoke(
        {"messages": [HumanMessage(content="/weather-briefing 北京天气")]}
    )

    assert search_queries == []
    assert weather_cities == []
    tool_results = [
        message
        for message in result["messages"]
        if isinstance(message, ToolMessage)
    ]
    assert [json.loads(message.text)["reason"] for message in tool_results] == [
        "skill_tool_not_allowed",
        "skill_policy_batch_rejected",
    ]


def test_empty_allowed_tools_keeps_only_framework_controls() -> None:
    """显式空白名单仍保留澄清、任务清单和激活控制，不开放业务工具。"""
    catalog = BuiltInSkillCatalog(
        skills=(
            BuiltInSkill(
                name="framework-only",
                description="只验证框架控制工具。",
                instructions="直接回答测试问题。",
                source_file=Path("framework-only/SKILL.md"),
                allowed_tools=(),
            ),
        )
    )
    model = ToolAwareFakeModel(responses=[AIMessage(content="完成。")])

    build_agent_graph(model, skill_catalog=catalog).invoke(
        {"messages": [HumanMessage(content="/framework-only 执行测试。")]}
    )

    assert model.bound_tool_name_histories == [
        ["write_todos", "ask_clarification", "activate_skill"]
    ]


def test_graph_rejects_skill_policy_that_names_unregistered_tool() -> None:
    """内置资产引用未知工具时必须在构图阶段失败，不能运行时静默放宽。"""
    catalog = BuiltInSkillCatalog(
        skills=(
            BuiltInSkill(
                name="broken-policy",
                description="引用未知工具的测试技能。",
                instructions="不应进入模型。",
                source_file=Path("broken-policy/SKILL.md"),
                allowed_tools=("missing_tool",),
            ),
        )
    )
    model = ToolAwareFakeModel(responses=[AIMessage(content="不应调用。")])

    with pytest.raises(SkillCatalogError, match="unknown allowed tool"):
        build_agent_graph(model, skill_catalog=catalog)


def test_weather_tool_policy_expires_on_next_run_in_same_thread() -> None:
    """新用户消息必须恢复被动工具集合，不能继承上一轮天气权限。"""
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(content="第一轮天气回答。"),
            AIMessage(content="第二轮普通回答。"),
        ]
    )
    graph = build_agent_graph(model, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "weather-policy-expiry"}}

    graph.invoke(
        {"messages": [HumanMessage(content="/weather-briefing 北京天气")]},
        config,
    )
    graph.invoke(
        {"messages": [HumanMessage(content="解释普通问题。") ]},
        config,
    )

    assert model.bound_tool_name_histories[0] == [
        "write_todos",
        "ask_clarification",
        "activate_skill",
        "get_weather",
    ]
    assert model.bound_tool_name_histories[1] == [
        "web_search",
        "web_fetch",
        "write_todos",
        "ask_clarification",
        "inspect_execution_environment",
        "activate_skill",
        "task",
    ]
    assert '<active_skill_tool_policy name="weather-briefing">' in (
        model.received_histories[0][0].text
    )
    assert "<active_skill_tool_policy" not in (
        model.received_histories[1][0].text
    )


def test_async_slash_weather_executes_registered_coroutine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Web 使用的异步主图必须执行天气协程，并保持相同白名单。"""
    called_cities: list[str] = []

    async def fake_weather(city: str) -> str:
        called_cities.append(city)
        return f"{city}当前天气：晴；来源 Open-Meteo。"

    monkeypatch.setattr(get_weather, "coroutine", fake_weather)
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_weather",
                        "args": {"city": "广州"},
                        "id": "call-async-weather",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="广州当前晴。"),
        ]
    )

    result = asyncio.run(
        build_agent_graph(model).ainvoke(
            {"messages": [HumanMessage(content="/weather-briefing 广州天气")]}
        )
    )

    assert called_cities == ["广州"]
    assert result["messages"][-1].text == "广州当前晴。"


def test_automatic_skill_activation_reaches_product_tool_event() -> None:
    """自动激活结果必须进入版本化产品流，供现有通用工具卡直接展示。"""

    async def collect_events() -> list:
        """运行真实异步消息流和产品事件投影，不绕过 Web 使用的边界。"""
        model = ToolAwareFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        _skill_activation_call(
                            "call-visible-activation",
                            "structured-explainer",
                        )
                    ],
                ),
                AIMessage(content="结构化解释完成。"),
            ]
        )
        return [
            event
            async for event in aproject_run_events(
                astream_agent_messages(
                    build_agent_graph(model),
                    [HumanMessage(content="结构化解释 checkpoint。")],
                ),
                run_id="run-visible-activation",
                thread_id="thread-visible-activation",
            )
        ]

    run_events = asyncio.run(collect_events())
    tool_event = next(event for event in run_events if event.event == "tool_result")

    assert tool_event.payload["name"] == "activate_skill"
    assert tool_event.payload["tool_call_id"] == "call-visible-activation"
    assert json.loads(tool_event.payload["content"])["status"] == "activated"
    assert "### 一句话结论" not in tool_event.payload["content"]


def test_skill_activation_is_exclusive_and_settles_mixed_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """激活调用必须独占本批，普通工具和 task 都不得抢跑或悬空。"""
    search_queries: list[str] = []

    def unexpected_search(query: str, max_results: int = 5) -> str:
        search_queries.append(query)
        return "不应执行"

    monkeypatch.setattr(web_search, "func", unexpected_search)
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": "不应搜索"},
                        "id": "call-auto-skipped-search",
                        "type": "tool_call",
                    },
                    _skill_activation_call(
                        "call-auto-exclusive",
                        "structured-explainer",
                    ),
                    _delegation_task_call("call-auto-skipped-task", "不应委派"),
                ],
            ),
            AIMessage(content="激活后直接完成。"),
        ]
    )

    result = build_agent_graph(model).invoke(
        {"messages": [HumanMessage(content="结构化解释 checkpoint。")]}
    )

    assert search_queries == []
    tool_results = [
        message for message in result["messages"] if isinstance(message, ToolMessage)
    ]
    assert [message.tool_call_id for message in tool_results] == [
        "call-auto-skipped-search",
        "call-auto-exclusive",
        "call-auto-skipped-task",
    ]
    assert json.loads(tool_results[0].text)["reason"] == (
        "skill_activation_requested"
    )
    assert tool_results[1].status == "success"
    assert json.loads(tool_results[2].text)["reason"] == (
        "skill_activation_requested"
    )


def test_skill_activation_is_idempotent_but_cannot_switch_within_run() -> None:
    """同一 Run 可重复确认同名技能，但不能借后续调用切换到另一个技能。"""
    catalog = BuiltInSkillCatalog(
        skills=(
            BuiltInSkill(
                name="alpha-skill",
                description="Alpha 测试技能。",
                instructions="ALPHA_SKILL_BODY",
                source_file=Path("alpha-skill/SKILL.md"),
            ),
            BuiltInSkill(
                name="beta-skill",
                description="Beta 测试技能。",
                instructions="BETA_SKILL_BODY",
                source_file=Path("beta-skill/SKILL.md"),
            ),
        )
    )
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[_skill_activation_call("call-alpha-1", "alpha-skill")],
            ),
            AIMessage(
                content="",
                tool_calls=[_skill_activation_call("call-alpha-2", "alpha-skill")],
            ),
            AIMessage(
                content="",
                tool_calls=[_skill_activation_call("call-beta", "beta-skill")],
            ),
            AIMessage(content="保持 Alpha 完成。"),
        ]
    )

    result = build_agent_graph(model, skill_catalog=catalog).invoke(
        {"messages": [HumanMessage(content="执行需要 Alpha 的任务。")]}
    )

    assert len(model.received_histories) == 4
    assert all(
        "ALPHA_SKILL_BODY" in history[0].text
        for history in model.received_histories[1:]
    )
    assert all("BETA_SKILL_BODY" not in history[0].text for history in model.received_histories)
    tool_results = [
        message
        for message in result["messages"]
        if isinstance(message, ToolMessage) and message.name == "activate_skill"
    ]
    assert [message.status for message in tool_results] == [
        "success",
        "success",
        "error",
    ]
    assert json.loads(tool_results[-1].text)["reason"] == (
        "skill_activation_conflict"
    )


def test_explicit_slash_skill_cannot_be_replaced_by_automatic_activation() -> None:
    """显式 slash 对当前 Run 有最高优先级，模型后续激活调用只能失败关闭。"""
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    _skill_activation_call(
                        "call-after-explicit",
                        "structured-explainer",
                    )
                ],
            ),
            AIMessage(content="继续按显式技能完成。"),
        ]
    )

    result = build_agent_graph(model).invoke(
        {
            "messages": [
                HumanMessage(
                    content="/structured-explainer 解释 checkpoint"
                )
            ]
        }
    )

    assert len(model.received_histories) == 2
    assert all(
        '<activated_skill name="structured-explainer">' in history[0].text
        for history in model.received_histories
    )
    tool_result = next(
        message for message in result["messages"] if isinstance(message, ToolMessage)
    )
    assert tool_result.status == "error"
    assert json.loads(tool_result.text)["reason"] == "explicit_skill_active"


def test_unknown_or_empty_skill_command_finishes_without_calling_model() -> None:
    """确定性的 slash 错误应直接形成 Assistant 结果，不能消耗模型请求。"""
    for user_text, expected in [
        ("/missing-skill 执行任务", "未找到技能 `/missing-skill`"),
        (
            "/structured-explainer",
            "请在 `/structured-explainer` 后提供任务内容",
        ),
    ]:
        model = ToolAwareFakeModel(responses=[AIMessage(content="不应调用。")])
        graph = build_agent_graph(model)

        result = graph.invoke({"messages": [HumanMessage(content=user_text)]})

        assert model.received_histories == []
        assert expected in result["messages"][-1].text


def test_skill_command_failure_reaches_async_product_event_stream() -> None:
    """确定性技能错误必须产生 Assistant delta，真实 Web 页面才能看到原因。"""

    async def collect_events() -> list:
        """运行与 Web Run 相同的异步消息和产品事件投影链。"""
        model = ToolAwareFakeModel(responses=[AIMessage(content="不应调用。")])
        graph = build_agent_graph(model)
        message_events = astream_agent_messages(
            graph,
            [HumanMessage(content="/missing-skill 执行任务")],
        )
        events = [
            event
            async for event in aproject_run_events(
                message_events,
                run_id="run-skill-failure",
                thread_id="thread-skill-failure",
            )
        ]
        assert model.received_histories == []
        return events

    run_events = asyncio.run(collect_events())

    assert [event.event for event in run_events] == [
        "run_started",
        "ai_delta",
        "run_completed",
    ]
    assert "未找到技能 `/missing-skill`" in (
        run_events[1].payload["text"]
    )


def test_skill_activation_applies_to_all_model_calls_in_current_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一 Run 的工具循环必须持续携带技能，不能只约束首次模型调用。"""
    monkeypatch.setattr(
        web_search,
        "func",
        lambda query, max_results=5: json.dumps(
            {"query": query, "results": []},
            ensure_ascii=False,
        ),
    )
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": "LangGraph checkpoint"},
                        "id": "call-skill-search",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="按技能格式完成。"),
        ]
    )
    graph = build_agent_graph(model)

    graph.invoke(
        {
            "messages": [
                HumanMessage(
                    content="/structured-explainer 解释 LangGraph checkpoint"
                )
            ]
        }
    )

    assert len(model.received_histories) == 2
    assert all(
        '<activated_skill name="structured-explainer">' in history[0].text
        for history in model.received_histories
    )


def test_skill_activation_expires_on_next_run_in_same_thread() -> None:
    """新用户消息开始的新 Run 不得继承上一轮显式技能系统指令。"""
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(content="第一轮完成。"),
            AIMessage(content="第二轮直接回答。"),
        ]
    )
    graph = build_agent_graph(model, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "skill-expiry-thread"}}

    graph.invoke(
        {
            "messages": [
                HumanMessage(
                    content="/structured-explainer 解释 checkpoint"
                )
            ]
        },
        config,
    )
    graph.invoke(
        {"messages": [HumanMessage(content="只回答：2 + 2 等于几？")]},
        config,
    )

    assert '<activated_skill name="structured-explainer">' in (
        model.received_histories[0][0].text
    )
    assert '<activated_skill name="structured-explainer">' not in (
        model.received_histories[1][0].text
    )
    assert model.received_histories[1][-1].text == "只回答：2 + 2 等于几？"


def test_automatic_skill_activation_expires_on_next_run_in_same_thread() -> None:
    """自动激活只从最新 HumanMessage 后取证，下一 Run 不能继承旧工具结果。"""
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    _skill_activation_call(
                        "call-auto-expiry",
                        "structured-explainer",
                    )
                ],
            ),
            AIMessage(content="第一轮按技能完成。"),
            AIMessage(content="第二轮直接回答。"),
        ]
    )
    graph = build_agent_graph(model, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "auto-skill-expiry-thread"}}

    graph.invoke(
        {"messages": [HumanMessage(content="分层解释 checkpoint。")]},
        config,
    )
    graph.invoke(
        {"messages": [HumanMessage(content="只回答：3 + 3 等于几？")]},
        config,
    )

    assert '<activated_skill name="structured-explainer">' not in (
        model.received_histories[0][0].text
    )
    assert '<activated_skill name="structured-explainer">' in (
        model.received_histories[1][0].text
    )
    assert '<activated_skill name="structured-explainer">' not in (
        model.received_histories[2][0].text
    )
    assert model.received_histories[2][-1].text == "只回答：3 + 3 等于几？"


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
            available_tool_names=(
                "web_search",
                "web_fetch",
                "write_todos",
                "ask_clarification",
                "inspect_execution_environment",
                "activate_skill",
                "task",
            ),
            available_skills=BuiltInSkillCatalog.discover().summaries,
        )
    ]


def test_empty_skill_catalog_compiles_without_exposing_activation_tool() -> None:
    """没有技能时条件图仍可编译运行，模型也不应看到无意义的激活工具。"""
    model = ToolAwareFakeModel(responses=[AIMessage(content="直接完成。")])

    result = build_agent_graph(
        model,
        skill_catalog=BuiltInSkillCatalog(skills=()),
    ).invoke({"messages": [HumanMessage(content="普通问题。")]})

    assert "activate_skill" not in model.bound_tool_names
    assert result["messages"][-1].text == "直接完成。"


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

    assert model.bound_tool_names == [
        "web_search",
        "web_fetch",
        "write_todos",
        "ask_clarification",
        "inspect_execution_environment",
        "activate_skill",
        "task",
    ]
    assert called_queries == [("Mini Deer 最新消息", 3)]
    assert len(result["messages"]) == 4
    assert isinstance(result["messages"][2], ToolMessage)
    assert result["messages"][2].name == "web_search"
    assert result["messages"][2].tool_call_id == "call-search-1"
    assert "https://example.com/mini-deer" in result["messages"][2].text
    assert result["messages"][3].text.endswith(
        "https://example.com/mini-deer"
    )


def test_compiled_graph_defers_injected_mcp_tool_until_discovery() -> None:
    """16.1 基础请求只公开 MCP 摘要，不能绑定或执行完整 Schema。"""
    calls: list[tuple[int, int]] = []

    def add_numbers(left: int, right: int) -> int:
        calls.append((left, right))
        return left + right

    mcp_tool = StructuredTool.from_function(
        add_numbers,
        name="learning_add_numbers",
        description="通过学习 MCP Server 把两个整数相加",
    )
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "learning_add_numbers",
                        "args": {"left": 19, "right": 23},
                        "id": "call-mcp-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="该 MCP 工具尚未提升，因此没有执行计算。"),
        ]
    )

    result = build_agent_graph(model, mcp_tools=(mcp_tool,)).invoke(
        {"messages": [HumanMessage(content="请通过 MCP 计算 19+23。")]}
    )

    assert "learning_add_numbers" not in model.bound_tool_names
    assert calls == []
    blocked = result["messages"][-2]
    assert isinstance(blocked, ToolMessage)
    assert blocked.status == "error"
    assert result["messages"][-1].text == "该 MCP 工具尚未提升，因此没有执行计算。"


def test_mcp_exception_returns_tool_error_and_model_can_choose_alternative() -> None:
    """外部工具普通异常不能终止图，下一轮模型仍可解释并收尾。"""

    calls: list[str] = []

    def unavailable_service() -> str:
        calls.append("invoked")
        raise RuntimeError("invalid API key secret-value")

    mcp_tool = StructuredTool.from_function(
        unavailable_service,
        name="private_lookup",
        description="查询需要认证的外部服务",
    )
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "tool_search",
                        "args": {"query": "private_lookup"},
                        "id": "call-search-private",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "private_lookup",
                        "args": {},
                        "id": "call-mcp-error",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="外部查询不可用；我会基于已有信息给出可完成部分。"),
        ]
    )

    result = build_agent_graph(model, mcp_tools=(mcp_tool,)).invoke(
        {"messages": [HumanMessage(content="查询外部资料，失败时说明替代方案。")]}
    )

    tool_message = result["messages"][-2]
    assert calls == ["invoked"]
    assert isinstance(tool_message, ToolMessage)
    assert tool_message.status == "error"
    assert tool_result_meta(tool_message).status == "terminal_error"
    assert "secret-value" not in tool_message.text
    assert result["messages"][-1].text.startswith("外部查询不可用")


def test_repeated_identical_tool_calls_warn_then_force_final_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """硬阈值调用不再执行，收尾响应移除新工具并携带稳定停止原因。"""
    calls: list[str] = []

    def repeatable_lookup(query: str, max_results: int = 5) -> str:
        del max_results
        calls.append(query)
        return json.dumps({"query": query, "results": []})
    monkeypatch.setattr(web_search, "func", repeatable_lookup)

    def repeated(call_id: str) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "web_search",
                    "args": {"query": "same"},
                    "id": call_id,
                    "type": "tool_call",
                }
            ],
        )

    model = ToolAwareFakeModel(
        responses=[
            repeated("call-loop-1"),
            repeated("call-loop-2"),
            repeated("call-loop-3"),
            AIMessage(content="已有搜索均为空，因此无法确认目标存在。"),
        ]
    )

    result = build_agent_graph(
        model,
        loop_soft_limit=2,
        loop_hard_limit=3,
    ).invoke({"messages": [HumanMessage(content="查找目标，空结果时收尾。")]})

    assert calls == ["same", "same"]
    assert any(
        message.additional_kwargs.get("kind") == "loop_warning"
        for message in model.received_histories[2]
    )
    final = result["messages"][-1]
    assert isinstance(final, AIMessage)
    assert final.text == "已有搜索均为空，因此无法确认目标存在。"
    assert final.tool_calls == []
    assert final.additional_kwargs["mini_deer_stop_reason"] == "loop_capped"


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


def test_compiled_graph_delegates_with_isolated_context_and_synthesizes_result() -> None:
    """主 Agent 应把自包含任务交给独立子图，再读取结构化结果完成回答。"""
    delegated_prompt = "比较方案 A 和方案 B，只返回各自优缺点。"
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "description": "比较两个方案",
                            "prompt": delegated_prompt,
                            "subagent_type": "research",
                        },
                        "id": "call-task-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="方案 A 更简单，方案 B 扩展性更好。"),
            AIMessage(content="综合来看，当前阶段优先选择方案 A。"),
        ]
    )

    result = build_agent_graph(model).invoke(
        {"messages": [HumanMessage(content="请比较方案 A 和方案 B，并给出建议。")]}
    )

    assert model.bound_tool_name_histories == [
        [
            "web_search",
            "web_fetch",
            "write_todos",
            "ask_clarification",
            "inspect_execution_environment",
            "activate_skill",
            "task",
        ],
        ["web_search", "web_fetch"],
        [
            "web_search",
            "web_fetch",
            "write_todos",
            "ask_clarification",
            "inspect_execution_environment",
            "activate_skill",
            "task",
        ],
    ]
    assert len(model.received_histories) == 3
    assert [type(message).__name__ for message in model.received_histories[1]] == [
        "SystemMessage",
        "HumanMessage",
    ]
    assert model.received_histories[1][1].text == delegated_prompt
    assert "请比较方案 A 和方案 B" not in model.received_histories[1][1].text

    task_result = next(
        message
        for message in result["messages"]
        if isinstance(message, ToolMessage) and message.name == "task"
    )
    payload = json.loads(task_result.text)
    assert {
        key: payload[key]
        for key in (
            "version",
            "kind",
            "status",
            "subagent_type",
            "description",
            "result",
        )
    } == {
        "version": 1,
        "kind": "subagent_result",
        "status": "completed",
        "subagent_type": "research",
        "description": "比较两个方案",
        "result": "方案 A 更简单，方案 B 扩展性更好。",
    }
    assert payload["duration_ms"] >= 0
    assert payload["usage"]["model_calls"] == 1
    assert result["messages"][-1].text == "综合来看，当前阶段优先选择方案 A。"


def test_delegation_skips_coemitted_tools_and_settles_every_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一响应出现 task 时只执行首个委派，其他工具必须跳过并补齐结果。"""
    search_queries: list[str] = []

    def unexpected_search(query: str, max_results: int = 5) -> str:
        search_queries.append(query)
        return "不应执行"

    monkeypatch.setattr(web_search, "func", unexpected_search)
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": "不应搜索"},
                        "id": "call-skipped-by-task",
                        "type": "tool_call",
                    },
                    {
                        "name": "task",
                        "args": {
                            "description": "独立分析",
                            "prompt": "独立分析这个问题。",
                            "subagent_type": "research",
                        },
                        "id": "call-priority-task",
                        "type": "tool_call",
                    },
                ],
            ),
            AIMessage(content="子 Agent 结果。"),
            AIMessage(content="主 Agent 已核验结果。"),
        ]
    )

    result = build_agent_graph(model).invoke(
        {"messages": [HumanMessage(content="分析并搜索这个问题。")]}
    )

    assert search_queries == []
    tool_results = [
        message for message in result["messages"] if isinstance(message, ToolMessage)
    ]
    assert [message.tool_call_id for message in tool_results] == [
        "call-skipped-by-task",
        "call-priority-task",
    ]
    assert tool_results[0].status == "error"
    assert json.loads(tool_results[0].text)["reason"] == (
        "delegation_batch_exclusive"
    )
    assert json.loads(tool_results[1].text)["status"] == "completed"


def test_async_delegation_runs_three_tasks_concurrently_and_preserves_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """三个独立 task 必须重叠执行，但 ToolMessage 仍按模型调用顺序返回。"""
    subagent_module = import_module("mini_deer_agent.agents.subagent")

    async def scenario() -> None:
        started: list[str] = []
        completion_order: list[str] = []
        all_started = asyncio.Event()
        delays = {
            "独立完成：任务一": 0.03,
            "独立完成：任务二": 0.015,
            "独立完成：任务三": 0.0,
        }

        async def concurrent_runner(
            model: Any, prompt: str, **options: object
        ) -> str:
            del model
            del options
            started.append(prompt)
            if len(started) == 3:
                all_started.set()
            # 串行实现会在第一个任务永久等待，因此该屏障可以证明任务确实重叠启动。
            await all_started.wait()
            await asyncio.sleep(delays[prompt])
            completion_order.append(prompt)
            return f"{prompt}的结果"

        monkeypatch.setattr(
            subagent_module,
            "async_run_subagent",
            concurrent_runner,
        )
        model = ToolAwareFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        _delegation_task_call("call-parallel-1", "任务一"),
                        _delegation_task_call("call-parallel-2", "任务二"),
                        _delegation_task_call("call-parallel-3", "任务三"),
                    ],
                ),
                AIMessage(content="已综合三个独立结果。"),
            ]
        )

        result = await asyncio.wait_for(
            build_agent_graph(model).ainvoke(
                {"messages": [HumanMessage(content="并发完成三个独立任务。")]}
            ),
            timeout=1,
        )

        assert len(started) == 3
        assert completion_order == [
            "独立完成：任务三",
            "独立完成：任务二",
            "独立完成：任务一",
        ]
        tool_results = [
            message
            for message in result["messages"]
            if isinstance(message, ToolMessage)
        ]
        assert [message.tool_call_id for message in tool_results] == [
            "call-parallel-1",
            "call-parallel-2",
            "call-parallel-3",
        ]
        assert [json.loads(message.text)["result"] for message in tool_results] == [
            "独立完成：任务一的结果",
            "独立完成：任务二的结果",
            "独立完成：任务三的结果",
        ]
        assert result["messages"][-1].text == "已综合三个独立结果。"

    asyncio.run(scenario())


def test_delegation_limits_each_batch_and_settles_mixed_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """一批只执行前三个 task，额外 task 与混入的普通工具都必须明确跳过。"""
    subagent_module = import_module("mini_deer_agent.agents.subagent")
    executed_prompts: list[str] = []

    def run_without_model(model: Any, prompt: str, **options: object) -> str:
        del model
        del options
        executed_prompts.append(prompt)
        return f"{prompt}的结果"

    monkeypatch.setattr(subagent_module, "run_subagent", run_without_model)
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": "不应执行"},
                        "id": "call-mixed-search",
                        "type": "tool_call",
                    },
                    _delegation_task_call("call-batch-1", "批次一"),
                    _delegation_task_call("call-batch-2", "批次二"),
                    _delegation_task_call("call-batch-3", "批次三"),
                    _delegation_task_call("call-batch-4", "批次四"),
                ],
            ),
            AIMessage(content="已使用允许的结果。"),
        ]
    )

    result = build_agent_graph(model).invoke(
        {"messages": [HumanMessage(content="执行一批并发任务。")]}
    )

    assert sorted(executed_prompts) == [
        "独立完成：批次一",
        "独立完成：批次三",
        "独立完成：批次二",
    ]
    tool_results = [
        message for message in result["messages"] if isinstance(message, ToolMessage)
    ]
    assert [message.tool_call_id for message in tool_results] == [
        "call-mixed-search",
        "call-batch-1",
        "call-batch-2",
        "call-batch-3",
        "call-batch-4",
    ]
    assert json.loads(tool_results[0].text)["reason"] == (
        "delegation_batch_exclusive"
    )
    assert json.loads(tool_results[-1].text)["reason"] == (
        "delegation_concurrency_limit"
    )


def test_delegation_enforces_six_task_total_across_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一产品 Run 的后续批次累计到六次后，新的 task 必须失败关闭。"""
    subagent_module = import_module("mini_deer_agent.agents.subagent")
    executed_prompts: list[str] = []

    def run_without_model(model: Any, prompt: str, **options: object) -> str:
        del model
        del options
        executed_prompts.append(prompt)
        return f"{prompt}的结果"

    monkeypatch.setattr(subagent_module, "run_subagent", run_without_model)
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    _delegation_task_call(f"call-total-{index}", f"总量{index}")
                    for index in range(1, 4)
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    _delegation_task_call(f"call-total-{index}", f"总量{index}")
                    for index in range(4, 7)
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    _delegation_task_call("call-total-7", "总量7")
                ],
            ),
            AIMessage(content="已达到委派上限并完成综合。"),
        ]
    )

    result = build_agent_graph(model).invoke(
        {"messages": [HumanMessage(content="分批执行独立任务。")]}
    )

    assert len(executed_prompts) == 6
    rejected = next(
        message
        for message in result["messages"]
        if isinstance(message, ToolMessage)
        and message.tool_call_id == "call-total-7"
    )
    assert rejected.status == "error"
    assert json.loads(rejected.text)["reason"] == "delegation_total_limit"
    assert result["messages"][-1].text == "已达到委派上限并完成综合。"


def test_parallel_delegation_isolates_failure_and_cancels_all_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单个失败不能拖垮兄弟任务，而父 Run 取消必须取消全部仍在运行的子图。"""
    subagent_module = import_module("mini_deer_agent.agents.subagent")

    async def failure_scenario() -> None:
        async def partly_failing_runner(
            model: Any, prompt: str, **options: object
        ) -> str:
            del model
            del options
            if prompt.endswith("失败任务"):
                raise RuntimeError("不应泄露的异常")
            return f"{prompt}的成功结果"

        monkeypatch.setattr(
            subagent_module,
            "async_run_subagent",
            partly_failing_runner,
        )
        model = ToolAwareFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        _delegation_task_call("call-success", "成功任务"),
                        _delegation_task_call("call-failure", "失败任务"),
                    ],
                ),
                AIMessage(content="已使用成功结果并说明失败。"),
            ]
        )
        result = await build_agent_graph(model).ainvoke(
            {"messages": [HumanMessage(content="并发执行，允许部分失败。")]}
        )
        tool_results = [
            message
            for message in result["messages"]
            if isinstance(message, ToolMessage)
        ]
        assert json.loads(tool_results[0].text)["status"] == "completed"
        assert json.loads(tool_results[1].text)["status"] == "failed"
        assert "不应泄露的异常" not in tool_results[1].text

    async def cancellation_scenario() -> None:
        started = asyncio.Event()
        started_count = 0
        cancelled_prompts: list[str] = []

        async def cancellable_runner(
            model: Any, prompt: str, **options: object
        ) -> str:
            nonlocal started_count
            del model
            del options
            started_count += 1
            if started_count == 3:
                started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled_prompts.append(prompt)
                raise

        monkeypatch.setattr(
            subagent_module,
            "async_run_subagent",
            cancellable_runner,
        )
        model = ToolAwareFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        _delegation_task_call(f"call-cancel-{index}", f"取消{index}")
                        for index in range(1, 4)
                    ],
                )
            ]
        )
        checkpointer = InMemorySaver()
        graph = build_agent_graph(model, checkpointer=checkpointer)
        config = {
            "configurable": {"thread_id": "cancelled-delegation-lifecycle"}
        }
        graph_task = asyncio.create_task(
            graph.ainvoke(
                {
                    "messages": [
                        HumanMessage(
                            content="启动后取消全部任务。",
                            id="turn-cancelled-delegation",
                        )
                    ]
                },
                config,
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        graph_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await graph_task

        assert sorted(cancelled_prompts) == [
            "独立完成：取消1",
            "独立完成：取消2",
            "独立完成：取消3",
        ]
        snapshot = graph.get_state(config).values
        assert [entry["status"] for entry in snapshot["delegations"]] == [
            "running",
            "running",
            "running",
        ]

    asyncio.run(failure_scenario())
    asyncio.run(cancellation_scenario())


def test_clarification_ends_current_graph_without_second_model_call() -> None:
    """澄清结果写入历史后必须直接结束，不能把问题结果再次交给模型。"""
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "ask_clarification",
                        "args": {
                            "question": "报告的主题和用途是什么？",
                            "clarification_type": "missing_info",
                        },
                        "id": "call-clarification-stop",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    )

    result = build_agent_graph(model).invoke(
        {"messages": [HumanMessage(content="帮我生成一份报告。")]}
    )

    assert len(model.received_histories) == 1
    assert [type(message).__name__ for message in result["messages"]] == [
        "HumanMessage",
        "AIMessage",
        "ToolMessage",
    ]
    tool_result = result["messages"][-1]
    assert isinstance(tool_result, ToolMessage)
    assert tool_result.name == "ask_clarification"
    assert json.loads(tool_result.text)["question"] == "报告的主题和用途是什么？"


def test_clarification_skips_coemitted_tools_and_settles_every_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一响应一旦要求澄清，其他工具不能执行且每个调用都要有结果。"""
    search_queries: list[str] = []

    def unexpected_search(query: str, max_results: int = 5) -> str:
        search_queries.append(query)
        return "不应执行"

    monkeypatch.setattr(web_search, "func", unexpected_search)
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": "不应搜索"},
                        "id": "call-skipped-search",
                        "type": "tool_call",
                    },
                    {
                        "name": "ask_clarification",
                        "args": {
                            "question": "请先确认报告主题？",
                            "clarification_type": "missing_info",
                        },
                        "id": "call-priority-clarification",
                        "type": "tool_call",
                    },
                ],
            )
        ]
    )

    result = build_agent_graph(model).invoke(
        {"messages": [HumanMessage(content="生成报告并搜索资料。")]}
    )

    assert search_queries == []
    assert len(model.received_histories) == 1
    tool_results = [
        message for message in result["messages"] if isinstance(message, ToolMessage)
    ]
    assert [message.tool_call_id for message in tool_results] == [
        "call-skipped-search",
        "call-priority-clarification",
    ]
    assert tool_results[0].status == "error"
    assert json.loads(tool_results[0].text)["reason"] == "clarification_requested"
    assert tool_results[1].status == "success"


def test_same_thread_continues_after_user_answers_clarification() -> None:
    """下一 Run 只提交回答时，checkpoint 仍应提供原请求和澄清问题。"""
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "ask_clarification",
                        "args": {
                            "question": "报告的主题是什么？",
                            "clarification_type": "missing_info",
                        },
                        "id": "call-clarification-resume",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="我会继续生成 Agent 架构报告。"),
        ]
    )
    graph = build_agent_graph(model, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "thread-clarification"}}

    graph.invoke(
        {"messages": [HumanMessage(content="帮我生成一份报告。")]},
        config,
    )
    result = graph.invoke(
        {"messages": [HumanMessage(content="主题是 Agent 架构。")]},
        config,
    )

    assert len(model.received_histories) == 2
    assert [message.text for message in model.received_histories[1][1:]] == [
        "帮我生成一份报告。",
        "",
        result["messages"][2].text,
        "主题是 Agent 架构。",
    ]
    assert result["messages"][-1].text == "我会继续生成 Agent 架构报告。"


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


def test_large_tool_result_is_externalized_and_read_through_virtual_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实 ToolNode 回环只把摘要交给模型，并允许当前 Run 分段续读。"""
    run_id = str(uuid4())
    store = RunOutputStore(tmp_path / "run-outputs")
    policy = ToolOutputBudgetPolicy(
        max_inline_chars=1_024,
        sample_chars=100,
        read_chunk_chars=400,
    )
    large_content = json.dumps(
        {
            "records": ["x" * 100 for _ in range(40)],
            "last_error": "target-error-marker",
        }
    )
    output_path = store.virtual_path(
        tool_name="web_search",
        tool_call_id="call-large-output",
        output_format="json",
    )

    def large_search(query: str, max_results: int = 5) -> str:
        del query, max_results
        return large_content
    monkeypatch.setattr(web_search, "func", large_search)
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": "large result"},
                        "id": "call-large-output",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {
                            "path": output_path,
                            "start_line": 1,
                            "limit": 2,
                        },
                        "id": "call-read-output",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="已定位 target-error-marker。"),
        ]
    )

    result = build_agent_graph(
        model,
        tool_output_store=store,
        tool_output_policy=policy,
    ).invoke(
        {"messages": [HumanMessage(content="定位大型结果中的最后一个错误。")]},
        {"configurable": {"run_id": run_id}},
    )

    tool_messages = [
        message for message in result["messages"] if isinstance(message, ToolMessage)
    ]
    assert [message.name for message in tool_messages] == [
        "web_search",
        "read_file",
    ]
    reference = json.loads(tool_messages[0].text)
    read_result = json.loads(tool_messages[1].text)
    assert reference["path"] == output_path
    assert reference["stored"] is True
    assert read_result["path"] == output_path
    assert read_result["virtual_chunks"] is True
    assert len(tool_messages[0].text) <= policy.max_inline_chars
    assert all(
        large_content not in message.text
        for history in model.received_histories
        for message in history
    )
    assert result["messages"][-1].text == "已定位 target-error-marker。"
