"""验证单次同步子 Agent 委派的契约、隔离边界和执行上限。"""

import asyncio
import json
from collections.abc import Sequence
from importlib import import_module
from typing import Any, Self

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import Field

from mini_deer_agent.tools.task import (
    MAX_CONCURRENT_DELEGATIONS,
    MAX_TOTAL_DELEGATIONS_PER_RUN,
    create_task_tool,
)


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


def _task_call(call_id: str, *, prompt: str = "独立分析输入。") -> dict[str, Any]:
    """生成带稳定 ID 的 task 工具调用。"""
    return {
        "name": "task",
        "args": {
            "description": "独立分析",
            "prompt": prompt,
            "subagent_type": "general-purpose",
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
    result = task_tool.invoke(_task_call("call-task-contract"))
    payload = json.loads(result.text)

    assert payload["status"] == "completed"
    assert payload["result"] == "独立分析结果。"
    assert model.bound_tool_name_histories == [["web_search", "web_fetch"]]
    assert [type(message).__name__ for message in model.received_histories[0]] == [
        "SystemMessage",
        "HumanMessage",
    ]
    assert isinstance(model.received_histories[0][0], SystemMessage)
    assert isinstance(model.received_histories[0][1], HumanMessage)
    assert model.received_histories[0][1].text == "独立分析输入。"


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


def test_task_returns_sanitized_failure_without_exception_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """子图失败应进入稳定 ToolMessage，不能泄露底层异常正文。"""
    subagent_module = import_module("mini_deer_agent.agents.subagent")

    def fail_subagent(model: Any, prompt: str) -> str:
        del model, prompt
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

        async def wait_forever(model: Any, prompt: str) -> str:
            del model, prompt
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
