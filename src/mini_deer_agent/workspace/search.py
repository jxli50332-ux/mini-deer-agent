"""在已授权目录内有界查找文件名，不读取正文或跟随链接。"""

import os
import stat
from collections import deque
from pathlib import Path, PurePosixPath
from time import monotonic

from mini_deer_agent.domain.workspaces import ProjectError
from mini_deer_agent.workspace.directory import ignored, valid_name
from mini_deer_agent.workspace.files import _signature
from mini_deer_agent.workspace.paths import _inspect_directory

MAX_SCANNED_ENTRIES = 10_000
SEARCH_TIME_BUDGET_SECONDS = 1.0
MAX_SEARCH_FILES = 500
MAX_SEARCH_BYTES = 8 * 1024 * 1024
MAX_SEARCH_FILE_BYTES = 1024 * 1024
MAX_SEARCH_LINE_CHARS = 4_000
MAX_SEARCH_OUTPUT_CHARS = 32_768
LINE_SUMMARY_CHARS = 300


def _valid_pattern(pattern: str) -> bool:
    """只接受相对 glob；模式不能借路径语法改变搜索根。"""
    normalized = pattern.replace("\\", "/")
    return (
        bool(pattern)
        and len(pattern) <= 256
        and not normalized.startswith("/")
        and ".." not in normalized.split("/")
        and not any(ord(character) < 32 for character in pattern)
    )


def validate_glob_query(pattern: str, limit: int) -> None:
    """统一校验 glob 与结果预算，供目录和单文件 Scope 复用。"""
    if not _valid_pattern(pattern):
        raise ProjectError("file_glob_pattern_invalid", "文件匹配模式无效。")
    if not 1 <= limit <= 200:
        raise ProjectError("file_glob_limit_invalid", "文件匹配数量范围无效。")


def matches_glob_pattern(pattern: str, relative_path: str) -> bool:
    """让常用的 **/*.ext 同时匹配根目录和嵌套文件。"""
    path = PurePosixPath(relative_path)
    return path.match(pattern) or (
        pattern.startswith("**/") and path.match(pattern[3:])
    )


def glob_project_files(
    root: Path,
    path: str,
    pattern: str,
    *,
    limit: int = 100,
    time_budget_seconds: float = SEARCH_TIME_BUDGET_SECONDS,
    scan_limit: int = MAX_SCANNED_ENTRIES,
) -> dict:
    """从相对目录递归匹配普通文件，返回稳定路径和不完整原因。"""
    parts = path.split("/") if path else []
    if (
        len(path) > 2048
        or len(parts) > 64
        or any(not valid_name(part) or ignored(part) for part in parts)
    ):
        raise ProjectError("project_path_invalid", "搜索目录无效或已被忽略。")
    validate_glob_query(pattern, limit)

    search_root = root.joinpath(*parts)
    initial = _inspect_directory(search_root)
    if not initial.path.is_relative_to(root):
        raise ProjectError("project_path_invalid", "搜索目录超出文件范围。")

    matches: list[str] = []
    pending = [initial.path]
    scanned_entries = 0
    skipped_entries = False
    deadline = monotonic() + time_budget_seconds
    truncation_reason: str | None = None

    while pending:
        if monotonic() >= deadline:
            truncation_reason = "time_budget"
            break
        directory = pending.pop()
        before = _inspect_directory(directory)
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name.casefold())
        except OSError:
            skipped_entries = True
            continue
        if _inspect_directory(directory).identity != before.identity:
            raise ProjectError(
                "project_directory_changed", "目录已变化，请重新搜索。"
            )
        child_directories: list[Path] = []
        for entry in entries:
            scanned_entries += 1
            if scanned_entries > scan_limit:
                truncation_reason = "scan_limit"
                break
            if ignored(entry.name) or not valid_name(entry.name):
                continue
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError:
                skipped_entries = True
                continue
            if (
                stat.S_ISLNK(metadata.st_mode)
                or getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            ):
                continue
            entry_path = Path(entry.path)
            if stat.S_ISDIR(metadata.st_mode):
                child_directories.append(entry_path)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                continue
            relative_path = entry_path.relative_to(root).as_posix()
            pattern_path = entry_path.relative_to(initial.path).as_posix()
            if matches_glob_pattern(pattern, pattern_path):
                matches.append(relative_path)
                if len(matches) > limit:
                    matches.pop()
                    truncation_reason = "result_limit"
                    break
        if truncation_reason is not None:
            break
        # 栈逆序压入，保证实际扫描顺序与文件名排序一致。
        pending.extend(reversed(child_directories))

    if truncation_reason is None and skipped_entries:
        truncation_reason = "unavailable_entries"
    return {
        "path": path,
        "pattern": pattern,
        "matches": matches,
        "truncated": truncation_reason is not None,
        "truncation_reason": truncation_reason,
        "limit": limit,
        "scanned_entries": min(scanned_entries, scan_limit),
    }


