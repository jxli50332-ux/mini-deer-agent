"""只列项目目录元数据；不读取文件正文，不递归或跟随链接。"""

import os
import stat
from pathlib import Path
from time import monotonic

from mini_deer_agent.domain.workspaces import ProjectError
from mini_deer_agent.workspace.paths import _inspect_directory, _is_reserved

_IGNORED = {
    ".git",
    ".ssh",
    ".aws",
    ".azure",
    ".kube",
    ".gnupg",
    ".codex",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    ".next",
}


def ignored(name: str) -> bool:
    """固定忽略策略覆盖凭据与产物；尚不解析项目自定义 gitignore。"""
    lower = name.casefold()
    return (
        lower in _IGNORED
        or lower == ".env"
        or (lower.startswith(".env.") and lower not in {".env.example", ".env.sample"})
        or lower.endswith(
            (".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite-wal", ".sqlite-shm")
        )
        or lower.startswith(("id_rsa", "id_ed25519"))
    )


def valid_name(name: str) -> bool:
    """统一拒绝 Windows 别名，即便服务运行于其他系统也保持协议一致。"""
    return (
        bool(name)
        and name not in {".", ".."}
        and not (
            any(ord(c) < 32 or c in ':<>"|?*\\/' for c in name)
            or name.endswith((" ", "."))
            or _is_reserved(name)
        )
    )


def list_directory(root: Path, path: str, *, limit: int = 200) -> dict:
    """枚举至多 limit 个直接子项，返回明确截断；校验前后目录身份。"""
    parts = path.split("/") if path else []
    if (
        len(path) > 2048
        or len(parts) > 64
        or not 1 <= limit <= 500
        or any(not valid_name(part) or ignored(part) for part in parts)
    ):
        raise ProjectError("project_path_invalid", "目录路径无效或已被忽略。")
    directory = root.joinpath(*parts)
    before = _inspect_directory(directory)
    if not before.path.is_relative_to(root):
        raise ProjectError("project_path_invalid", "目录超出项目范围。")
    items = []
    reason = None
    deadline = monotonic() + 1.0
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if len(items) >= limit or monotonic() >= deadline:
                    reason = "entry_limit" if len(items) >= limit else "time_budget"
                    break
                name = entry.name
                status, kind, detail = "available", "unknown", None
                if ignored(name) or not valid_name(name):
                    status, detail = "ignored", "policy"
                else:
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                        if (
                            stat.S_ISLNK(metadata.st_mode)
                            or getattr(metadata, "st_file_attributes", 0) & 0x400
                        ):
                            status, detail = "unavailable", "link"
                        elif stat.S_ISDIR(metadata.st_mode):
                            kind = "directory"
                        elif stat.S_ISREG(metadata.st_mode):
                            kind = "file"
                        else:
                            status, detail = "unavailable", "unsupported_type"
                    except OSError:
                        status, detail = "unavailable", "metadata_unavailable"
                items.append(
                    {
                        "name": name,
                        "path": "/".join([*parts, name]),
                        "kind": kind,
                        "status": status,
                        "reason": detail,
                    }
                )
        if _inspect_directory(directory).identity != before.identity:
            raise ProjectError("project_directory_changed", "目录已变化，请刷新重试。")
    except OSError:
        raise ProjectError(
            "project_directory_unavailable", "目录当前无法列出。"
        ) from None
    items.sort(key=lambda item: (item["kind"] != "directory", item["name"].casefold()))
    return {
        "path": path,
        "items": items,
        "truncated": reason is not None,
        "truncation_reason": reason,
        "limit": limit,
    }
