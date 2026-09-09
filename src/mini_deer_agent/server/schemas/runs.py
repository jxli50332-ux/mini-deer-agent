"""定义 Agent run HTTP 接口的版本化请求模型。"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from uuid import UUID

from mini_deer_agent.domain import (
    MAX_TEXT_ATTACHMENT_COUNT,
    MAX_TEXT_ATTACHMENT_FILENAME_LENGTH,
    TextAttachment,
    validate_text_attachment_batch,
)


# 请求正文设置明确上限，防止在进入模型前接收无界字符串。
type MessageText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=32_768),
]

# 旧接口仍接收任意非空线程键；正式 v1 路由改由 UUID 路径参数约束身份格式。
type LegacyThreadId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]


type AttachmentFilename = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_TEXT_ATTACHMENT_FILENAME_LENGTH,
    ),
]


class TextAttachmentRequest(BaseModel):
    """接收浏览器已经读取的 UTF-8 文本文件，不信任客户端媒体类型与大小。"""

    model_config = ConfigDict(extra="forbid")

    filename: AttachmentFilename
    content: str = Field(min_length=1, max_length=32_768)


class HumanInputTextResponseRequest(BaseModel):
    """接收自由文本澄清回答，并保留原请求身份。"""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    kind: Literal["human_input_response"]
    request_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
    ]
    response_kind: Literal["text"]
    value: MessageText


class HumanInputOptionResponseRequest(BaseModel):
    """接收卡片中的稳定选项身份和值。"""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    kind: Literal["human_input_response"]
    request_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
    ]
    response_kind: Literal["option"]
    option_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
    ]
    value: MessageText


type HumanInputResponseRequest = Annotated[
    HumanInputTextResponseRequest | HumanInputOptionResponseRequest,
    Field(discriminator="response_kind"),
]


class RunStreamRequest(BaseModel):
    """校验 v1 线程 run 接收的本轮用户消息。"""

    # 正式 API 拒绝未知字段，避免客户端拼写错误被静默忽略。
    model_config = ConfigDict(extra="forbid")

    # 客户端生成的稳定消息 ID 同时用于 optimistic UI 和持久化历史去重。
    message_id: UUID
    message: MessageText
    attachments: list[TextAttachmentRequest] = Field(
        default_factory=list,
        max_length=MAX_TEXT_ATTACHMENT_COUNT,
    )
    human_input_response: HumanInputResponseRequest | None = None
    benchmark_case_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ] | None = None

    def to_domain_attachments(self) -> tuple[TextAttachment, ...]:
        """由服务端重新推导附件类型和 UTF-8 字节数。"""
        return validate_text_attachment_batch(
            [(item.filename, item.content) for item in self.attachments]
        )

    def to_domain_human_input_response(self) -> dict[str, object] | None:
        """把已严格校验的响应转换为不依赖 Pydantic 的应用层数据。"""
        if self.human_input_response is None:
            return None
        return self.human_input_response.model_dump()

    @model_validator(mode="after")
    def validate_attachment_business_rules(self) -> Self:
        """让非法扩展名和按字节超限在启动 Run 前返回 422。"""
        self.to_domain_attachments()
        if self.benchmark_case_id is not None:
            from mini_deer_agent.domain import require_benchmark_case

            require_benchmark_case(self.benchmark_case_id)
        return self


class LegacyChatStreamRequest(BaseModel):
    """兼容旧 `/chat/stream` 请求体，迁移期仍保留 thread_id 字段。"""

    message: MessageText
    thread_id: LegacyThreadId
