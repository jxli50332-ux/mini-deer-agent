"""验证单次同步子 Agent 委派的契约、隔离边界和执行上限。"""

import asyncio
import json
from collections.abc import Sequence
from importlib import import_module
from pathlib import Path
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
from langchain_core.tools import StructuredTool
from pydantic import Field

from mini_deer_agent.tools.task import (
    MAX_CONCURRENT_DELEGATIONS,
    MAX_TOTAL_DELEGATIONS_PER_RUN,
    create_task_tool,
)
from mini_deer_agent.agents.subagent import (
    DEFAULT_SUBAGENT_REGISTRY,
    INHERIT_MODEL,
    PROJECT_READER_SUBAGENT,
    RESEARCH_SUBAGENT,
    TEST_RUNNER_SUBAGENT,
    SubagentConfig,
    SubagentRegistry,
    run_subagent,
)
from mini_deer_agent.deferred_tools import DeferredToolCatalog
from mini_deer_agent.skills import BuiltInSkill, BuiltInSkillCatalog


class RecordingFakeModel(FakeMessagesListChatModel):
    """记录子图工具绑定和模型输入，不访问真实模型服务。"""

    bound_tool_name_histories: list[list[str]] = Field(default_factory=list)
    received_histories: list[list[BaseMessage]] = Field(default_factory=list)

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Self:
        """保存每次绑定的工具名称，供测试验证能力隔离。"""
        self.bound_tool_name_histories.append([tool.name for tool in tools])
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        """保存模型输入后返回预设消息。"""
        self.received_histories.append(list(messages))
        return super()._generate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


def _task_call(
    call_id: str,
    *,
    prompt: str = "独立分析输入。",
    subagent_type: str = "research",
) -> dict[str, Any]:
    """生成带稳定 ID 的 task 工具调用。"""
    return {
        "name": "task",
        "args": {
            "description": "独立分析",
            "prompt": prompt,
            "subagent_type": subagent_type,
        },
        "id": call_id,
        "type": "tool_call",
    }


def test_task_contract_and_child_context_are_isolated() -> None:
    """task 参数必须明确，子图只能收到自己的系统提示和委派内容。"""
    model = RecordingFakeModel(responses=[AIMessage(content="独立分析结果。")])
    task_tool = create_task_tool(model)

    assert task_tool.name == "task"
    assert task_tool.tool_call_schema.model_json_schema()["required"] == [
        "description",
        "prompt",
        "subagent_type",
    ]
    assert "active_skill_name" not in (
        task_tool.tool_call_schema.model_json_schema()["properties"]
    )
    result = task_tool.invoke(_task_call("call-task-contract"))
    payload = json.loads(result.text)

    assert payload["status"] == "completed"
    assert payload["subagent_type"] == "research"
    assert payload["result"] == "独立分析结果。"
    assert model.bound_tool_name_histories == [["web_search", "web_fetch"]]
    assert [type(message).__name__ for message in model.received_histories[0]] == [
        "SystemMessage",
        "HumanMessage",
    ]
    assert isinstance(model.received_histories[0][0], SystemMessage)
    assert isinstance(model.received_histories[0][1], HumanMessage)
    assert model.received_histories[0][1].text == "独立分析输入。"


def test_default_registry_contains_named_specialists_without_generic_fallback() -> None:
    """配置必须完整、不可变且不保留隐式通用角色。"""
    assert DEFAULT_SUBAGENT_REGISTRY.names == (
        "project-reader",
        "research",
        "test-runner",
    )
    assert RESEARCH_SUBAGENT.model == INHERIT_MODEL
    assert RESEARCH_SUBAGENT.tools == (
        "web_search",
        "web_fetch",
        "read_file",
        "tool_search",
        "mcp:*",
    )
    assert PROJECT_READER_SUBAGENT.tools == (
        "list_files",
        "glob_files",
        "search_files",
        "read_file",
    )
    assert PROJECT_READER_SUBAGENT.max_turns == 15
    assert PROJECT_READER_SUBAGENT.timeout_seconds == 120
    assert "task" in PROJECT_READER_SUBAGENT.disallowed_tools
    assert PROJECT_READER_SUBAGENT.skills == ()
    assert TEST_RUNNER_SUBAGENT.tools == (
        "inspect_execution_environment",
        "inspect_project_sandbox",
        "run_project_command",
    )
    assert "write_file" in TEST_RUNNER_SUBAGENT.disallowed_tools
    assert "run_project_command" not in TEST_RUNNER_SUBAGENT.disallowed_tools


