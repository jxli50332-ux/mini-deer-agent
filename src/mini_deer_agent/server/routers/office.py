"""为 Office 产物提供真实文件链接和结构化内容预览。"""

from dataclasses import asdict
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query
from pydantic import BaseModel

from mini_deer_agent.application.office_documents import OfficeDocumentError, OfficeDocumentStore
from mini_deer_agent.application.text_documents import preview_text_document, read_text_document
from mini_deer_agent.application.workspaces import FileAccess
from mini_deer_agent.domain.workspaces import ProjectError
from mini_deer_agent.server.dependencies import get_project_service
from mini_deer_agent.workspace.paths import ProjectRootPolicy
from mini_deer_agent.server.workspace_access import require_workspace_access


router = APIRouter(
    prefix="/api/v1/office/documents",
    tags=["office"],
    dependencies=[Depends(require_workspace_access)],
)


def get_office_document_store() -> OfficeDocumentStore:
    return OfficeDocumentStore()


Store = Annotated[OfficeDocumentStore, Depends(get_office_document_store)]


class DocumentResponse(BaseModel):
    filename: str
    size_bytes: int
    modified_at: str


class DocumentsResponse(BaseModel):
    documents: list[DocumentResponse]


class PreviewResponse(BaseModel):
    document: DocumentResponse
    title: str
    blocks: list[dict[str, object]]
    truncated: bool
    kind: str = "word"
    content: str | None = None


def _http_error(exc: OfficeDocumentError) -> HTTPException:
    return HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})


@router.get("", response_model=DocumentsResponse)
def list_documents(store: Store) -> DocumentsResponse:
    return DocumentsResponse(documents=[DocumentResponse(**asdict(doc)) for doc in store.list_documents()])


def _text_access(request: Request, project_id: UUID | None) -> FileAccess:
    if project_id is not None:
        return FileAccess.for_project(get_project_service(request), str(project_id))
    settings = request.app.state.settings
    policy = ProjectRootPolicy(
        allowed_roots=settings.workspace_allowed_roots,
        blocked_roots=(settings.application_database_path.resolve().parent, settings.checkpoint_database_path.resolve().parent, settings.tool_output_directory.resolve()),
    )
    return FileAccess.for_allowed_roots(policy)


@router.get("/text-preview", response_model=PreviewResponse)
def preview_text(request: Request, response: Response, path: Annotated[str, Query(min_length=1, max_length=2048)], project_id: UUID | None = None) -> PreviewResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return PreviewResponse(**asdict(preview_text_document(_text_access(request, project_id), path)))
    except OfficeDocumentError as exc:
        raise _http_error(exc) from None
    except ProjectError as exc:
        raise HTTPException(404, detail={"code": exc.code, "message": exc.message}) from None


@router.get("/text-download")
def download_text(request: Request, path: Annotated[str, Query(min_length=1, max_length=2048)], project_id: UUID | None = None) -> Response:
    try:
        document, content = read_text_document(_text_access(request, project_id), path)
    except OfficeDocumentError as exc:
        raise _http_error(exc) from None
    except ProjectError as exc:
        raise HTTPException(404, detail={"code": exc.code, "message": exc.message}) from None
    return Response(content, media_type="text/plain", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(document.filename, safe='')}", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/{filename}/preview", response_model=PreviewResponse)
def preview_document(filename: str, store: Store, response: Response) -> PreviewResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return PreviewResponse(**asdict(store.preview(filename)))
    except OfficeDocumentError as exc:
        raise _http_error(exc) from None
    except OSError:
        raise HTTPException(409, detail={"code": "document_unavailable", "message": "文件正在写入或已移动，请稍后刷新。"}) from None


@router.get("/{filename}/download")
def download_document(filename: str, store: Store) -> Response:
    try:
        content = store.read(filename)
    except OfficeDocumentError as exc:
        raise _http_error(exc) from None
    except OSError:
        raise HTTPException(409, detail={"code": "document_unavailable", "message": "文件正在写入或已移动，请稍后刷新。"}) from None
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document" if Path(filename).suffix.lower() == ".docx" else "text/plain",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
