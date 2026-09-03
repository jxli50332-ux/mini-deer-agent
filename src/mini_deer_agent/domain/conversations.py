"""定义与 FastAPI、LangGraph 和 SQLite 解耦的对话历史领域模型。"""

from dataclasses import dataclass
from typing import Any, Literal

from mini_deer_agent.domain.attachments import TextAttachment


type ThreadStatus = Literal["idle", "busy", "error"]
type RunStatus = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
]
type ToolExecutionStatus = Literal[
    "pending",
    "completed",
    "failed",
    "cancelled",
]


MAX_THREAD_TITLE_LENGTH = 60


def normalize_thread_title(value: str) -> str:
    """把标题压成单行稳定文本，避免空白和换行破坏列表布局。"""
    return " ".join(value.split())


def default_thread_title(user_message: str) -> str:
    """从首条用户消息生成无需额外模型调用的默认 Thread 标题。"""
    normalized = normalize_thread_title(user_message)
    if not normalized:
        return "新对话"
    if len(normalized) <= MAX_THREAD_TITLE_LENGTH:
        return normalized
    return normalized[: MAX_THREAD_TITLE_LENGTH - 3].rstrip() + "..."


@dataclass(frozen=True, slots=True)
class ThreadRecord:
    """表示可由产品 API 查询的 Thread 元数据。"""

    thread_id: str
    title: str | None
    status: ThreadStatus
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class RunRecord:
    """表示 Thread 上一次可追踪的 Agent 执行。"""

    run_id: str
    thread_id: str
    status: RunStatus
    user_message_id: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    finish_reason: str | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class StoredRunEventRecord:
    """表示 Event Store 中一条可按 Run sequence 重建的原始事件。"""

    version: str
    event: str
    run_id: str
    thread_id: str
    sequence: int
    message_id: str | None
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True, slots=True)
class MessageHistoryItem:
    """表示用户或模型产生的一条稳定消息及其结构化交互元数据。"""

    kind: Literal["message"]
    item_id: str
    thread_id: str
    run_id: str
    thread_sequence: int
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    reasoning: str | None = None
    attachments: tuple[TextAttachment, ...] = ()
    hidden_from_ui: bool = False
    human_input_response: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ToolExecutionHistoryItem:
    """表示一次工具请求及其最终结果组成的可见时间线项目。"""

    kind: Literal["tool"]
    item_id: str
    thread_id: str
    run_id: str
    thread_sequence: int
    tool_call_id: str
    name: str | None
    input: str
    result: str | None
    status: ToolExecutionStatus
    created_at: str


type TimelineHistoryItem = MessageHistoryItem | ToolExecutionHistoryItem


@dataclass(frozen=True, slots=True)
class ConversationHistoryPage:
    """表示按 Thread 全局序号向前翻页的一页可见时间线。"""

    thread_id: str
    thread_exists: bool
    items: tuple[TimelineHistoryItem, ...]
    has_more: bool
    next_before_sequence: int | None