def test_registry_rejects_duplicate_names_and_conflicting_tools() -> None:
    """服务端配置错误应在启动边界暴露，不能在运行时静默覆盖。"""
    with pytest.raises(ValueError, match="duplicate subagent name"):
        SubagentRegistry((RESEARCH_SUBAGENT, RESEARCH_SUBAGENT))
    with pytest.raises(ValueError, match="overlap"):
        SubagentConfig(
            name="broken",
            description="错误配置",
            system_prompt="只用于测试。",
            model=INHERIT_MODEL,
            tools=("read_file",),
            disallowed_tools=("read_file",),
            skills=(),
            max_turns=1,
            timeout_seconds=1,
        )


def test_task_explicitly_selects_two_roles_and_rejects_unknown_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一 task 契约可选择两个角色，未知角色返回稳定错误且不消耗名额。"""
    subagent_module = import_module("mini_deer_agent.agents.subagent")
    selected: list[str] = []

    def record_role(
        model: Any,
        prompt: str,
        **options: object,
    ) -> str:
        del model, prompt
        config = options["config"]
        assert isinstance(config, SubagentConfig)
        selected.append(config.name)
        return f"{config.name} result"

    monkeypatch.setattr(subagent_module, "run_subagent", record_role)
    task_tool = create_task_tool(
        RecordingFakeModel(responses=[AIMessage(content="不会使用")])
    )

    research = task_tool.invoke(
        _task_call("call-research", subagent_type="research")
    )
    reader = task_tool.invoke(
        _task_call("call-reader", subagent_type="project-reader")
    )
    unknown = task_tool.invoke(
        _task_call("call-unknown", subagent_type="writer")
    )

    assert selected == ["research", "project-reader"]
    assert json.loads(research.text)["result"] == "research result"
    assert json.loads(reader.text)["result"] == "project-reader result"
    unknown_payload = json.loads(unknown.text)
    assert unknown.status == "error"
    assert unknown_payload == {
        "version": 1,
        "kind": "subagent_result",
        "status": "failed",
        "subagent_type": "writer",
        "description": "独立分析",
        "error_code": "unknown_subagent_type",
        "message": (
            "未知子 Agent 类型；可用类型："
            "project-reader、research、test-runner。"
        ),
    }


def _test_tool(name: str) -> StructuredTool:
    """创建只用于核对权限名称的无参数工具。"""

    def invoke() -> str:
        return name

    return StructuredTool.from_function(
        func=invoke,
        name=name,
        description=f"测试工具 {name}",
    )


def test_task_intersects_parent_role_and_active_skill_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """子图工具必须同时属于父 Run、角色白名单和活动 Skill 白名单。"""
    subagent_module = import_module("mini_deer_agent.agents.subagent")
    selected_histories: list[list[str]] = []

    def capture_tools(
        model: Any,
        prompt: str,
        **options: object,
    ) -> str:
        del model, prompt
        tools = options["available_tools"]
        assert isinstance(tools, tuple)
        selected_histories.append([tool.name for tool in tools])
        return "完成"

    monkeypatch.setattr(subagent_module, "run_subagent", capture_tools)
    catalog = BuiltInSkillCatalog(
        skills=(
            BuiltInSkill(
                name="reader-skill",
                description="只允许读取。",
                instructions="读取后返回证据。",
                source_file=Path("reader-skill/SKILL.md"),
                allowed_tools=("read_file", "write_file"),
            ),
        )
    )
    task_tool = create_task_tool(
        RecordingFakeModel(responses=[AIMessage(content="不会使用")]),
        parent_tools=(
            _test_tool("web_search"),
            _test_tool("read_file"),
            _test_tool("write_file"),
            _test_tool("get_weather"),
        ),
        skill_catalog=catalog,
    )
    reader_call = _task_call(
        "call-reader-policy",
        subagent_type="project-reader",
    )
    reader_call["args"]["active_skill_name"] = "reader-skill"

    task_tool.invoke(reader_call)
    task_tool.invoke(
        _task_call("call-research-policy", subagent_type="research")
    )

    assert selected_histories == [["read_file"], ["web_search", "read_file"]]


def test_subagent_execution_registry_cannot_run_disallowed_parent_tool() -> None:
    """即使模型伪造未绑定调用，子图执行节点也不能调用父级写工具。"""
    write_calls: list[str] = []

    def read_file(path: str) -> str:
        return f"read:{path}"

    def write_file(path: str, content: str) -> str:
        write_calls.append(f"{path}:{content}")
        return "written"

    read_tool = StructuredTool.from_function(
        func=read_file,
        name="read_file",
        description="读取测试文件",
    )
    write_tool = StructuredTool.from_function(
        func=write_file,
        name="write_file",
        description="写入测试文件",
    )
    model = RecordingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {"path": "x.py", "content": "bad"},
                        "id": "call-forbidden-write",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="没有执行写入。"),
        ]
    )
    task_tool = create_task_tool(
        model,
        parent_tools=(read_tool, write_tool),
    )

    result = task_tool.invoke(
        _task_call(
            "call-reader-bypass",
            subagent_type="project-reader",
        )
    )

    assert json.loads(result.text)["result"] == "没有执行写入。"
    assert model.bound_tool_name_histories == [["read_file"], ["read_file"]]
    assert write_calls == []
    forbidden_result = next(
        message
        for message in model.received_histories[-1]
        if isinstance(message, ToolMessage)
    )
    assert forbidden_result.status == "error"
    assert forbidden_result.name == "write_file"
    assert json.loads(forbidden_result.text)["kind"] == "tool_call_blocked"


def test_research_subagent_reuses_deferred_discovery_and_role_guard() -> None:
    """research 可发现并调用 MCP；project-reader 即使伪造调用也不能越权。"""
    calls: list[str] = []

    def literature_lookup(topic: str) -> str:
        calls.append(topic)
        return "paper:42"

    deferred = StructuredTool.from_function(
        literature_lookup,
        name="literature_lookup",
        description="按主题查询外部论文目录",
    )
    catalog = DeferredToolCatalog((deferred,))
    research_model = RecordingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "tool_search",
                        "args": {"query": "literature_lookup"},
                        "id": "child-search",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "literature_lookup",
                        "args": {"topic": "agents"},
                        "id": "child-lookup",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="找到 paper:42。"),
        ]
    )

    result = run_subagent(
        research_model,
        "查询 agents 论文。",
        config=RESEARCH_SUBAGENT,
        deferred_tool_catalog=catalog,
    )

    assert result.content == "找到 paper:42。"
    assert "literature_lookup" not in research_model.bound_tool_name_histories[0]
    assert "tool_search" in research_model.bound_tool_name_histories[0]
    assert "literature_lookup" in research_model.bound_tool_name_histories[1]
    assert calls == ["agents"]

    reader_model = RecordingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "literature_lookup",
                        "args": {"topic": "forbidden"},
                        "id": "reader-forged-lookup",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="未执行越权调用。"),
        ]
    )
    reader_result = run_subagent(
        reader_model,
        "尝试外部查询。",
        config=PROJECT_READER_SUBAGENT,
        available_tools=(_test_tool("read_file"),),
        deferred_tool_catalog=catalog,
    )

    assert reader_result.content == "未执行越权调用。"
    assert all(
        "literature_lookup" not in names and "tool_search" not in names
        for names in reader_model.bound_tool_name_histories
    )
    assert calls == ["agents"]


def test_task_enforces_total_execution_limit_per_compiled_graph() -> None:
    """同一主图最多启动六次子图，超额调用返回稳定错误。"""
    model = RecordingFakeModel(responses=[AIMessage(content="委派结果。")])
    task_tool = create_task_tool(model)

    accepted = [
        task_tool.invoke(_task_call(f"call-task-{index}"))
        for index in range(MAX_TOTAL_DELEGATIONS_PER_RUN)
    ]
    rejected = task_tool.invoke(_task_call("call-task-overflow"))

    assert MAX_CONCURRENT_DELEGATIONS == 3
    assert all(json.loads(result.text)["status"] == "completed" for result in accepted)
    rejected_payload = json.loads(rejected.text)
    assert rejected.status == "error"
    assert rejected_payload["status"] == "failed"
    assert rejected_payload["error_code"] == "delegation_limit_reached"
    assert len(model.received_histories) == MAX_TOTAL_DELEGATIONS_PER_RUN


def test_task_supports_async_execution_without_sync_fallback() -> None:
    """异步 Web Run 应直接等待子图 ainvoke，并返回同一稳定协议。"""
    model = RecordingFakeModel(responses=[AIMessage(content="异步结果。")])
    task_tool = create_task_tool(model)

    result = asyncio.run(task_tool.ainvoke(_task_call("call-task-async")))

    payload = json.loads(result.text)
    assert payload["status"] == "completed"
    assert payload["result"] == "异步结果。"
    assert payload["duration_ms"] >= 0
    assert payload["started_at"].endswith("Z")
    assert payload["finished_at"].endswith("Z")
    assert payload["usage"] == {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "model_calls": 1,
    }


def test_task_timeout_returns_partial_result_and_local_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超时必须取消子图，并保留最后正文、停止原因和独立用量。"""
    subagent_module = import_module("mini_deer_agent.agents.subagent")

    async def scenario() -> None:
        child_cancelled = asyncio.Event()

        async def never_finishes(
            model: Any,
            prompt: str,
            **options: object,
        ) -> str:
            del model, prompt
            progress = options["execution_progress"]
            progress.observe(AIMessage(content="超时前已经找到的证据"))
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                child_cancelled.set()
                raise

        monkeypatch.setattr(
            subagent_module,
            "async_run_subagent",
            never_finishes,
        )
        timeout_config = SubagentConfig(
            name="timeout-test",
            description="测试超时",
            system_prompt="只用于测试。",
            model=INHERIT_MODEL,
            tools=(),
            disallowed_tools=(),
            skills=(),
            max_turns=1,
            timeout_seconds=1,
        )
        task_tool = create_task_tool(
            RecordingFakeModel(responses=[AIMessage(content="不会使用")]),
            registry=SubagentRegistry((timeout_config,)),
        )

        result = await task_tool.ainvoke(
            _task_call(
                "call-task-timeout",
                subagent_type="timeout-test",
            )
        )
        payload = json.loads(result.text)

        assert child_cancelled.is_set()
        assert result.status == "error"
        assert payload["status"] == "timed_out"
        assert payload["error_code"] == "subagent_timed_out"
        assert payload["stop_reason"] == "timeout"
        assert payload["last_result"] == "超时前已经找到的证据"
        assert 900 <= payload["duration_ms"] < 2_000
        assert payload["usage"]["model_calls"] == 0

    asyncio.run(scenario())


