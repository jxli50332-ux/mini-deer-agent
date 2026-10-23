"""受控读取 UTF-8 源码；原文件保持只读，正文与响应均有预算。"""

import hashlib
import os
import stat
from pathlib import Path
from mini_deer_agent.domain.workspaces import ProjectError
from mini_deer_agent.workspace.directory import ignored, valid_name
from mini_deer_agent.workspace.paths import _inspect_directory

MAX_BYTES = 2 * 1024 * 1024
MAX_CHARS = 32768


def _signature(value: os.stat_result) -> tuple:
    """同时检查文件身份和版本，检测读取期间的常见替换或编辑。"""
    # Windows 的路径 stat 与句柄 fstat 对 ctime 语义不同，不能跨接口比较。
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns if os.name != "nt" else 0,
    )


def read_project_snapshot(root: Path, path: str) -> tuple[dict, bytes]:
    """读取受目录、文件身份和大小约束的原始快照，供源码与文件预览共用。"""
    parts = path.split("/")
    if (
        len(path) > 2048
        or len(parts) > 64
        or any(not valid_name(p) or ignored(p) for p in parts)
    ):
        raise ProjectError("project_path_invalid", "文件路径无效或已被忽略。")
    file = root.joinpath(*parts)
    parent = _inspect_directory(file.parent)
    if not parent.path.is_relative_to(root):
        raise ProjectError("project_path_invalid", "文件超出项目范围。")
    try:
        before = file.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or getattr(before, "st_file_attributes", 0) & 0x400
        ):
            raise ProjectError(
                "project_file_unsupported", "仅支持普通文件，不能读取链接或目录。"
            )
        result = {
            "path": path,
            "size_bytes": before.st_size,
            "status": "text",
            "lines": [],
            "start_line": 1,
            "next_line": None,
            "total_lines": None,
            "revision": None,
        }
        if before.st_size > MAX_BYTES:
            return {**result, "status": "too_large"}, b""
        # POSIX 可用时拒绝最终链接并避免 FIFO 阻塞；跨平台仍校验打开句柄身份。
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        fd = os.open(file, flags)
        with os.fdopen(fd, "rb") as stream:
            if _signature(os.fstat(stream.fileno())) != _signature(before):
                raise ProjectError("project_file_changed", "文件已变化，请重新读取。")
            data = stream.read(MAX_BYTES + 1)
            after = os.fstat(stream.fileno())
        if (
            _signature(after) != _signature(before)
            or _signature(file.lstat()) != _signature(before)
            or _inspect_directory(file.parent).identity != parent.identity
        ):
            raise ProjectError("project_file_changed", "文件已变化，请重新读取。")
    except OSError:
        raise ProjectError(
            "project_file_unavailable", "文件不存在或当前无法读取。"
        ) from None
    if len(data) > MAX_BYTES:
        return {**result, "status": "too_large"}, b""
    return result, data


def decode_project_text(data: bytes) -> tuple[str, str]:
    """只接受 UTF-8 文本；扩展名不能把二进制内容伪装成文本。"""
    if b"\x00" in data:
        return "binary", ""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "unsupported_encoding", ""
    if any(ord(c) < 32 and c not in "\t\r\n" for c in text):
        return "binary", ""
    return "text", text


def read_project_file(
    root: Path, path: str, *, start_line: int = 1, limit: int = 200
) -> dict:
    """按行和字符预算投影同一只读快照，保留既有工具协议。"""
    if not 1 <= start_line <= 1000000 or not 1 <= limit <= 500:
        raise ProjectError("project_range_invalid", "读取行范围无效。")
    result, data = read_project_snapshot(root, path)
    result["start_line"] = start_line
    if result["status"] != "text":
        return result
    status, text = decode_project_text(data)
    if status != "text":
        return {**result, "status": status}
    # 仅把 CRLF/CR 视为源码换行，避免 Unicode 段落字符改变编辑器行号。
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n") if text else []
    if lines and lines[-1] == "":
        lines.pop()
    result.update(total_lines=len(lines), revision=hashlib.sha256(data).hexdigest())
    if start_line > max(1, len(lines)):
        raise ProjectError("project_range_invalid", "起始行超过文件行数。")
    selected = []
    used = 0
    for line in lines[start_line - 1 : start_line - 1 + limit]:
        if used + len(line) + 1 > MAX_CHARS:
            if not selected:
                return {**result, "status": "line_too_long"}
            break
        selected.append(line)
        used += len(line) + 1
    next_line = start_line + len(selected)
    return {
        **result,
        "lines": selected,
        "next_line": next_line if next_line <= len(lines) else None,
    }
