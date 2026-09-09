"""验证 14.3 重复工具调用签名、提示和终止原因。"""

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from mini_deer_agent.agents.middleware import (
    LOOP_CAPPED_REASON,
    LOOP_STOP_REASON_KEY,
    ToolLoopDetector,
    ToolLoopPolicy,
    tool_call_signature,
)
from mini_deer_agent.streaming.projector import project_run_events


def _tool_message(name: str, args: dict[str, object]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": name,
                "args": args,
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )


def test_same_arguments_warn_once_then_cap() -> None:
    detector = ToolLoopDetector(ToolLoopPolicy(soft_limit=2, hard_limit=3))
    response = _tool_message("web_search", {"query": "same"})

    assert detector.observe(response) == "continue"
    assert detector.observe(response) == "warn"
    warned = detector.append_pending_warning([HumanMessage(content="task")])
    assert len(warned) == 2
    assert warned[-1].additional_kwargs["kind"] == "loop_warning"
    assert detector.append_pending_warning(warned) is warned
    assert detector.observe(response) == "cap"


def test_new_run_key_resets_repeat_state() -> None:
    detector = ToolLoopDetector(ToolLoopPolicy(soft_limit=2, hard_limit=3))
    response = _tool_message("web_search", {"query": "same"})
    detector.begin_run("run-one")
    assert detector.observe(response) == "continue"
    assert detector.observe(response) == "warn"

    detector.begin_run("run-two")
    assert detector.repeat_count == 0
    assert detector.observe(response) == "continue"


def test_changed_query_and_read_range_do_not_share_signature() -> None:
    first = _tool_message("web_search", {"query": "alpha", "page": 1})
    second = _tool_message("web_search", {"query": "beta", "page": 1})
    read_first = _tool_message(
        "read_file", {"path": "src/app.py", "start_line": 1, "end_line": 100}
    )
    read_next = _tool_message(
        "read_file", {"path": "src/app.py", "start_line": 101, "end_line": 200}
    )

    assert tool_call_signature(first) != tool_call_signature(second)
    assert tool_call_signature(read_first) != tool_call_signature(read_next)


def test_planning_clarification_skill_and_delegation_calls_are_exempt() -> None:
    for name in ("write_todos", "ask_clarification", "activate_skill", "task"):
        assert tool_call_signature(_tool_message(name, {"value": "same"})) is None


def test_projector_surfaces_loop_capped_as_run_finish_reason() -> None:
    events = list(
        project_run_events(
            [
                (
                    AIMessageChunk(
                        content="使用已有证据收尾。",
                        additional_kwargs={LOOP_STOP_REASON_KEY: LOOP_CAPPED_REASON},
                    ),
                    {},
                )
            ],
            run_id="11111111-1111-4111-8111-111111111111",
            thread_id="22222222-2222-4222-8222-222222222222",
        )
    )

    assert events[-1].event == "run_completed"
    assert events[-1].payload["finish_reason"] == "loop_capped"
