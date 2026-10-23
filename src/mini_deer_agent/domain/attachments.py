"""定义随一轮消息提交的 UTF-8 文本与视觉图片附件业务规则。"""

from dataclasses import dataclass
from typing import Literal

from mini_deer_agent.domain.image_attachments import (
    ImageAttachmentMediaType,
    MAX_IMAGE_ATTACHMENTS_TOTAL_BYTES,
    validate_image_content,
)


MAX_TEXT_ATTACHMENT_COUNT = 3
MAX_TEXT_ATTACHMENT_BYTES = 32 * 1024
MAX_TEXT_ATTACHMENTS_TOTAL_BYTES = 64 * 1024
MAX_TEXT_ATTACHMENT_FILENAME_LENGTH = 120

# 只收录可以安全作为 UTF-8 文本内联进模型上下文的扩展名。
# 媒体类型由服务端根据扩展名推导，不信任客户端声明，因此这里必须与前端映射保持一致。
_MEDIA_TYPES_BY_EXTENSION = {
    # 基础文本与数据
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    ".csv": "text/csv",
    # 编程语言
    ".py": "text/x-python",
    ".js": "text/javascript",
    ".jsx": "text/jsx",
    ".ts": "text/typescript",
    ".tsx": "text/tsx",
    ".go": "text/x-go",
    ".java": "text/x-java",
    ".c": "text/x-c",
    ".h": "text/x-c",
    ".cpp": "text/x-c++",
    ".hpp": "text/x-c++",
    ".rs": "text/x-rust",
    ".sql": "text/x-sql",
    ".sh": "text/x-sh",
    # Web 标记与样式
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".scss": "text/x-scss",
    # 配置与结构化数据
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".xml": "text/xml",
    ".toml": "application/toml",
}

# 从白名单推导出的媒体类型联合，供领域模型与 HTTP schema 共用，避免各自硬编码白名单。
TextAttachmentMediaType = Literal[
    "text/plain",
    "text/markdown",
    "application/json",
    "text/csv",
    "text/x-python",
    "text/javascript",
    "text/jsx",
    "text/typescript",
    "text/tsx",
    "text/x-go",
    "text/x-java",
    "text/x-c",
    "text/x-c++",
    "text/x-rust",
    "text/x-sql",
    "text/x-sh",
    "text/html",
    "text/css",
    "text/x-scss",
    "text/yaml",
    "text/xml",
    "application/toml",
]


AttachmentMediaType = TextAttachmentMediaType | ImageAttachmentMediaType


@dataclass(frozen=True, slots=True)
class Attachment:
    """已验证的附件；文本保存正文，图片保存标准 data URL，大小始终为原始字节数。"""

    filename: str
    media_type: AttachmentMediaType
    size_bytes: int
    content: str


# 保留旧领域入口，已有调用者和文本附件数据无需迁移。
TextAttachment = Attachment


def _validated_attachment(filename: str, content: str) -> Attachment:
    """校验文件名及实际内容，由可信端计算类型和原始字节数。"""
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
    if extension in {".png", ".jpg", ".jpeg"}:
        image_type, size, data_url = validate_image_content(normalized_name, content)
        return Attachment(normalized_name, image_type, size, data_url)
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
    return Attachment(
        filename=normalized_name,
        media_type=media_type,
        size_bytes=size_bytes,
        content=content,
    )


def validate_attachment_batch(
    values: list[tuple[str, str]] | tuple[tuple[str, str], ...],
) -> tuple[Attachment, ...]:
    """混合附件共用数量限制，文本与图片分别应用原始字节预算。"""
    if len(values) > MAX_TEXT_ATTACHMENT_COUNT:
        raise ValueError("too many text attachments")

    attachments = tuple(
        _validated_attachment(filename, content) for filename, content in values
    )
    text_bytes = sum(
        item.size_bytes for item in attachments
        if not item.media_type.startswith("image/")
    )
    image_bytes = sum(
        item.size_bytes for item in attachments
        if item.media_type.startswith("image/")
    )
    if text_bytes > MAX_TEXT_ATTACHMENTS_TOTAL_BYTES:
        raise ValueError("text attachments total size is too large")
    if image_bytes > MAX_IMAGE_ATTACHMENTS_TOTAL_BYTES:
        raise ValueError("image attachments total size exceeds 8 MiB")
    return attachments


def validate_text_attachment_batch(
    values: list[tuple[str, str]] | tuple[tuple[str, str], ...],
) -> tuple[Attachment, ...]:
    """兼容既有严格文本入口，不把图片静默传给仅接受文本的旧调用方。"""
    attachments = validate_attachment_batch(values)
    if any(item.media_type.startswith("image/") for item in attachments):
        raise ValueError("unsupported text attachment type")
    return attachments
