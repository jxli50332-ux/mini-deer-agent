"""把已授权的工作区文本快照接入文档面板，保留原始下载字节。"""

from pathlib import Path

from mini_deer_agent.application.office_documents import OfficeDocument, OfficeDocumentError, text_preview
from mini_deer_agent.application.workspaces import FileAccess
from mini_deer_agent.workspace.files import decode_project_text


def read_text_document(access: FileAccess, path: str) -> tuple[OfficeDocument, bytes]:
    metadata, content = access.read_file_bytes(path=path)
    if metadata["status"] == "too_large":
        raise OfficeDocumentError("document_too_large", "文本文件超过 2 MiB，无法在线打开。", 413)
    if decode_project_text(content)[0] != "text":
        raise OfficeDocumentError("unsupported_text", "文件不是有效的 UTF-8 纯文本，不能使用文本预览。", 415)
    # 工作区快照不公开修改时间，不能用请求时间冒充文件的修改时间。
    document = OfficeDocument(Path(path).name, len(content), "")
    return document, content


def preview_text_document(access: FileAccess, path: str):
    document, content = read_text_document(access, path)
    return text_preview(document, content)
