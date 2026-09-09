"""本地用户 Skill 管理接口的数据契约。"""

from pydantic import BaseModel, Field


class UserSkillResponse(BaseModel):
    name: str
    description: str
    enabled: bool
    allowed_tools: list[str] | None
    resource_paths: list[str]


class UserSkillListResponse(BaseModel):
    skills: list[UserSkillResponse]


class UserSkillInstallRequest(BaseModel):
    source_path: str = Field(min_length=1, max_length=4096)
    enabled: bool = True


class UserSkillEnabledRequest(BaseModel):
    enabled: bool
