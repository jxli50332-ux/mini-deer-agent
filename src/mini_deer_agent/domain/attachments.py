"""定义可随一轮消息提交的小型 UTF-8 文本附件业务规则。"""

from dataclasses import dataclass


MAX_TEXT_ATTACHMENT_COUNT = 3
MAX_TEXT_ATTACHMENT_BYTES = 32 * 1024
MAX_TEXT_ATTACHMENTS_TOTAL_BYTES = 64 * 1024
MAX_TEXT_ATTACHMENT_FILENAME_LENGTH = 120

_MEDIA_TYPES_BY_EXTENSION = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    ".csv": "text/csv",
}


@dataclass(frozen=True, slots=True)
class TextAttachment:
    """表示已经由服务端验证、可以持久化和交给 Agent 的文本附件。"""

    filename: str
    media_type: str
    size_bytes: int
    content: str


@dataclass(frozen=True, slots=True)
class TextAttachmentMetadata:
    """表示可以安全返回给浏览器、但不包含附件正文的历史元数据。"""

    filename: str
    media_type: str
    size_bytes: int


def _validated_attachment(filename: str, content: str) -> TextAttachment:
    """校验一个文件名与正文，并由可信端计算类型和 UTF-8 字节数。"""
    normalized_name = filename.strip()
    if (
        not normalized_name
        or normalized_name in {".", ".."}
        or "/" in normalized_name
        or "\\" in normalized_name
        or any(ord(character) < 32 for character in normalized_name)
    ):
        raise ValueError("unsafe filename")
    if len(normalized_name) > MAX_TEXT_ATTACHMENT_FILENAME_LENGTH:
        raise ValueError("attachment filename is too long")

    dot_index = normalized_name.rfind(".")
    extension = normalized_name[dot_index:].lower() if dot_index >= 0 else ""
    media_type = _MEDIA_TYPES_BY_EXTENSION.get(extension)
    if media_type is None:
        raise ValueError("unsupported attachment type")
    if not content:
        raise ValueError("attachment content must not be empty")
    if "\x00" in content:
        raise ValueError("attachment content must be text")

    size_bytes = len(content.encode("utf-8"))
    if size_bytes > MAX_TEXT_ATTACHMENT_BYTES:
        raise ValueError("text attachment is too large")
    return TextAttachment(
        filename=normalized_name,
        media_type=media_type,
        size_bytes=size_bytes,
        content=content,
    )


def validate_text_attachment_batch(
    values: list[tuple[str, str]] | tuple[tuple[str, str], ...],
) -> tuple[TextAttachment, ...]:
    """校验一轮消息的附件数量、单文件大小和总大小。"""
    if len(values) > MAX_TEXT_ATTACHMENT_COUNT:
        raise ValueError("too many text attachments")

    attachments = tuple(
        _validated_attachment(filename, content) for filename, content in values
    )
    if sum(item.size_bytes for item in attachments) > MAX_TEXT_ATTACHMENTS_TOTAL_BYTES:
        raise ValueError("text attachments total size is too large")
    return attachments