def validate_content_query(
    query: str, file_pattern: str | None, limit: int
) -> None:
    """正文搜索只接受单行字面量；文件过滤继续沿用安全 glob。"""
    if (
        not query
        or not query.strip()
        or len(query) > 256
        or any(ord(character) < 32 for character in query)
    ):
        raise ProjectError("file_search_query_invalid", "文件搜索内容无效。")
    if file_pattern is not None:
        validate_glob_query(file_pattern, 200)
    if not 1 <= limit <= 200:
        raise ProjectError("file_search_limit_invalid", "文件搜索数量范围无效。")


def _line_summary(line: str, match_index: int) -> str:
    """限制单条证据正文，长行截取时保留命中位置。"""
    if len(line) <= LINE_SUMMARY_CHARS:
        return line
    content_budget = LINE_SUMMARY_CHARS - 2
    start = max(0, match_index - content_budget // 3)
    end = min(len(line), start + content_budget)
    start = max(0, end - content_budget)
    return f'{"…" if start else ""}{line[start:end]}{"…" if end < len(line) else ""}'


def _search_text_file(
    root: Path,
    relative_path: str,
    *,
    query: str,
    case_sensitive: bool,
    deadline: float,
    limit: int,
    file_limit: int,
    byte_budget: int,
    output_budget: int,
    state: dict,
) -> str | None:
    """安全读取一个已筛选文件一次，把匹配行加入全局有界状态。"""
    file = root.joinpath(*relative_path.split("/"))
    parent = _inspect_directory(file.parent)
    try:
        before = file.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or getattr(before, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            state["skipped_files"] += 1
            return None
        if before.st_size > MAX_SEARCH_FILE_BYTES:
            state["skipped_files"] += 1
            return None
        if state["scanned_files"] >= file_limit:
            return "file_limit"
        if state["scanned_bytes"] + before.st_size > byte_budget:
            return "byte_budget"
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        fd = os.open(file, flags)
        with os.fdopen(fd, "rb") as stream:
            if _signature(os.fstat(stream.fileno())) != _signature(before):
                raise ProjectError("project_file_changed", "文件已变化，请重新搜索。")
            data = stream.read(MAX_SEARCH_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
        if (
            _signature(after) != _signature(before)
            or _signature(file.lstat()) != _signature(before)
            or _inspect_directory(file.parent).identity != parent.identity
        ):
            raise ProjectError("project_file_changed", "文件已变化，请重新搜索。")
    except OSError:
        state["skipped_files"] += 1
        return None
    state["scanned_files"] += 1
    state["scanned_bytes"] += len(data)
    if len(data) > MAX_SEARCH_FILE_BYTES or b"\x00" in data:
        state["skipped_files"] += 1
        return None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        state["skipped_files"] += 1
        return None
    if any(ord(character) < 32 and character not in "\t\r\n" for character in text):
        state["skipped_files"] += 1
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n") if text else []
    if lines and lines[-1] == "":
        lines.pop()
    needle = query if case_sensitive else query.casefold()
    for line_number, line in enumerate(lines, start=1):
        if monotonic() >= deadline:
            return "time_budget"
        if len(line) > MAX_SEARCH_LINE_CHARS:
            state["skipped_lines"] += 1
            continue
        haystack = line if case_sensitive else line.casefold()
        match_index = haystack.find(needle)
        if match_index < 0:
            continue
        if len(state["matches"]) >= limit:
            return "result_limit"
        summary = _line_summary(line, match_index)
        output_size = len(relative_path) + len(summary) + 32
        if state["output_chars"] + output_size > output_budget:
            return "output_budget"
        state["matches"].append(
            {
                "path": relative_path,
                "line_number": line_number,
                "line": summary,
            }
        )
        state["output_chars"] += output_size
    return None


def search_project_files(
    root: Path,
    path: str,
    query: str,
    *,
    file_pattern: str | None = None,
    case_sensitive: bool = False,
    limit: int = 100,
    time_budget_seconds: float = SEARCH_TIME_BUDGET_SECONDS,
    scan_limit: int = MAX_SCANNED_ENTRIES,
    file_limit: int = MAX_SEARCH_FILES,
    byte_budget: int = MAX_SEARCH_BYTES,
    output_budget: int = MAX_SEARCH_OUTPUT_CHARS,
) -> dict:
    """在文件或目录中有界搜索字面量正文，返回路径、真实行号和摘要。"""
    parts = path.split("/") if path else []
    if (
        len(path) > 2048
        or len(parts) > 64
        or any(not valid_name(part) or ignored(part) for part in parts)
    ):
        raise ProjectError("project_path_invalid", "搜索路径无效或已被忽略。")
    validate_content_query(query, file_pattern, limit)

    target = root.joinpath(*parts)
    try:
        target_metadata = target.lstat()
    except OSError:
        raise ProjectError("project_path_invalid", "搜索路径不存在或无法访问。") from None
    if (
        stat.S_ISLNK(target_metadata.st_mode)
        or getattr(target_metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    ):
        raise ProjectError("project_path_invalid", "搜索路径不能是链接。")
    try:
        resolved_target = target.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ProjectError("project_path_invalid", "搜索路径不存在或无法访问。") from None
    if not resolved_target.is_relative_to(root):
        raise ProjectError("project_path_invalid", "搜索路径超出文件范围。")

    state = {
        "matches": [],
        "output_chars": 0,
        "skipped_files": 0,
        "skipped_lines": 0,
        "scanned_files": 0,
        "scanned_bytes": 0,
    }
    scanned_entries = 0
    deadline = monotonic() + time_budget_seconds
    truncation_reason: str | None = None

    if stat.S_ISREG(target_metadata.st_mode):
        parent = _inspect_directory(target.parent)
        if not parent.path.is_relative_to(root):
            raise ProjectError("project_path_invalid", "搜索路径超出文件范围。")
        candidates = deque([(target, target_metadata)])
        pending: list[Path] = []
        initial = target.parent
        scanned_entries = 1
    elif stat.S_ISDIR(target_metadata.st_mode):
        initial_snapshot = _inspect_directory(target)
        candidates = deque()
        pending = [initial_snapshot.path]
        initial = initial_snapshot.path
    else:
        raise ProjectError("project_path_invalid", "搜索路径不是普通文件或目录。")

    while candidates or pending:
        if monotonic() >= deadline:
            truncation_reason = "time_budget"
            break
        if not candidates:
            directory = pending.pop()
            before = _inspect_directory(directory)
            try:
                with os.scandir(directory) as iterator:
                    entries = sorted(iterator, key=lambda entry: entry.name.casefold())
            except OSError:
                state["skipped_files"] += 1
                continue
            if _inspect_directory(directory).identity != before.identity:
                raise ProjectError(
                    "project_directory_changed", "目录已变化，请重新搜索。"
                )
            child_directories: list[Path] = []
            for entry in entries:
                scanned_entries += 1
                if scanned_entries > scan_limit:
                    truncation_reason = "scan_limit"
                    break
                if ignored(entry.name) or not valid_name(entry.name):
                    continue
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError:
                    state["skipped_files"] += 1
                    continue
                if (
                    stat.S_ISLNK(metadata.st_mode)
                    or getattr(metadata, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                ):
                    continue
                entry_path = Path(entry.path)
                if stat.S_ISDIR(metadata.st_mode):
                    child_directories.append(entry_path)
                elif stat.S_ISREG(metadata.st_mode):
                    candidates.append((entry_path, metadata))
            if truncation_reason is not None:
                break
            pending.extend(reversed(child_directories))

        while candidates:
            candidate, _metadata = candidates.popleft()
            relative_path = candidate.relative_to(root).as_posix()
            pattern_path = candidate.relative_to(initial).as_posix()
            if file_pattern is not None and not matches_glob_pattern(
                file_pattern, pattern_path
            ):
                continue
            try:
                reason = _search_text_file(
                    root,
                    relative_path,
                    query=query,
                    case_sensitive=case_sensitive,
                    deadline=deadline,
                    limit=limit,
                    file_limit=file_limit,
                    byte_budget=byte_budget,
                    output_budget=output_budget,
                    state=state,
                )
            except ProjectError as error:
                if error.code not in {
                    "project_file_unavailable",
                    "project_file_unsupported",
                }:
                    raise
                state["skipped_files"] += 1
                continue
            if reason is not None:
                truncation_reason = reason
                break
        if truncation_reason is not None:
            break

    if truncation_reason is None and (
        state["skipped_files"] or state["skipped_lines"]
    ):
        truncation_reason = "unsupported_content"
    return {
        "path": path,
        "query": query,
        "file_pattern": file_pattern,
        "case_sensitive": case_sensitive,
        "matches": state["matches"],
        "truncated": truncation_reason is not None,
        "truncation_reason": truncation_reason,
        "limit": limit,
        "scanned_entries": min(scanned_entries, scan_limit),
        "scanned_files": state["scanned_files"],
        "scanned_bytes": state["scanned_bytes"],
        "skipped_files": state["skipped_files"],
        "skipped_lines": state["skipped_lines"],
        "output_chars": state["output_chars"],
    }
