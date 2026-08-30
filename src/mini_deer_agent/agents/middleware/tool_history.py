"""修复中断后不完整的工具调用消息历史。"""

import logging
from collections import defaultdict, deque
from collections.abc import Sequence

from langchain_core.messages import BaseMessage, ToolMessage


logger = logging.getLogger(__name__)
_INTERRUPTED_TOOL_CONTENT = (
    "[工具调用已中断，未返回结果。不得假设调用成功；"
    "如果当前任务仍需要该结果，请重新调用工具。]"
)


def _message_tool_calls(message: BaseMessage) -> list[dict]:
    """返回 AI 消息中具有可配对 ID 的结构化工具调用。"""
    if getattr(message, "type", None) != "ai":
        return []
    return [
        tool_call
        for tool_call in (getattr(message, "tool_calls", None) or [])
        if isinstance(tool_call, dict)
        and isinstance(tool_call.get("id"), str)
        and bool(tool_call["id"].strip())
    ]


def _tool_name(tool_call: dict) -> str:
    """为合成 ToolMessage 提供严格协议可接受的非空工具名。"""
    name = tool_call.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return "unknown_tool"


def repair_tool_call_message_history(
    messages: Sequence[BaseMessage],
) -> list[BaseMessage]:
    """构造只供模型调用使用的合法工具消息历史。

    LangGraph 在工具节点完成时才提交 ToolMessage。若 Run 在此之前被取消，
    checkpoint 会保留 AIMessage.tool_calls，却没有一一对应的工具结果。
    OpenAI-compatible 模型会拒绝这种历史。本函数只修复传给模型的视图：

    - 把已有 ToolMessage 放回发起调用的 AIMessage 后；
    - 为缺失结果补充 status=error 的合成 ToolMessage；
    - 丢弃找不到来源工具调用的孤儿 ToolMessage。

    原 checkpoint 和产品时间线均不会被修改，因此历史展示仍以持久化事件为准。
    """
    original = list(messages)
    tool_messages_by_id: dict[str, deque[ToolMessage]] = defaultdict(deque)
    declared_tool_call_ids: set[str] = set()

    for message in original:
        if isinstance(message, ToolMessage):
            tool_messages_by_id[message.tool_call_id].append(message)
            continue
        for tool_call in _message_tool_calls(message):
            declared_tool_call_ids.add(tool_call["id"])

    repaired: list[BaseMessage] = []
    injected_count = 0
    dropped_count = 0
    for message in original:
        if isinstance(message, ToolMessage):
            # 有来源的结果会在对应 AIMessage 后按调用顺序重新插入。
            if message.tool_call_id not in declared_tool_call_ids:
                dropped_count += 1
            continue

        repaired.append(message)
        for tool_call in _message_tool_calls(message):
            tool_call_id = tool_call["id"]
            candidates = tool_messages_by_id.get(tool_call_id)
            if candidates:
                repaired.append(candidates.popleft())
                continue
            repaired.append(
                ToolMessage(
                    content=_INTERRUPTED_TOOL_CONTENT,
                    tool_call_id=tool_call_id,
                    name=_tool_name(tool_call),
                    status="error",
                )
            )
            injected_count += 1

    if injected_count or dropped_count:
        # 日志只记录数量，不输出用户消息、工具参数或工具结果。
        logger.warning(
            "模型消息历史已修复：injected_tool_results=%d, dropped_orphans=%d",
            injected_count,
            dropped_count,
        )
    return repaired
