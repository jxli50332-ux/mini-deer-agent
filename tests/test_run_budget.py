"""验证 14.6 主/子 Agent 共享预算、正式终态和持久化。"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Self, cast

from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from pydantic import Field

from mini_deer_agent.agents import build_agent_graph
from mini_deer_agent.agents.middleware import (
    LOOP_STOP_REASON_KEY,
    RUN_USAGE_KEY,
    RunBudgetPolicy,
    RunBudgetTracker,
)
from mini_deer_agent.agents.subagent import run_subagent
from mini_deer_agent.persistence import open_sqlite_conversation_repository
from mini_deer_agent.streaming import RunEvent
from mini_deer_agent.streaming.projector import project_run_events


class _ToolAwareModel(FakeMessagesListChatModel):
    """让固定响应模型支持子图工具绑定并记录实际调用次数。"""

    calls: int = 0
    histories: list[list[BaseMessage]] = Field(default_factory=list)

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Self:
        del tools, tool_choice, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        self.calls += 1
        self.histories.append(list(messages))
        return super()._generate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


def _usage_message(
    content: str,
    *,
    input_tokens: int,
    output_tokens: int,
    tool_calls: list[dict[str, Any]] | None = None,
) -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=tool_calls or [],
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )


def test_tracker_aggregates_usage_and_emits_soft_warning_once() -> None:
    tracker = RunBudgetTracker(
        RunBudgetPolicy(
            soft_token_limit=10,
            hard_token_limit=20,
            soft_turn_limit=2,
            hard_turn_limit=4,
        )
    )
    tracker.begin_run("run-1")
    assert tracker.reserve_model_call() is None
    assert tracker.record_response(
        _usage_message("阶段结果", input_tokens=7, output_tokens=4)
    ) is None

    first = tracker.append_pending_warning([HumanMessage(content="任务")])
    second = tracker.append_pending_warning(first)

    assert len(first) == 2
    assert first[-1].additional_kwargs["kind"] == "run_budget_warning"
    assert second == first
    assert tracker.snapshot().total_tokens == 11
    assert tracker.snapshot().model_calls == 1


def test_token_cap_removes_tools_and_preserves_partial_text() -> None:
    tracker = RunBudgetTracker(
        RunBudgetPolicy(
            soft_token_limit=5,
            hard_token_limit=10,
            soft_turn_limit=2,
            hard_turn_limit=4,
        )
    )
    tracker.begin_run("run-1")
    assert tracker.reserve_model_call() is None
    response = _usage_message(
        "已得到的部分结论",
        input_tokens=6,
        output_tokens=4,
        tool_calls=[
            {
                "name": "web_search",
                "args": {"query": "不应继续"},
                "id": "call-blocked",
                "type": "tool_call",
            }
        ],
    )

    assert tracker.record_response(response) == "token_capped"
    capped = tracker.capped_response("token_capped", response)

    assert capped.text == "已得到的部分结论"
    assert capped.tool_calls == []
    assert capped.additional_kwargs[LOOP_STOP_REASON_KEY] == "token_capped"


def test_turn_cap_is_checked_before_extra_model_request() -> None:
    tracker = RunBudgetTracker(
        RunBudgetPolicy(
            soft_token_limit=100,
            hard_token_limit=200,
            soft_turn_limit=1,
            hard_turn_limit=2,
        )
    )
    tracker.begin_run("run-1")
    assert tracker.reserve_model_call() is None
    tracker.record_response(_usage_message("一", input_tokens=1, output_tokens=1))
    assert tracker.reserve_model_call() is None
    tracker.record_response(_usage_message("二", input_tokens=1, output_tokens=1))

    assert tracker.reserve_model_call() == "turn_capped"
    assert tracker.snapshot().model_calls == 2


def test_subagent_uses_parent_budget_and_returns_stop_reason() -> None:
    tracker = RunBudgetTracker(
        RunBudgetPolicy(
            soft_token_limit=5,
            hard_token_limit=10,
            soft_turn_limit=3,
            hard_turn_limit=5,
        )
    )
    tracker.begin_run("shared-run")
    assert tracker.reserve_model_call() is None
    tracker.record_response(_usage_message("主 Agent 阶段", input_tokens=1, output_tokens=1))
    model = _ToolAwareModel(
        responses=[
            _usage_message("子 Agent 部分结果", input_tokens=5, output_tokens=3)
        ]
    )

    result = run_subagent(model, "独立调研", run_budget_tracker=tracker)

    assert result.content == "子 Agent 部分结果"
    assert result.stop_reason == "token_capped"
    assert tracker.snapshot().total_tokens == 10
    assert tracker.snapshot().model_calls == 2


def test_main_graph_hard_token_cap_skips_requested_tool() -> None:
    model = _ToolAwareModel(
        responses=[
            _usage_message(
                "预算内部分答案",
                input_tokens=7,
                output_tokens=3,
                tool_calls=[
                    {
                        "name": "web_search",
                        "args": {"query": "不应执行"},
                        "id": "call-capped",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    )

    result = build_agent_graph(
        model,
        run_budget_policy=RunBudgetPolicy(
            soft_token_limit=5,
            hard_token_limit=10,
            soft_turn_limit=2,
            hard_turn_limit=4,
        ),
    ).invoke({"messages": [HumanMessage(content="执行测试")]})

    final = result["messages"][-1]
    assert isinstance(final, AIMessage)
    assert final.text == "预算内部分答案"
    assert final.tool_calls == []
    assert final.additional_kwargs[LOOP_STOP_REASON_KEY] == "token_capped"
    assert final.additional_kwargs[RUN_USAGE_KEY]["total_tokens"] == 10
    assert model.calls == 1


def test_task_returns_subagent_partial_result_and_cap_reason_to_main() -> None:
    model = _ToolAwareModel(
        responses=[
            _usage_message(
                "",
                input_tokens=1,
                output_tokens=1,
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "description": "预算内调研",
                            "prompt": "独立完成预算内调研",
                            "subagent_type": "research",
                        },
                        "id": "call-budget-task",
                        "type": "tool_call",
                    }
                ],
            ),
            _usage_message(
                "子 Agent 最后一版可用结果",
                input_tokens=5,
                output_tokens=3,
            ),
        ]
    )

    state = build_agent_graph(
        model,
        run_budget_policy=RunBudgetPolicy(
            soft_token_limit=5,
            hard_token_limit=10,
            soft_turn_limit=3,
            hard_turn_limit=5,
        ),
    ).invoke({"messages": [HumanMessage(content="委派测试")]})

    task_result = next(
        message
        for message in state["messages"]
        if isinstance(message, ToolMessage) and message.name == "task"
    )
    payload = json.loads(task_result.text)
    assert payload["result"] == "子 Agent 最后一版可用结果"
    assert payload["stop_reason"] == "token_capped"
    assert payload["usage"] == {
        "input_tokens": 5,
        "output_tokens": 3,
        "total_tokens": 8,
        "model_calls": 1,
    }
    final = state["messages"][-1]
    assert isinstance(final, AIMessage)
    assert "子 Agent 最后一版可用结果" in final.text
    assert final.additional_kwargs[LOOP_STOP_REASON_KEY] == "token_capped"
    assert model.calls == 2


def test_child_budget_scopes_report_independent_usage_and_share_parent_cap() -> None:
    """兄弟子任务分别计量，但两者之和必须进入同一个父 Run。"""
    parent = RunBudgetTracker()
    parent.begin_run("shared-parent")
    first = parent.child_scope()
    second = parent.child_scope()

    assert first.reserve_model_call() is None
    first.record_response(
        _usage_message("一", input_tokens=2, output_tokens=3)
    )
    assert second.reserve_model_call() is None
    second.record_response(
        _usage_message("二", input_tokens=5, output_tokens=7)
    )

    assert first.snapshot().total_tokens == 5
    assert second.snapshot().total_tokens == 12
    assert parent.snapshot().total_tokens == 17
    assert parent.snapshot().model_calls == 2


def test_projector_and_repository_preserve_budget_terminal_facts(
    tmp_path: Path,
) -> None:
    thread_id = "11111111-1111-4111-8111-111111111111"
    run_id = "22222222-2222-4222-8222-222222222222"
    message_id = "33333333-3333-4333-8333-333333333333"
    chunks = [
        (
            AIMessageChunk(
                content="部分回答",
                id="provider-answer",
                additional_kwargs={
                    LOOP_STOP_REASON_KEY: "turn_capped",
                    RUN_USAGE_KEY: {
                        "input_tokens": 80,
                        "output_tokens": 20,
                        "total_tokens": 100,
                        "model_calls": 4,
                    },
                },
            ),
            {"langgraph_node": "model"},
        )
    ]
    projected = list(
        project_run_events(chunks, run_id=run_id, thread_id=thread_id)
    )
    assert projected[-1].payload == {
        "finish_reason": "turn_capped",
        "input_tokens": 80,
        "output_tokens": 20,
        "total_tokens": 100,
        "model_calls": 4,
    }

    database = tmp_path / "run-budget.sqlite"
    with open_sqlite_conversation_repository(database) as repository:
        repository.create_run(
            thread_id=thread_id,
            run_id=run_id,
            user_message_id=message_id,
            user_message="测试预算终态",
        )
        for item in projected:
            event = RunEvent(
                event=cast(Any, item.event),
                run_id=item.run_id,
                thread_id=item.thread_id,
                sequence=item.sequence,
                message_id=item.message_id,
                payload=item.payload,
            )
            assert repository.apply_run_event(event)

    with open_sqlite_conversation_repository(database) as repository:
        stored = repository.get_run(run_id)

    assert stored is not None
    assert stored.status == "completed"
    assert stored.finish_reason == "turn_capped"
    assert stored.input_tokens == 80
    assert stored.output_tokens == 20
    assert stored.total_tokens == 100
    assert stored.model_calls == 4


def test_pinned_product_run_keeps_budget_across_hidden_continuation_turns() -> None:
    tracker = RunBudgetTracker()
    tracker.pin_run("product-run")
    assert tracker.reserve_model_call() is None
    tracker.record_response(
        _usage_message("第一轮", input_tokens=10, output_tokens=5)
    )

    # 图节点会用每一轮 HumanMessage ID 调 begin_run；固定后不能重置产品 Run 累计值。
    tracker.begin_run("hidden-continuation-message")
    assert tracker.reserve_model_call() is None
    tracker.record_response(
        _usage_message("第二轮", input_tokens=20, output_tokens=7)
    )

    assert tracker.snapshot().total_tokens == 42
    assert tracker.snapshot().model_calls == 2
