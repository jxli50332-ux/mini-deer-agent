"""远程 Skill 市场元数据查询；不允许模型直接安装。"""

from dataclasses import asdict
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from mini_deer_agent.server.dependencies import get_skill_marketplace_service
from mini_deer_agent.server.schemas.skill_market import (
    SkillMarketApplyRequest,
    SkillMarketCatalogResponse,
    SkillMarketChangePreviewResponse,
    SkillMarketItemResponse,
    SkillMarketPreviewRequest,
    SkillMarketProviderResponse,
    SkillMarketProvidersResponse,
    SkillMarketVersionResponse,
    SkillMarketVersionsResponse,
)
from mini_deer_agent.skills.marketplace import SkillMarketplaceService
from mini_deer_agent.server.schemas.skills import SkillDetailResponse, SkillResourceRequest
from mini_deer_agent.server.schemas.skills import SkillRollbackRequest


router = APIRouter(prefix="/api/v1/skill-market", tags=["skill-market"])


def _market_write_error(code: str, exc: Exception) -> HTTPException:
    message = str(exc)
    return HTTPException(
        status_code=409 if "revision conflict" in message else 422,
        detail={"code": "skill_revision_conflict" if "revision conflict" in message else code, "message": message},
    )


@router.get("/providers", response_model=SkillMarketProvidersResponse)
def list_providers(
    service: Annotated[SkillMarketplaceService, Depends(get_skill_marketplace_service)],
) -> SkillMarketProvidersResponse:
    return SkillMarketProvidersResponse(
        providers=[SkillMarketProviderResponse(**item) for item in service.providers()]
    )


@router.get("/catalog", response_model=SkillMarketCatalogResponse)
def search_catalog(
    service: Annotated[SkillMarketplaceService, Depends(get_skill_marketplace_service)],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    refresh: bool = False,
) -> SkillMarketCatalogResponse:
    try:
        items, synced_at, from_cache = service.search(q, refresh=refresh)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "skill_market_unavailable", "message": "Skill 市场暂时不可用，且没有可用缓存。"},
        ) from exc
    return SkillMarketCatalogResponse(
        items=[SkillMarketItemResponse(**asdict(item)) for item in items],
        synced_at=synced_at,
        from_cache=from_cache,
    )


@router.post("/refresh", response_model=SkillMarketCatalogResponse)
def refresh_catalog(
    service: Annotated[SkillMarketplaceService, Depends(get_skill_marketplace_service)],
    q: Annotated[str, Query(min_length=1, max_length=200)],
) -> SkillMarketCatalogResponse:
    return search_catalog(service=service, q=q, refresh=True)


@router.get(
    "/items/{provider}/{owner}/{slug}", response_model=SkillMarketItemResponse
)
def get_market_item(
    provider: str,
    owner: str,
    slug: str,
    service: Annotated[SkillMarketplaceService, Depends(get_skill_marketplace_service)],
) -> SkillMarketItemResponse:
    try:
        item = service.get_fresh_item(provider, f"{owner}/{slug}")
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "market_skill_not_found", "message": str(exc)},
        ) from exc
    return SkillMarketItemResponse(**asdict(item))


@router.get(
    "/items/{provider}/{owner}/{slug}/versions",
    response_model=SkillMarketVersionsResponse,
)
def list_market_versions(
    provider: str,
    owner: str,
    slug: str,
    service: Annotated[SkillMarketplaceService, Depends(get_skill_marketplace_service)],
) -> SkillMarketVersionsResponse:
    try:
        versions = service.list_versions(provider, f"{owner}/{slug}")
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "market_skill_versions_failed", "message": str(exc)},
        ) from exc
    return SkillMarketVersionsResponse(
        versions=[SkillMarketVersionResponse(**asdict(item)) for item in versions]
    )


