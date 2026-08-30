"""定义 Agent run HTTP 接口的版本化请求模型。"""

from typing import Annotated, Self

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

    def to_domain_attachments(self) -> tuple[TextAttachment, ...]:
        """由服务端重新推导附件类型和 UTF-8 字节数。"""
        return validate_text_attachment_batch(
            [(item.filename, item.content) for item in self.attachments]
        )

    @model_validator(mode="after")
    def validate_attachment_business_rules(self) -> Self:
        """让非法扩展名和按字节超限在启动 Run 前返回 422。"""
        self.to_domain_attachments()
        return self


class LegacyChatStreamRequest(BaseModel):
    """兼容旧 `/chat/stream` 请求体，迁移期仍保留 thread_id 字段。"""

    message: MessageText
    thread_id: LegacyThreadId
