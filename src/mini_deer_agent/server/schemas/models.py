"""模型 Profile、连接检查与默认选择的非敏感 HTTP 契约。"""

from typing import Literal

from pydantic import BaseModel, Field


class ModelProfileResponse(BaseModel):
    name: str
    display_name: str
    provider: str
    model: str
    base_url: str | None
    api_key_env: str
    api_key_configured: bool
    supports_tools: bool
    supports_reasoning: bool
    source: Literal["environment", "file"]


class ModelListResponse(BaseModel):
    models: list[ModelProfileResponse]
    profile_revision: str


class ModelSelectionResponse(BaseModel):
    primary_model: str
    goal_model: str | None
    revision: int


class ModelSelectionUpdateRequest(BaseModel):
    primary_model: str = Field(min_length=1, max_length=64)
    goal_model: str | None = Field(default=None, min_length=1, max_length=64)
    revision: int = Field(ge=0)


class ModelProbeResponse(BaseModel):
    ok: bool
    category: Literal[
        "success", "missing_key", "authentication", "network", "capability", "unknown"
    ]
    message: str
