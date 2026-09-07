"""项目登记只接收名称与根路径，权限和目录身份不接受客户端赋值。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID

from mini_deer_agent.domain.workspaces import ProjectStatus


class ProjectRegistrationRequest(BaseModel):
    """接收有界管理输入；未知字段失败关闭。"""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    root_path: str = Field(min_length=1, max_length=4096)


class ProjectResponse(BaseModel):
    """公开持久身份与最近核验状态，不公开底层目录身份或数据库位置。"""

    model_config = ConfigDict(from_attributes=True)
    project_id: str
    name: str
    root_path: str
    access_mode: Literal["read_write"]
    status: ProjectStatus
    status_reason: str | None
    created_at: str
    updated_at: str


class ProjectListResponse(BaseModel):
    """返回有界列表和明确的续页位置，不静默截断登记记录。"""

    items: list[ProjectResponse]
    next_offset: int | None


class ProjectThreadCreateRequest(BaseModel):
    """客户端提供稳定 Thread ID，使连接中断后的创建请求可以安全重试。"""

    model_config = ConfigDict(extra="forbid")
    thread_id: UUID


class ProjectDirectoryEntry(BaseModel):
    """只公开子项名字、相对路径与访问状态，不返回内容或链接目标。"""

    name: str
    path: str
    kind: Literal["directory", "file", "unknown"]
    status: Literal["available", "ignored", "unavailable"]
    reason: str | None


class ProjectDirectoryResponse(BaseModel):
    """单层有界目录结果；截断时不声称已经列出全部内容。"""

    project_id: str
    path: str
    items: list[ProjectDirectoryEntry]
    truncated: bool
    truncation_reason: Literal["entry_limit", "time_budget"] | None
    limit: int


class ProjectFileResponse(BaseModel):
    """返回只读文本片段与版本摘要；不支持的格式仅返回元数据和原因。"""

    project_id: str
    path: str
    size_bytes: int
    status: Literal[
        "text", "binary", "unsupported_encoding", "too_large", "line_too_long"
    ]
    lines: list[str]
    start_line: int
    next_line: int | None
    total_lines: int | None
    revision: str | None
