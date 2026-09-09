"""管理受管目录中的本地用户 Skill，不提供远程下载或生成能力。"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from mini_deer_agent.server.dependencies import get_user_skill_manager
from mini_deer_agent.server.schemas import (
    UserSkillEnabledRequest,
    UserSkillInstallRequest,
    UserSkillListResponse,
    UserSkillResponse,
)
from mini_deer_agent.skills import SkillCatalogError, UserSkillManager, UserSkillRecord


router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


def _response(record: UserSkillRecord) -> UserSkillResponse:
    return UserSkillResponse(
        name=record.name,
        description=record.description,
        enabled=record.enabled,
        allowed_tools=(
            list(record.allowed_tools) if record.allowed_tools is not None else None
        ),
        resource_paths=list(record.resource_paths),
    )


def _invalid_skill(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"code": "invalid_user_skill", "message": str(exc)},
    )


@router.get("", response_model=UserSkillListResponse)
def list_user_skills(
    manager: Annotated[UserSkillManager, Depends(get_user_skill_manager)],
) -> UserSkillListResponse:
    try:
        records = manager.list()
    except SkillCatalogError as exc:
        raise _invalid_skill(exc) from exc
    return UserSkillListResponse(skills=[_response(record) for record in records])


@router.post("/install", response_model=UserSkillResponse, status_code=201)
def install_user_skill(
    request: UserSkillInstallRequest,
    manager: Annotated[UserSkillManager, Depends(get_user_skill_manager)],
) -> UserSkillResponse:
    try:
        return _response(
            manager.install(Path(request.source_path), enabled=request.enabled)
        )
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc

@router.patch("/{name}", response_model=UserSkillResponse)
def set_user_skill_enabled(
    name: str,
    request: UserSkillEnabledRequest,
    manager: Annotated[UserSkillManager, Depends(get_user_skill_manager)],
) -> UserSkillResponse:
    try:
        return _response(manager.set_enabled(name, request.enabled))
    except (OSError, SkillCatalogError) as exc:
        raise _invalid_skill(exc) from exc
