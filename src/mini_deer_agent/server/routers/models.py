"""暴露模型 Profile、安全连接检查和应用级默认选择。"""

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from mini_deer_agent.llms import (
    ModelConfigurationService,
    ModelProfileError,
    ModelSelectionConflictError,
)
from mini_deer_agent.server.dependencies import get_model_configuration_service
from mini_deer_agent.server.schemas.models import (
    ModelListResponse,
    ModelProbeResponse,
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
    return ModelListResponse(
        models=[ModelProfileResponse(**asdict(item)) for item in service.list_profiles()],
        profile_revision=service.catalog.revision,
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