def test_task_returns_sanitized_failure_without_exception_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """子图失败应进入稳定 ToolMessage，不能泄露底层异常正文。"""
    subagent_module = import_module("mini_deer_agent.agents.subagent")

    def fail_subagent(model: Any, prompt: str, **options: object) -> str:
        del model, prompt, options
        raise RuntimeError("secret-provider-detail")

    monkeypatch.setattr(subagent_module, "run_subagent", fail_subagent)
    task_tool = create_task_tool(
        RecordingFakeModel(responses=[AIMessage(content="不会使用")])
    )

    result = task_tool.invoke(_task_call("call-task-failed"))
    payload = json.loads(result.text)

    assert result.status == "error"
    assert payload["error_code"] == "subagent_execution_failed"
    assert "secret-provider-detail" not in result.text


def test_task_async_cancellation_propagates_to_subagent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """取消 task 的异步等待时，CancelledError 必须继续传播而非伪装成失败。"""
    subagent_module = import_module("mini_deer_agent.agents.subagent")

    async def scenario() -> None:
        started = asyncio.Event()

        async def wait_forever(
            model: Any,
            prompt: str,
            **options: object,
        ) -> str:
            del model, prompt, options
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        monkeypatch.setattr(subagent_module, "async_run_subagent", wait_forever)
        task_tool = create_task_tool(
            RecordingFakeModel(responses=[AIMessage(content="不会使用")])
        )
        task = asyncio.create_task(
            task_tool.ainvoke(_task_call("call-task-cancelled"))
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
