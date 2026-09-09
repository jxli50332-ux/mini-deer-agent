"""Skill 市场的统一非执行元数据契约。"""

from typing import Literal

from pydantic import BaseModel, Field


class SkillMarketProviderResponse(BaseModel):
    name: str
    available: bool
    last_synced_at: str | None
    cached: bool


class SkillMarketItemResponse(BaseModel):
    provider: str
    remote_id: str
    name: str
    version: str | None
    description: str
    publisher: str
    license: str | None
    tags: list[str]
    source_url: str | None
    canonical_url: str
    required_tools: list[str]
    runtime_requirements: list[str]
    download_ref: str
    content_hash: str | None
    scan_status: str
    changelog: str | None
    published_at: str | None
    compatible: bool
    compatibility_reason: str
    file_paths: list[str]
    package_size: int | None
    file_hashes: list[tuple[str, str]]


class SkillMarketCatalogResponse(BaseModel):
    items: list[SkillMarketItemResponse]
    synced_at: str | None
    from_cache: bool


class SkillMarketProvidersResponse(BaseModel):
    providers: list[SkillMarketProviderResponse]


class SkillMarketPreviewRequest(BaseModel):
    action: Literal["install", "update"]
    version: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool = True


class SkillMarketVersionResponse(BaseModel):
    version: str
    changelog: str | None
    published_at: str | None


class SkillMarketVersionsResponse(BaseModel):
    versions: list[SkillMarketVersionResponse]


class SkillMarketApplyRequest(BaseModel):
    confirmation_token: str = Field(min_length=32, max_length=128)


class SkillMarketChangePreviewResponse(BaseModel):
    confirmation_token: str
    action: Literal["install", "update"]
    provider: str
    remote_id: str
    name: str
    current_version: str | None
    target_version: str | None
    content_hash: str
    enabled_after: bool
    allowed_tools_before: list[str] | None
    allowed_tools_after: list[str] | None
    added_tools: list[str]
    removed_tools: list[str]
    permission_changed: bool
    description_changed: bool
    instructions_changed: bool
    resources_changed: bool
    risk_warnings: list[str]
    expires_at: str
