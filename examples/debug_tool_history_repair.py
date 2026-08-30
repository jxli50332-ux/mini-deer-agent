"""在 PyCharm 中逐步调试中断后的工具消息历史修复。"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from mini_deer_agent.agents.middleware import repair_tool_call_message_history


def message_summary(message: BaseMessage) -> str:
    """生成不展开完整消息对象的调试摘要。"""
    return (
        f"{type(message).__name__}: "
        f"tool_call_id={getattr(message, 'tool_call_id', None)!r}, "
        f"status={getattr(message, 'status', None)!r}, "
        f"text={message.text!r}"
    )


# 断点 1：观察一个 AIMessage 如何同时声明五个工具调用。
human_message = HumanMessage(
    content="请查询北京、上海、广州、深圳和杭州的天气。"
)
ai_message = AIMessage(
    content="我来查询这五个城市的天气。",
    tool_calls=[
        {
            "name": "get_weather",
            "args": {"city": "北京"},
            "id": "call-01",
            "type": "tool_call",
        },
        {
            "name": "get_weather",
            "args": {"city": "上海"},
            "id": "call-02",
            "type": "tool_call",
        },
        {
            "name": "get_weather",
            "args": {"city": "广州"},
            "id": "call-03",
            "type": "tool_call",
        },
        {
            "name": "get_weather",
            "args": {"city": "深圳"},
            "id": "call-04",
            "type": "tool_call",
        },
        {
            "name": "get_weather",
            "args": {"city": "杭州"},
            "id": "call-05",
            "type": "tool_call",
        },
    ],
)

# 北京和深圳调用成功；上海调用完成但明确失败。
beijing_result = ToolMessage(
    content="北京：晴，25°C。",
    tool_call_id="call-01",
    name="get_weather",
    status="success",
)
shanghai_error = ToolMessage(
    content="上海天气查询超时。",
    tool_call_id="call-02",
    name="get_weather",
    status="error",
)
shenzhen_result = ToolMessage(
    content="深圳：多云，29°C。",
    tool_call_id="call-04",
    name="get_weather",
    status="success",
)

# 广州和杭州在用户终止 Run 时没有留下 ToolMessage。
# 已有结果故意按完成时间乱序排列，修复函数会把它们放回工具声明顺序。
messages: list[BaseMessage] = [
    human_message,
    ai_message,
    shenzhen_result,
    shanghai_error,
    beijing_result,
]

print("修复前：")
for index, message in enumerate(messages):
    print(index, message_summary(message))

# 断点 2：在下一行设置断点，使用 Step Into 进入真实修复函数。
repaired_messages = repair_tool_call_message_history(messages)

# 断点 3：观察成功、明确失败和合成中断结果如何按 call-01～call-05 排列。
print("\n修复后：")
for index, message in enumerate(repaired_messages):
    print(index, message_summary(message))

tool_results = [
    message for message in repaired_messages if isinstance(message, ToolMessage)
]
assert [message.tool_call_id for message in tool_results] == [
    "call-01",
    "call-02",
    "call-03",
    "call-04",
    "call-05",
]
assert [message.status for message in tool_results] == [
    "success",
    "error",
    "error",
    "success",
    "error",
]
assert tool_results[0] is beijing_result
assert tool_results[1] is shanghai_error
assert tool_results[3] is shenzhen_result
assert "已中断" in tool_results[2].text
assert "已中断" in tool_results[4].text

print("\n断言通过：已有结果被复用，广州和杭州获得了合成中断结果。")
