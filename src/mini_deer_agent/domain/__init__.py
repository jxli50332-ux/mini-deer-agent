"""公开 Mini Deer Agent 的核心业务领域模型。"""

from mini_deer_agent.domain.attachments import (
    MAX_TEXT_ATTACHMENT_BYTES,
    MAX_TEXT_ATTACHMENT_COUNT,
    MAX_TEXT_ATTACHMENT_FILENAME_LENGTH,
    MAX_TEXT_ATTACHMENTS_TOTAL_BYTES,
    TextAttachment,
    TextAttachmentMetadata,
    validate_text_attachment_batch,
)

from mini_deer_agent.domain.conversations import (
    ConversationHistoryPage,
    MAX_THREAD_TITLE_LENGTH,
    MessageHistoryItem,
    RunRecord,
    StoredRunEventRecord,
    ThreadRecord,
    TimelineHistoryItem,
    ToolExecutionHistoryItem,
    default_thread_title,
    normalize_thread_title,
)


__all__ = [
    "ConversationHistoryPage",
    "MAX_TEXT_ATTACHMENT_BYTES",
    "MAX_TEXT_ATTACHMENT_COUNT",
    "MAX_TEXT_ATTACHMENT_FILENAME_LENGTH",
    "MAX_TEXT_ATTACHMENTS_TOTAL_BYTES",
    "MAX_THREAD_TITLE_LENGTH",
    "MessageHistoryItem",
    "RunRecord",
    "StoredRunEventRecord",
    "ThreadRecord",
    "TextAttachment",
    "TextAttachmentMetadata",
    "TimelineHistoryItem",
    "ToolExecutionHistoryItem",
    "default_thread_title",
    "normalize_thread_title",
    "validate_text_attachment_batch",
]
