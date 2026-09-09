"""应用级 Skill 清单与本地用户 Skill 管理接口的数据契约。"""

from typing import Literal

from pydantic import BaseModel, Field


class UserSkillResponse(BaseModel):
    name: str
    description: str
    source: Literal["builtin", "user", "market"]
    enabled: bool
    editable: bool
    allowed_tools: list[str] | None
    resource_paths: list[str]
    resource_count: int
    modified_at: str
    check_status: Literal["valid"]


class UserSkillListResponse(BaseModel):
    skills: list[UserSkillResponse]
    revision: int


class UserSkillInstallRequest(BaseModel):
    source_path: str = Field(min_length=1, max_length=4096)
    enabled: bool = True
    revision: int = Field(ge=0)


class UserSkillEnabledRequest(BaseModel):
    enabled: bool
    revision: int = Field(ge=0)


class SkillResourceRequest(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=65536)


class SkillDraftWriteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=500)
    instructions: str = Field(min_length=1, max_length=32768)
    allowed_tools: list[str] | None = None
    resources: list[SkillResourceRequest] = Field(default_factory=list, max_length=16)
    revision: int | None = Field(default=None, ge=1)


class SkillDraftInstallRequest(BaseModel):
    revision: int = Field(ge=1)
    settings_revision: int = Field(ge=0)
    enabled: bool = True


class SkillInstallAuthorizationRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=128)
    expected_name: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    requirement: str = Field(min_length=1, max_length=4000)


class SkillInstallAuthorizationResponse(BaseModel):
    authorization_token: str
    thread_id: str
    expected_name: str
    requirement_hash: str
    created_at: str
    expires_at: str


class SkillAgentSettingsResponse(BaseModel):
    creation_enabled: bool
    revision: int


class SkillAgentSettingsUpdateRequest(BaseModel):
    creation_enabled: bool
    revision: int = Field(ge=0)


class SkillDraftResponse(BaseModel):
    draft_id: str
    revision: int
    name: str
    description: str
    instructions: str
    allowed_tools: list[str] | None
    resources: list[SkillResourceRequest]
    author: str
    created_at: str
    updated_at: str


class SkillDraftListResponse(BaseModel):
    drafts: list[SkillDraftResponse]


class SkillCheckResponse(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]
    content_hash: str | None


class SkillDetailResponse(BaseModel):
    name: str
    description: str
    source: Literal["builtin", "user", "market"]
    editable: bool
    enabled: bool
    allowed_tools: list[str] | None
    instructions: str
    resources: list[SkillResourceRequest]
    revision: int


class SkillHistoryResponse(BaseModel):
    history_id: str
    skill_name: str
    action: Literal["install", "update", "delete", "rollback", "import"]
    author: str
    created_at: str
    description: str
    allowed_tools: list[str] | None
    version: str | None = None


class SkillHistoryListResponse(BaseModel):
    history: list[SkillHistoryResponse]


class RecoverableSkillResponse(BaseModel):
    name: str
    history_id: str
    description: str
    source: Literal["user", "market"]
    version: str | None
    deleted_at: str


class RecoverableSkillListResponse(BaseModel):
    skills: list[RecoverableSkillResponse]


class SkillRollbackRequest(BaseModel):
    history_id: str
    revision: int = Field(ge=0)
