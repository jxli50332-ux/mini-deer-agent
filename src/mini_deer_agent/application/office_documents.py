"""读取 Word MCP 的实际产物，提供与模型回答无关的文档内容。"""

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from mini_deer_agent.workspace.files import decode_project_text


WORD_DOCUMENTS_DIRECTORY = Path(__file__).resolve().parents[3] / "data" / "word-documents"
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_PREVIEW_CHARS = 150_000
TEXT_EXTENSIONS = {".md", ".markdown", ".txt", ".text", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".xml", ".html", ".css", ".scss", ".csv", ".tsv", ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".sql", ".sh", ".ps1", ".bat", ".c", ".cpp", ".h", ".hpp", ".rs", ".go", ".java", ".rb", ".log", ".rst", ".vue", ".svelte"}
_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
_W = "{" + _NS["w"] + "}"


class OfficeDocumentError(ValueError):
    """对外仅返回稳定错误，不泄露宿主文件路径。"""

    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class OfficeDocument:
    filename: str
    size_bytes: int
    modified_at: str


@dataclass(frozen=True)
class WordPreview:
    document: OfficeDocument
    title: str
    blocks: list[dict[str, object]]
    truncated: bool
    kind: str = "word"
    content: str | None = None


def text_preview(document: OfficeDocument, content: bytes) -> WordPreview:
    status, text = decode_project_text(content)
    if status != "text":
        raise OfficeDocumentError("unsupported_text", "文件不是有效的 UTF-8 纯文本，不能使用文本预览。", 415)
    kind = "markdown" if Path(document.filename).suffix.lower() in {".md", ".markdown"} else "text"
    return WordPreview(document, Path(document.filename).stem, [], len(text) > MAX_PREVIEW_CHARS, kind, text[:MAX_PREVIEW_CHARS])


def _paragraph_text(paragraph: ET.Element) -> str:
    return "".join(
        node.text or "" if node.tag == _W + "t" else "\t" if node.tag == _W + "tab" else "\n"
        for node in paragraph.iter()
        if node.tag in {_W + "t", _W + "tab", _W + "br"}
    )


class OfficeDocumentStore:
    """只发布明确的 Word 输出目录；浏览器不能请求任意绝对路径。"""

    def __init__(self, directory: Path = WORD_DOCUMENTS_DIRECTORY):
        self.directory = directory.resolve()

    def _path(self, filename: str) -> Path:
        if (
            Path(filename).suffix.lower() not in TEXT_EXTENSIONS | {".docx"}
            or len(filename) > 255
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', filename)
            or filename.endswith((" ", "."))
        ):
            raise OfficeDocumentError("invalid_document_name", "文档文件名无效。", 400)
        path = self.directory / filename
        if path.is_symlink() or path.resolve().parent != self.directory:
            raise OfficeDocumentError("document_not_found", "文档不存在或不能访问。", 404)
        if not path.is_file():
            raise OfficeDocumentError("document_not_found", "文档已移动、删除或尚未生成。", 404)
        return path

    def describe(self, filename: str) -> OfficeDocument:
        stat = self._path(filename).stat()
        return OfficeDocument(
            filename=filename,
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        )

    def list_documents(self) -> list[OfficeDocument]:
        if not self.directory.is_dir():
            return []
        documents = []
        for path in self.directory.iterdir():
            if path.suffix.lower() not in TEXT_EXTENSIONS | {".docx"} or path.name.startswith("~$"):
                continue
            try:
                documents.append(self.describe(path.name))
            except (OfficeDocumentError, OSError):
                continue  # 文件可能正在生成或已被外部进程移动。
        return sorted(documents, key=lambda item: item.modified_at, reverse=True)[:200]

    def read(self, filename: str) -> bytes:
        path = self._path(filename)
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            raise OfficeDocumentError("document_too_large", "文档超过 10 MiB，暂不支持在线查看。", 413)
        content = path.read_bytes()
        if len(content) > MAX_DOCUMENT_BYTES:
            raise OfficeDocumentError("document_too_large", "文档超过在线查看上限。", 413)
        return content

    def preview(self, filename: str) -> WordPreview:
        content = self.read(filename)
        if Path(filename).suffix.lower() != ".docx":
            return text_preview(self.describe(filename), content)
        try:
            with ZipFile(BytesIO(content)) as archive:
                part = archive.getinfo("word/document.xml")
                if part.file_size > MAX_XML_BYTES or sum(item.file_size for item in archive.infolist()) > 40 * 1024 * 1024:
                    raise OfficeDocumentError("document_too_large", "文档展开后超过预览上限。", 413)
                document = ET.fromstring(archive.read(part))
            body = document.find("w:body", _NS)
            if body is None:
                raise ValueError("missing body")
        except (BadZipFile, KeyError, ET.ParseError, ValueError, RuntimeError) as exc:
            if isinstance(exc, OfficeDocumentError):
                raise
            raise OfficeDocumentError("invalid_document", "无法预览此 Word 文件，文件可能尚未写完或已损坏。") from exc

        blocks: list[dict[str, object]] = []
        remaining = MAX_PREVIEW_CHARS
        truncated = False
        for child in body:
            if remaining <= 0 or len(blocks) >= 2_000:
                truncated = True
                break
            if child.tag == _W + "p":
                text = _paragraph_text(child)
                style = child.find("w:pPr/w:pStyle", _NS)
                style_name = style.get(_W + "val", "") if style is not None else ""
                heading = re.fullmatch(r"(?:Heading|标题)\s*([1-6])", style_name, re.IGNORECASE)
                level = int(heading[1]) if heading else 1 if style_name == "Title" else 0
                blocks.append({"kind": "paragraph", "text": text[:remaining], "heading_level": level})
                truncated |= len(text) > remaining
                remaining -= len(text)
            elif child.tag == _W + "tbl":
                rows = []
                for row in child.findall("w:tr", _NS):
                    if remaining <= 0 or len(rows) >= 500:
                        truncated = True
                        break
                    cells = []
                    source_cells = row.findall("w:tc", _NS)
                    truncated |= len(source_cells) > 50
                    for cell in source_cells[:50]:
                        text = "\n".join(_paragraph_text(p) for p in cell.findall("w:p", _NS))
                        cells.append(text[:max(0, remaining)])
                        truncated |= len(text) > remaining
                        remaining -= len(text)
                    rows.append(cells)
                blocks.append({"kind": "table", "rows": rows})
        return WordPreview(self.describe(filename), Path(filename).stem, blocks, truncated)
