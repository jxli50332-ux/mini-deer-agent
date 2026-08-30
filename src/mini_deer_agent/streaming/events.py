"""定义 LangGraph 执行层与传输层之间的内部消息事件。"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import BaseMessage


# 当前事件保留原始 LangChain 消息供 SSE 适配器识别；后续 wire contract 不直接暴露该类型。
type AgentMessageEvent = tuple[BaseMessage, dict[str, Any]]

# 判别联合类型限制公开协议的事件名称，拼写错误会在类型检查阶段暴露。
type RunEventName = Literal[
    "run_started",
    "ai_delta",
    "tool_call_delta",
    "tool_result",
    "run_error",
    "run_interrupted",
    "run_completed",
]


@dataclass(frozen=True, slots=True)
class RunEvent:
    """表示与 LangGraph 类型解耦的一条版本化 Agent run 事件。"""

    event: RunEventName
    run_id: str
    thread_id: str
    sequence: int
    message_id: str | None
    payload: Mapping[str, Any]
    version: str = "1"

    @property
    def event_id(self) -> str:
        """返回可用于日志、去重和未来事件重放的稳定 SSE ID。"""
        return f"{self.run_id}:{self.sequence}"

    def to_data(self) -> dict[str, Any]:
        """转换为公开 JSON envelope，不泄露内部消息或 metadata 对象。"""
        return {
            "version": self.version,
            "run_id": self.run_id,
            "thread_id": self.thread_id,
            "sequence": self.sequence,
            "message_id": self.message_id,
            "payload": dict(self.payload),
        }