@router.post(
    "/items/{provider}/{owner}/{slug}/preview",
    response_model=SkillMarketChangePreviewResponse,
)
def preview_market_change(
    provider: str,
    owner: str,
    slug: str,
    request: SkillMarketPreviewRequest,
    service: Annotated[SkillMarketplaceService, Depends(get_skill_marketplace_service)],
) -> SkillMarketChangePreviewResponse:
    try:
        preview = service.preview_change(
            provider,
            f"{owner}/{slug}",
            action=request.action,
            version=request.version,
            enabled=request.enabled,
        )
    except (OSError, ValueError, RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "market_skill_preview_failed", "message": str(exc)},
        ) from exc
    return SkillMarketChangePreviewResponse(
        **{
            **asdict(preview),
            "allowed_tools_before": (
                list(preview.allowed_tools_before)
                if preview.allowed_tools_before is not None
                else None
            ),
            "allowed_tools_after": (
                list(preview.allowed_tools_after)
                if preview.allowed_tools_after is not None
                else None
            ),
            "added_tools": list(preview.added_tools),
            "removed_tools": list(preview.removed_tools),
            "risk_warnings": list(preview.risk_warnings),
        }
    )


@router.post("/items/{provider}/{owner}/{slug}/install", response_model=SkillDetailResponse)
def install_market_skill(
    provider: str,
    owner: str,
    slug: str,
    request: SkillMarketApplyRequest,
    service: Annotated[SkillMarketplaceService, Depends(get_skill_marketplace_service)],
) -> SkillDetailResponse:
    try:
        item = service.install(
            provider,
            f"{owner}/{slug}",
            confirmation_token=request.confirmation_token,
        )
    except (OSError, ValueError, RuntimeError, httpx.HTTPError) as exc:
        raise _market_write_error("market_skill_install_failed", exc) from exc
    return SkillDetailResponse(
        name=item.name,
        description=item.description,
        source=item.source,
        editable=item.editable,
        enabled=item.enabled,
        allowed_tools=list(item.allowed_tools) if item.allowed_tools is not None else None,
        instructions=item.instructions,
        resources=[SkillResourceRequest(path=path, content=content) for path, content in item.resources],
        revision=item.revision,
    )


@router.post("/items/{provider}/{owner}/{slug}/update", response_model=SkillDetailResponse)
def update_market_skill(
    provider: str,
    owner: str,
    slug: str,
    request: SkillMarketApplyRequest,
    service: Annotated[SkillMarketplaceService, Depends(get_skill_marketplace_service)],
) -> SkillDetailResponse:
    try:
        item = service.install(
            provider,
            f"{owner}/{slug}",
            replace_existing=True,
            confirmation_token=request.confirmation_token,
        )
    except (OSError, ValueError, RuntimeError, httpx.HTTPError) as exc:
        raise _market_write_error("market_skill_update_failed", exc) from exc
    return SkillDetailResponse(
        name=item.name,
        description=item.description,
        source=item.source,
        editable=item.editable,
        enabled=item.enabled,
        allowed_tools=list(item.allowed_tools) if item.allowed_tools is not None else None,
        instructions=item.instructions,
        resources=[SkillResourceRequest(path=path, content=content) for path, content in item.resources],
        revision=item.revision,
    )


@router.delete("/items/{provider}/{owner}/{slug}/installation", status_code=204)
def uninstall_market_skill(
    provider: str,
    owner: str,
    slug: str,
    revision: Annotated[int, Query(ge=0)],
    service: Annotated[SkillMarketplaceService, Depends(get_skill_marketplace_service)],
) -> None:
    try:
        service.uninstall(provider, f"{owner}/{slug}", expected_revision=revision)
    except (OSError, ValueError, RuntimeError) as exc:
        raise _market_write_error("market_skill_uninstall_failed", exc) from exc


@router.post("/items/{provider}/{owner}/{slug}/rollback", response_model=SkillDetailResponse)
def rollback_market_skill(
    provider: str,
    owner: str,
    slug: str,
    request: SkillRollbackRequest,
    service: Annotated[SkillMarketplaceService, Depends(get_skill_marketplace_service)],
) -> SkillDetailResponse:
    try:
        item = service.rollback(
            provider,
            f"{owner}/{slug}",
            request.history_id,
            expected_revision=request.revision,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        raise _market_write_error("market_skill_rollback_failed", exc) from exc
    return SkillDetailResponse(
        name=item.name, description=item.description, source=item.source,
        editable=item.editable, enabled=item.enabled,
        allowed_tools=list(item.allowed_tools) if item.allowed_tools is not None else None,
        instructions=item.instructions,
        resources=[SkillResourceRequest(path=path, content=content) for path, content in item.resources],
        revision=item.revision,
    )
