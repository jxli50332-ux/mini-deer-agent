"""管理受管目录中的本地用户 Skill，不提供远程下载或生成能力。"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from mini_deer_agent.server.dependencies import (
    get_skill_management_service,
    get_user_skill_manager,
)
from mini_deer_agent.server.schemas import (
    SkillCheckResponse,
    SkillDetailResponse,
    SkillDraftInstallRequest,
    SkillDraftListResponse,
    SkillDraftResponse,
    SkillDraftWriteRequest,
    SkillHistoryListResponse,
    SkillHistoryResponse,
    SkillInstallAuthorizationRequest,
    SkillInstallAuthorizationResponse,
    SkillAgentSettingsResponse,
    SkillAgentSettingsUpdateRequest,
    SkillResourceRequest,
    SkillRollbackRequest,
    RecoverableSkillListResponse,
    RecoverableSkillResponse,
    UserSkillEnabledRequest,
    UserSkillInstallRequest,
    UserSkillListResponse,
    UserSkillResponse,
)
from mini_deer_agent.skills import (
    ManagedSkillRecord,
    SkillDetailRecord,
    SkillDraftPayload,
    SkillDraftRecord,
    SkillManagementService,
    SkillCatalogError,
    UserSkillManager,
    UserSkillRecord,
)


router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


def _response(record: UserSkillRecord | ManagedSkillRecord) -> UserSkillResponse:
    source = record.source if isinstance(record, ManagedSkillRecord) else "user"
    editable = record.editable if isinstance(record, ManagedSkillRecord) else True
    modified_at = record.modified_at if isinstance(record, ManagedSkillRecord) else ""
    check_status = (
        record.check_status if isinstance(record, ManagedSkillRecord) else "valid"
    )
    return UserSkillResponse(
        name=record.name,
        description=record.description,
        source=source,
        enabled=record.enabled,
        editable=editable,
        allowed_tools=(
            list(record.allowed_tools) if record.allowed_tools is not None else None
        ),
        resource_paths=list(record.resource_paths),
        resource_count=len(record.resource_paths),
        modified_at=modified_at,
        check_status=check_status,
    )


def _invalid_skill(exc: Exception) -> HTTPException:
    message = str(exc)
    if "revision conflict" in message:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "skill_revision_conflict", "message": message},
        )
    if "does not exist" in message or "is not installed" in message:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "skill_not_found", "message": message},
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"code": "invalid_user_skill", "message": str(exc)},
    )


@router.get("/agent-settings", response_model=SkillAgentSettingsResponse)
def get_skill_agent_settings(
    service: Annotated[SkillManagementService, Depends(get_skill_management_service)],
) -> SkillAgentSettingsResponse:
    try:
        current = service.agent_settings()
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc
    return SkillAgentSettingsResponse(
        creation_enabled=current.creation_enabled,
        revision=current.revision,
    )


@router.put("/agent-settings", response_model=SkillAgentSettingsResponse)
def update_skill_agent_settings(
    request: SkillAgentSettingsUpdateRequest,
    service: Annotated[SkillManagementService, Depends(get_skill_management_service)],
) -> SkillAgentSettingsResponse:
    try:
        updated = service.update_agent_settings(
            creation_enabled=request.creation_enabled,
            expected_revision=request.revision,
        )
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc
    return SkillAgentSettingsResponse(
        creation_enabled=updated.creation_enabled,
        revision=updated.revision,
    )


@router.get("", response_model=UserSkillListResponse)
def list_skills(
    manager: Annotated[UserSkillManager, Depends(get_user_skill_manager)],
) -> UserSkillListResponse:
    try:
        records = manager.list_all()
    except SkillCatalogError as exc:
        raise _invalid_skill(exc) from exc
    return UserSkillListResponse(
        skills=[_response(record) for record in records],
        revision=manager.revision,
    )


@router.post("/install", response_model=UserSkillResponse, status_code=201)
def install_user_skill(
    request: UserSkillInstallRequest,
    manager: Annotated[UserSkillManager, Depends(get_user_skill_manager)],
) -> UserSkillResponse:
    try:
        return _response(
            manager.install(
                Path(request.source_path),
                enabled=request.enabled,
                expected_revision=request.revision,
            )
        )
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc


def _draft_payload(request: SkillDraftWriteRequest) -> SkillDraftPayload:
    return SkillDraftPayload(
        name=request.name,
        description=request.description,
        instructions=request.instructions,
        allowed_tools=(
            tuple(request.allowed_tools) if request.allowed_tools is not None else None
        ),
        resources=tuple((resource.path, resource.content) for resource in request.resources),
    )


def _draft_response(record: SkillDraftRecord) -> SkillDraftResponse:
    return SkillDraftResponse(
        draft_id=record.draft_id,
        revision=record.revision,
        name=record.payload.name,
        description=record.payload.description,
        instructions=record.payload.instructions,
        allowed_tools=(
            list(record.payload.allowed_tools)
            if record.payload.allowed_tools is not None
            else None
        ),
        resources=[
            SkillResourceRequest(path=path, content=content)
            for path, content in record.payload.resources
        ],
        author=record.author,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _detail_response(record: SkillDetailRecord) -> SkillDetailResponse:
    return SkillDetailResponse(
        name=record.name,
        description=record.description,
        source=record.source,
        editable=record.editable,
        enabled=record.enabled,
        allowed_tools=(
            list(record.allowed_tools) if record.allowed_tools is not None else None
        ),
        instructions=record.instructions,
        resources=[
            SkillResourceRequest(path=path, content=content)
            for path, content in record.resources
        ],
        revision=record.revision,
    )


@router.post("/drafts", response_model=SkillDraftResponse, status_code=201)
def create_skill_draft(
    request: SkillDraftWriteRequest,
    service: Annotated[SkillManagementService, Depends(get_skill_management_service)],
) -> SkillDraftResponse:
    try:
        return _draft_response(
            service.create_draft(_draft_payload(request), author="user")
        )
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc


@router.get("/drafts", response_model=SkillDraftListResponse)
def list_skill_drafts(
    service: Annotated[SkillManagementService, Depends(get_skill_management_service)],
) -> SkillDraftListResponse:
    try:
        return SkillDraftListResponse(
            drafts=[_draft_response(item) for item in service.list_drafts()]
        )
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc


@router.get("/recoverable", response_model=RecoverableSkillListResponse)
def list_recoverable_skills(
    service: Annotated[SkillManagementService, Depends(get_skill_management_service)],
) -> RecoverableSkillListResponse:
    try:
        return RecoverableSkillListResponse(
            skills=[
                RecoverableSkillResponse(
                    name=item.name,
                    history_id=item.history_id,
                    description=item.description,
                    source=item.source,
                    version=item.version,
                    deleted_at=item.deleted_at,
                )
                for item in service.list_recoverable()
            ]
        )
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc


@router.put("/drafts/{draft_id}", response_model=SkillDraftResponse)
def update_skill_draft(
    draft_id: str,
    request: SkillDraftWriteRequest,
    service: Annotated[SkillManagementService, Depends(get_skill_management_service)],
) -> SkillDraftResponse:
    if request.revision is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "missing_revision", "message": "revision is required"},
        )
    try:
        return _draft_response(
            service.update_draft(
                draft_id,
                _draft_payload(request),
                expected_revision=request.revision,
            )
        )
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc


@router.post("/drafts/{draft_id}/check", response_model=SkillCheckResponse)
def check_skill_draft(
    draft_id: str,
    service: Annotated[SkillManagementService, Depends(get_skill_management_service)],
) -> SkillCheckResponse:
    try:
        result = service.check_draft(draft_id)
        return SkillCheckResponse(
            valid=result.valid,
            errors=list(result.errors),
            warnings=list(result.warnings),
            content_hash=result.content_hash,
        )
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc


@router.post("/drafts/{draft_id}/install", response_model=SkillDetailResponse)
def install_skill_draft(
    draft_id: str,
    request: SkillDraftInstallRequest,
    service: Annotated[SkillManagementService, Depends(get_skill_management_service)],
) -> SkillDetailResponse:
    try:
        return _detail_response(
            service.install_draft(
                draft_id,
                expected_revision=request.revision,
                expected_settings_revision=request.settings_revision,
                enabled=request.enabled,
                author="user",
            )
        )
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc


@router.post(
    "/install-authorizations",
    response_model=SkillInstallAuthorizationResponse,
    status_code=201,
)
def create_skill_install_authorization(
    request: SkillInstallAuthorizationRequest,
    service: Annotated[SkillManagementService, Depends(get_skill_management_service)],
) -> SkillInstallAuthorizationResponse:
    """由设置页显式授予当前 Skill 创作任务一次自动安装机会。"""
    try:
        authorization = service.authorize_automatic_install(
            thread_id=request.thread_id,
            expected_name=request.expected_name,
            requirement=request.requirement,
        )
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc
    return SkillInstallAuthorizationResponse(
        authorization_token=authorization.token,
        thread_id=authorization.thread_id,
        expected_name=authorization.expected_name,
        requirement_hash=authorization.requirement_hash,
        created_at=authorization.created_at,
        expires_at=authorization.expires_at,
    )


@router.post("/import", response_model=SkillDraftResponse, status_code=201)
async def import_skill_archive(
    request: Request,
    service: Annotated[SkillManagementService, Depends(get_skill_management_service)],
) -> SkillDraftResponse:
    try:
        return _draft_response(
            service.create_draft_from_archive(await request.body())
        )
    except (OSError, SkillCatalogError, ValueError) as exc:
        raise _invalid_skill(exc) from exc


@router.get("/{name}/history", response_model=SkillHistoryListResponse)
def list_skill_history(
    name: str,
    service: Annotated[SkillManagementService, Depends(get_skill_management_service)],
) -> SkillHistoryListResponse:
    try:
        return SkillHistoryListResponse(
            history=[
                SkillHistoryResponse(
                    history_id=item.history_id,
                    skill_name=item.skill_name,
                    action=item.action,
                    author=item.author,
                    created_at=item.created_at,
                    description=item.description,
                    allowed_tools=(
                        list(item.allowed_tools)
                        if item.allowed_tools is not None
                        else None
                    ),
                    version=item.version,
                )
                for item in service.list_history(name)
            ]
        )
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc


@router.get("/{name}/history/{history_id}", response_model=SkillDetailResponse)
def get_skill_history_detail(
    name: str,
    history_id: str,
    service: Annotated[SkillManagementService, Depends(get_skill_management_service)],
) -> SkillDetailResponse:
    try:
        return _detail_response(service.get_history_detail(name, history_id))
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc


@router.post("/{name}/rollback", response_model=SkillDetailResponse)
def rollback_skill(
    name: str,
    request: SkillRollbackRequest,
    service: Annotated[SkillManagementService, Depends(get_skill_management_service)],
) -> SkillDetailResponse:
    try:
        return _detail_response(
            service.rollback(
                name,
                request.history_id,
                author="user",
                expected_revision=request.revision,
            )
        )
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc


@router.get("/{name}", response_model=SkillDetailResponse)
def get_skill_detail(
    name: str,
    service: Annotated[SkillManagementService, Depends(get_skill_management_service)],
) -> SkillDetailResponse:
    try:
        return _detail_response(service.get_detail(name))
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc

@router.patch("/{name}", response_model=UserSkillResponse)
def set_user_skill_enabled(
    name: str,
    request: UserSkillEnabledRequest,
    manager: Annotated[UserSkillManager, Depends(get_user_skill_manager)],
) -> UserSkillResponse:
    try:
        return _response(
            manager.set_managed_enabled(
                name,
                request.enabled,
                expected_revision=request.revision,
            )
        )
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc


@router.delete("/{name}", status_code=204)
def delete_skill(
    name: str,
    service: Annotated[SkillManagementService, Depends(get_skill_management_service)],
    revision: Annotated[int, Query(ge=0)],
) -> Response:
    try:
        service.delete(name, expected_revision=revision)
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc
    return Response(status_code=204)
