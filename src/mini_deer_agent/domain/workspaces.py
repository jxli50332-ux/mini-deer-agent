"""定义独立于会话的项目登记事实与文件访问范围。"""

from dataclasses import dataclass
from typing import Literal


type ProjectStatus = Literal["available", "missing", "unavailable", "changed"]
type FileAccessSource = Literal["project", "explicit", "workspace"]
type FileAccessTargetKind = Literal["directory", "file", "roots"]


class ProjectError(ValueError):
    """携带稳定错误码和安全说明，不向 HTTP 泄露底层异常或路径详情。"""

    def __init__(self, code: str, message: str) -> None:
        """保存可复用的领域错误；调用方自行决定传输层状态码。"""
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    """保存项目根和登记时的目录身份；Project 不依赖 Thread 生命周期。"""

    project_id: str
    name: str
    root_path: str
    root_identity: str
    status: ProjectStatus
    status_reason: str | None
    created_at: str
    updated_at: str
    access_mode: Literal["read_write"] = "read_write"


@dataclass(frozen=True, slots=True)
class FileAccessRoot:
    """保存普通 Thread 可使用的一个允许根及其虚拟路径别名。"""

    alias: str
    path: str
    identity: str


@dataclass(frozen=True, slots=True)
class FileAccessScope:
    """冻结一次文件访问目标；Project 路径默认保持相对。"""

    source: FileAccessSource
    target_path: str
    target_identity: str
    target_kind: FileAccessTargetKind
    project_id: str | None = None
    access_mode: Literal["read_write"] = "read_write"
    roots: tuple[FileAccessRoot, ...] = ()
