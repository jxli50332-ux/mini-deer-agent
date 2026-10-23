"""验证 Word 产物的真实链接、中文内容、下载与目录边界。"""

from pathlib import Path
from zipfile import ZipFile
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from mini_deer_agent.application import office_documents
from mini_deer_agent.application.office_documents import OfficeDocumentStore
from mini_deer_agent.core import Settings
from mini_deer_agent.server.routers import office


@pytest.fixture
def office_client(tmp_path: Path):
    app = FastAPI()
    app.state.settings = Settings(workspace_allowed_roots=(tmp_path,), _env_file=None)
    app.include_router(office.router)
    app.dependency_overrides[office.get_office_document_store] = lambda: OfficeDocumentStore(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        yield client


def _write_docx(path: Path):
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
        <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>中文报告</w:t></w:r></w:p>
        <w:p><w:r><w:t>正文&lt;script&gt;</w:t></w:r><w:r><w:t>保持文本</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>收入</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>100</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
        </w:body></w:document>''')


def test_chinese_word_listing_preview_and_exact_download(office_client, tmp_path):
    path = tmp_path / "财报.docx"
    _write_docx(path)
    (tmp_path / "~$财报.docx").write_text("lock")
    (tmp_path / "private.bin").write_bytes(b"\x00\x01")
    documents = office_client.get("/api/v1/office/documents").json()["documents"]
    assert [item["filename"] for item in documents] == ["财报.docx"]
    assert documents[0]["size_bytes"] == path.stat().st_size
    response = office_client.get("/api/v1/office/documents/财报.docx/preview")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["blocks"] == [
        {"kind": "paragraph", "text": "中文报告", "heading_level": 1},
        {"kind": "paragraph", "text": "正文<script>保持文本", "heading_level": 0},
        {"kind": "table", "rows": [["收入", "100"]]},
    ]
    download = office_client.get("/api/v1/office/documents/财报.docx/download")
    assert download.content == path.read_bytes()
    assert download.headers["content-disposition"] == f"attachment; filename*=UTF-8''{quote(path.name)}"
    assert "wordprocessingml.document" in download.headers["content-type"]


@pytest.mark.parametrize("name", ["..\\secret.docx", "C:secret.docx", "report.pdf"])
def test_rejects_non_document_or_host_path(office_client, name):
    response = office_client.get(f"/api/v1/office/documents/{quote(name, safe='')}/download")
    assert response.status_code == 400


def test_missing_and_incomplete_document_have_clear_errors(office_client, tmp_path):
    assert office_client.get("/api/v1/office/documents/missing.docx/preview").status_code == 404
    (tmp_path / "incomplete.docx").write_bytes(b"not a zip")
    response = office_client.get("/api/v1/office/documents/incomplete.docx/preview")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_document"


def test_preview_limits_expanded_xml_and_output_text(office_client, tmp_path, monkeypatch):
    _write_docx(tmp_path / "report.docx")
    monkeypatch.setattr(office_documents, "MAX_PREVIEW_CHARS", 2)
    result = office_client.get("/api/v1/office/documents/report.docx/preview").json()
    assert result["truncated"] is True
    assert result["blocks"][0]["text"] == "中文"
    monkeypatch.setattr(office_documents, "MAX_XML_BYTES", 20)
    assert office_client.get("/api/v1/office/documents/report.docx/preview").status_code == 413


def test_document_endpoints_keep_existing_local_origin_boundary(office_client):
    assert office_client.get("/api/v1/office/documents", headers={"Origin": "https://outside.invalid"}).status_code == 403


def test_symlinked_document_is_not_published(office_client, tmp_path):
    target = tmp_path.parent / f"{tmp_path.name}-outside.docx"
    _write_docx(target)
    try:
        (tmp_path / "link.docx").symlink_to(target)
    except OSError:
        pytest.skip("Creating symlinks is unavailable")
    assert office_client.get("/api/v1/office/documents").json()["documents"] == []
    assert office_client.get("/api/v1/office/documents/link.docx/download").status_code == 404


@pytest.mark.parametrize("name", ["report.md", "sample.txt", "sample.py", "sample.json"])
def test_text_preview_and_download_in_document_output(office_client, tmp_path, name):
    raw = b'\xef\xbb\xbf' + '# 中文标题\r\n\r\n正文\r\n'.encode('utf-8')
    (tmp_path / name).write_bytes(raw)
    response = office_client.get(f"/api/v1/office/documents/{name}/preview")
    assert response.status_code == 200
    assert response.json()["kind"] == ("markdown" if name.endswith(".md") else "text")
    assert response.json()["content"] == raw.decode("utf-8-sig")
    assert office_client.get(f"/api/v1/office/documents/{name}/download").content == raw


def test_workspace_markdown_links_preserve_original_bytes_and_bounds(office_client, tmp_path):
    raw = b'\xef\xbb\xbf' + '# 工作区文档\r\n\r\n正文\r\n'.encode('utf-8')
    (tmp_path / "report.md").write_bytes(raw)
    query = {"path": "workspace-1/report.md"}
    response = office_client.get("/api/v1/office/documents/text-preview", params=query)
    assert response.status_code == 200
    assert response.json()["kind"] == "markdown"
    assert response.json()["content"] == raw.decode("utf-8-sig")
    assert office_client.get("/api/v1/office/documents/text-download", params=query).content == raw
    for path in ("workspace-1/../outside.md", "workspace-2/report.md", "C:/secret.txt", "workspace-1/.env"):
        assert office_client.get("/api/v1/office/documents/text-preview", params={"path": path}).status_code == 404


def test_binary_invalid_utf8_and_oversize_text_are_not_rendered(office_client, tmp_path, monkeypatch):
    for content in (b"\x00PK\x01", b"\xff\xfe", b"text\x07"):
        (tmp_path / "binary.txt").write_bytes(content)
        assert office_client.get("/api/v1/office/documents/text-preview", params={"path": "workspace-1/binary.txt"}).status_code == 415
    (tmp_path / "binary.txt").write_bytes(b"123456")
    from mini_deer_agent.workspace import files
    monkeypatch.setattr(files, "MAX_BYTES", 5)
    assert office_client.get("/api/v1/office/documents/text-preview", params={"path": "workspace-1/binary.txt"}).status_code == 413


def test_project_text_preview_stops_after_project_is_unregistered(office_client, tmp_path):
    from mini_deer_agent.application.workspaces import ProjectService
    from mini_deer_agent.persistence.conversations import open_sqlite_conversation_repository
    from mini_deer_agent.workspace.paths import ProjectRootPolicy
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("# 项目文件", encoding="utf-8")
    with open_sqlite_conversation_repository(tmp_path / "app.sqlite") as repository:
        service = ProjectService(repository.projects, ProjectRootPolicy(allowed_roots=(tmp_path,)))
        project = service.register(name="demo", root_path=str(root))
        office_client.app.state.project_service = service
        query = {"path": "README.md", "project_id": project.project_id}
        response = office_client.get("/api/v1/office/documents/text-preview", params=query)
        assert response.status_code == 200
        assert response.json()["content"] == "# 项目文件"
        service.unregister(project.project_id)
        assert office_client.get("/api/v1/office/documents/text-preview", params=query).status_code == 404
