"""提供项目登记、查询与解除入口；不向 Agent 注册目录管理工具。"""

from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from mini_deer_agent.application.workspaces import (
    ProjectService,
    ProjectThreadService,
    ThreadProjectConflictError,
)
from mini_deer_agent.domain.workspaces import ProjectError
from mini_deer_agent.server.dependencies import (
    get_project_service,
    get_project_thread_service,
    get_directory_picker,
)
from mini_deer_agent.server.schemas.projects import (
    ProjectListResponse,
    ProjectRegistrationRequest,
    ProjectResponse,
    ProjectThreadCreateRequest,
    ProjectDirectoryResponse,
    ProjectFileResponse,
)
from mini_deer_agent.server.schemas.threads import ThreadResponse
from mini_deer_agent.server.workspace_access import require_workspace_access
from mini_deer_agent.workspace.picker import DirectoryPicker, DirectoryPickerError


router = APIRouter(
    prefix="/api/v1/projects",
    tags=["projects"],
    dependencies=[Depends(require_workspace_access)],
)
type ProjectServiceDependency = Annotated[ProjectService, Depends(get_project_service)]
type ProjectThreadServiceDependency = Annotated[
    ProjectThreadService, Depends(get_project_thread_service)
]
type DirectoryPickerDependency = Annotated[
    DirectoryPicker, Depends(get_directory_picker)
]


def _project_error(error: ProjectError) -> HTTPException:
    """把项目缺失、状态和输入错误映射为稳定 HTTP 契约。"""
    status_code = (
        404
        if error.code == "project_not_found"
        else (
            409
            if error.code in {"project_already_registered", "project_unavailable"}
            else 400
        )
    )
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": error.message},
    )


@router.post("", status_code=201, response_model=ProjectResponse)
def register_project(
    body: ProjectRegistrationRequest, service: ProjectServiceDependency
) -> ProjectResponse:
    """登记已有本机目录，路由仅映射协议和稳定领域错误。"""
    try:
        project = service.register(name=body.name, root_path=body.root_path)
    except ProjectError as exc:
        raise _project_error(exc) from None
    return ProjectResponse.model_validate(project)


@router.post("/pick-directory", status_code=201, response_model=ProjectResponse)
def pick_project_directory(
    service: ProjectServiceDependency,
    picker: DirectoryPickerDependency,
) -> ProjectResponse | Response:
    """打开本机选择器；选中后按目录名登记，取消时不产生项目。"""
    try:
        selected = picker.pick()
        if selected is None:
            return Response(
                status_code=204,
                headers={"Cache-Control": "no-store"},
            )
        project = service.register(
            name=Path(selected).name,
            root_path=selected,
        )
    except DirectoryPickerError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "directory_picker_unavailable",
                "message": str(exc),
            },
        ) from None
    except ProjectError as exc:
        raise _project_error(exc) from None
    return ProjectResponse.model_validate(project)


@router.get("", response_model=ProjectListResponse)
def list_projects(
    service: ProjectServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> ProjectListResponse:
    """查询并复核当前页项目，按创建时间排序保证状态刷新不改变顺序。"""
    records = service.list(limit=limit + 1, offset=offset)
    return ProjectListResponse(
        items=[ProjectResponse.model_validate(record) for record in records[:limit]],
        next_offset=offset + limit if len(records) > limit else None,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: UUID, service: ProjectServiceDependency) -> ProjectResponse:
    """按稳定项目身份返回登记和当前目录状态。"""
    project = service.get(str(project_id))
    if project is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "project_not_found",
                "message": "项目尚未登记。",
            },
        )
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=204)
def unregister_project(project_id: UUID, service: ProjectServiceDependency) -> None:
    """凭据校验后幂等解除登记；接口不接受文件路径或删除文件的选项。"""
    service.unregister(str(project_id))


@router.get("/{project_id}/directory", response_model=ProjectDirectoryResponse)
def get_project_directory(
    project_id: UUID,
    service: ProjectServiceDependency,
    path: Annotated[str, Query(max_length=2048)] = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> ProjectDirectoryResponse:
    """受工作区凭据保护的单层列举；只接收项目内相对目录。"""
    try:
        return ProjectDirectoryResponse.model_validate(
            service.directory(str(project_id), path=path, limit=limit)
        )
    except ProjectError as exc:
        raise _project_error(exc) from None


@router.post("/{project_id}/threads", response_model=ThreadResponse)
def create_project_thread(
    project_id: UUID,
    body: ProjectThreadCreateRequest,
    service: ProjectThreadServiceDependency,
) -> ThreadResponse:
    """创建可安全重试的项目 Thread，不创建目录、Run 或模型 checkpoint。"""
    try:
        thread = service.create(
            project_id=str(project_id), thread_id=str(body.thread_id)
        )
    except ProjectError as exc:
        raise _project_error(exc) from None
    except ThreadProjectConflictError:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "thread_project_conflict",
                "message": "该会话已经属于另一个项目或普通聊天。",
            },
        ) from None
    return ThreadResponse.model_validate(thread, from_attributes=True)


@router.get("/{project_id}/file", response_model=ProjectFileResponse)
def get_project_file(
    project_id: UUID,
    service: ProjectServiceDependency,
    path: Annotated[str, Query(min_length=1, max_length=2048)],
    start_line: Annotated[int, Query(ge=1, le=1000000)] = 1,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> ProjectFileResponse:
    """复用工作区访问门禁，按项目相对路径和行范围预览源码。"""
    try:
        return ProjectFileResponse.model_validate(
            service.read_file(
                str(project_id), path=path, start_line=start_line, limit=limit
            )
        )
    except ProjectError as exc:
        raise _project_error(exc) from None


@router.get("/{project_id}/threads", response_model=list[ThreadResponse])
def list_project_threads(
    project_id: UUID,
    service: ProjectThreadServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> list[ThreadResponse]:
    """只列出指定 Project 的 Thread，普通聊天和其他项目不会混入。"""
    try:
        threads = service.list(
            project_id=str(project_id), limit=limit, offset=offset
        )
    except ProjectError as exc:
        raise _project_error(exc) from None
    return [
        ThreadResponse.model_validate(thread, from_attributes=True)
        for thread in threads
    ]
