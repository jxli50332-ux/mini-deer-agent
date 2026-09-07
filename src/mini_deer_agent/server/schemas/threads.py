"""定义 Thread、Run 与历史时间线的版本化 HTTP 响应。"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mini_deer_agent.domain import (
    MAX_THREAD_TITLE_LENGTH,
    TextAttachmentMediaType,
    normalize_thread_title,
)


class ThreadResponse(BaseModel):
    """公开 Thread 的稳定产品元数据。"""

    model_config = ConfigDict(extra="forbid")

    thread_id: str
    title: str | None
    status: Literal["idle", "busy", "error"]
    created_at: str
    updated_at: str
    project_id: str | None = None


class ThreadTitleUpdateRequest(BaseModel):
    """接收一个去除多余空白、长度受限的 Thread 标题。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_THREAD_TITLE_LENGTH)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        """先规范空白再执行长度校验，使 API 与领域规则一致。"""
        if isinstance(value, str):
            return normalize_thread_title(value)
        return value


class RunResponse(BaseModel):
    """公开一次 Run 的身份与最终生命周期状态。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    thread_id: str
    status: Literal[
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
        "interrupted",
    ]
    user_message_id: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    finish_reason: str | None
    error_code: str | None


class RunEventResponse(BaseModel):
    """公开一条已经持久化、可按 sequence 查询的原始 RunEvent。"""

    model_config = ConfigDict(extra="forbid")

    version: Literal["1"]
    event: Literal[
        "run_started",
        "reasoning_delta",
        "ai_delta",
        "tool_call_delta",
        "tool_result",
        "run_error",
        "run_interrupted",
        "run_completed",
    ]
    run_id: str
    thread_id: str
    sequence: int = Field(ge=1)
    message_id: str | None
    payload: dict[str, Any]
    created_at: str


class TextAttachmentResponse(BaseModel):
    """公开一条已持久化文本附件的完整内容，供历史恢复时查看正文。"""

    model_config = ConfigDict(extra="forbid")

    filename: str
    media_type: TextAttachmentMediaType
    size_bytes: int = Field(ge=1)
    content: str = Field(min_length=1)


class MessageHistoryItemResponse(BaseModel):
    """公开一条消息及可用于恢复结构化交互的受控元数据。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["message"]
    id: str
    run_id: str
    thread_sequence: int = Field(ge=1)
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    reasoning: str | None = None
    attachments: list[TextAttachmentResponse] = Field(default_factory=list)
    hidden_from_ui: bool = False
    human_input_response: dict[str, Any] | None = None


class ToolHistoryItemResponse(BaseModel):
    """公开一次工具请求和结果组成的时间线项目。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["tool"]
    id: str
    run_id: str
    thread_sequence: int = Field(ge=1)
    tool_call_id: str
    name: str | None
    input: str
    result: str | None
    status: Literal["pending", "completed", "failed", "cancelled"]
    created_at: str


type HistoryItemResponse = Annotated[
    MessageHistoryItemResponse | ToolHistoryItemResponse,
    Field(discriminator="kind"),
]


class ThreadHistoryPageResponse(BaseModel):
    """公开一页按时间正序排列的 Thread 可见历史。"""

    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    thread_id: str
    thread_exists: bool
    items: list[HistoryItemResponse]
    has_more: bool
    next_before_sequence: int | None = Field(default=None, ge=1)
