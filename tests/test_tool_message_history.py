"""验证中断工具调用在进入模型前会恢复为合法消息协议。"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from mini_deer_agent.agents.middleware import repair_tool_call_message_history


def _tool_call(call_id: str, city: str) -> dict:
    """创建测试使用的天气工具调用。"""
    return {
        "name": "get_weather",
        "args": {"city": city},
        "id": call_id,
        "type": "tool_call",
    }


def test_dangling_tool_calls_receive_results_before_next_human_message() -> None:
    """被取消的并行调用必须各有错误结果，且结果位于下一条用户消息之前。"""
    messages = [
        AIMessage(
            content="正在查询。",
            tool_calls=[
                _tool_call("call-beijing", "北京"),
                _tool_call("call-shanghai", "上海"),
            ],
        ),
        HumanMessage(content="继续刚才的任务。"),
    ]

    repaired = repair_tool_call_message_history(messages)

    assert [type(message).__name__ for message in repaired] == [
        "AIMessage",
        "ToolMessage",
        "ToolMessage",
        "HumanMessage",
    ]
    assert [message.tool_call_id for message in repaired[1:3]] == [
        "call-beijing",
        "call-shanghai",
    ]
    assert all(message.status == "error" for message in repaired[1:3])
    assert "重新调用工具" in repaired[1].text


def test_existing_tool_results_are_grouped_and_only_missing_results_are_added() -> None:
    """已有结果必须复用，只有未返回的调用才生成合成结果。"""
    existing_result = ToolMessage(
        content="北京天气：晴。",
        tool_call_id="call-beijing",
        name="get_weather",
    )
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                _tool_call("call-beijing", "北京"),
                _tool_call("call-shanghai", "上海"),
            ],
        ),
        HumanMessage(content="中间插入的消息。"),
        existing_result,
    ]

    repaired = repair_tool_call_message_history(messages)

    assert repaired[1] is existing_result
    assert isinstance(repaired[2], ToolMessage)
    assert repaired[2].tool_call_id == "call-shanghai"
    assert repaired[2].status == "error"
    assert isinstance(repaired[3], HumanMessage)


def test_orphan_tool_results_are_removed_from_model_view() -> None:
    """没有上游 AI 工具请求的结果不能进入严格模型协议。"""
    human = HumanMessage(content="你好。")
    orphan = ToolMessage(
        content="无来源结果。",
        tool_call_id="missing-call",
        name="get_weather",
    )

    repaired = repair_tool_call_message_history([orphan, human])

    assert repaired == [human]


def test_valid_tool_transcript_keeps_original_message_objects() -> None:
    """合法历史不得生成重复结果或复制已有消息对象。"""
    ai_message = AIMessage(
        content="",
        tool_calls=[_tool_call("call-beijing", "北京")],
    )
    tool_message = ToolMessage(
        content="北京天气：晴。",
        tool_call_id="call-beijing",
        name="get_weather",
    )
    human_message = HumanMessage(content="谢谢。")

    repaired = repair_tool_call_message_history(
        [ai_message, tool_message, human_message]
    )

    assert repaired == [ai_message, tool_message, human_message]
    assert repaired[0] is ai_message
    assert repaired[1] is tool_message
    assert repaired[2] is human_message
