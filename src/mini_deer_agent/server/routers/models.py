"""暴露模型 Profile、安全连接检查和应用级默认选择。"""

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from mini_deer_agent.llms import (
    ModelConfigurationService,
    ModelProfileConflictError,
    ModelProfileError,
    ModelSelectionConflictError,
)
from mini_deer_agent.server.dependencies import get_model_configuration_service
from mini_deer_agent.server.schemas.models import (
    ModelListResponse,
    ModelProbeResponse,
    ModelProfileCreateRequest,
    ModelProfileCreateResponse,
    ModelProfileResponse,
    ModelSelectionResponse,
    ModelSelectionUpdateRequest,
)


models_router = APIRouter(prefix="/api/v1/models", tags=["models"])
settings_router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


def _selection(value: Any) -> ModelSelectionResponse:
    return ModelSelectionResponse(
        primary_model=value.primary_model,
        goal_model=value.goal_model,
        revision=value.revision,
    )


@models_router.get("", response_model=ModelListResponse)
def list_models(
    service: Annotated[
        ModelConfigurationService, Depends(get_model_configuration_service)
    ],
) -> ModelListResponse:
    profiles, revision = service.profiles_snapshot()
    return ModelListResponse(
        models=[ModelProfileResponse(**asdict(item)) for item in profiles],
        profile_revision=revision,
    )


@models_router.post("", response_model=ModelProfileCreateResponse, status_code=201)
def create_model_profile(
    request: ModelProfileCreateRequest,
    service: Annotated[
        ModelConfigurationService, Depends(get_model_configuration_service)
    ],
) -> ModelProfileCreateResponse:
    """新增可信模型 Profile；可选密钥只写入本机凭据存储。"""
    try:
        profile, revision = service.add_profile(
            name=request.name,
            display_name=request.display_name,
            provider=request.provider,
            model=request.model,
            base_url=request.base_url,
            api_key_env=request.api_key_env,
            api_key=request.api_key,
            supports_tools=request.supports_tools,
            supports_reasoning=request.supports_reasoning,
            expected_revision=request.profile_revision,
        )
    except ModelProfileConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "model_profile_conflict", "message": str(exc)},
        ) from exc
    except ModelProfileError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_model_profile", "message": str(exc)},
        ) from exc
    return ModelProfileCreateResponse(
        model=ModelProfileResponse(**asdict(profile)),
        profile_revision=revision,
    )


@models_router.post("/{name}/probe", response_model=ModelProbeResponse)
async def probe_model(
    name: str,
    service: Annotated[
        ModelConfigurationService, Depends(get_model_configuration_service)
    ],
) -> ModelProbeResponse:
    try:
        result = await service.probe(name)
    except ModelProfileError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "model_not_found", "message": str(exc)},
        ) from exc
    return ModelProbeResponse(
        ok=result.ok, category=result.category, message=result.message
    )


@settings_router.get("/model-selection", response_model=ModelSelectionResponse)
def get_model_selection(
    service: Annotated[
        ModelConfigurationService, Depends(get_model_configuration_service)
    ],
) -> ModelSelectionResponse:
    try:
        return _selection(service.selection())
    except ModelProfileError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_model_selection", "message": str(exc)}) from exc


@settings_router.put("/model-selection", response_model=ModelSelectionResponse)
def update_model_selection(
    request: ModelSelectionUpdateRequest,
    service: Annotated[
        ModelConfigurationService, Depends(get_model_configuration_service)
    ],
) -> ModelSelectionResponse:
    try:
        return _selection(
            service.update_selection(
                request.primary_model,
                request.goal_model,
                expected_revision=request.revision,
            )
        )
    except ModelSelectionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "model_selection_conflict", "message": str(exc)},
        ) from exc
    except ModelProfileError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_model_selection", "message": str(exc)},
        ) from exc


__all__ = ["models_router", "settings_router"]
