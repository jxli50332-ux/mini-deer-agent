"""定义可随一轮消息提交的小型 UTF-8 文本附件业务规则。"""

from dataclasses import dataclass
from typing import Literal


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


@dataclass(frozen=True, slots=True)
class TextAttachment:
    """表示已经由服务端验证、可以持久化和交给 Agent 的文本附件。"""

    filename: str
    media_type: TextAttachmentMediaType
    size_bytes: int
    content: str


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
