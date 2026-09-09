"""限制 ToolMessage 上下文大小，并把完整结果保存到当前 Run 的内部目录。"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import stat
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass
from io import StringIO
from pathlib import Path
from threading import RLock
from typing import Literal, cast
from uuid import UUID, uuid4

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from mini_deer_agent.agents.middleware.tool_results import (
    ToolResultMeta,
    attach_tool_result_meta,
    awrap_tool_call,
    normalize_tool_message,
    tool_result_meta,
    wrap_tool_call,
)


TOOL_OUTPUT_META_KEY = "mini_deer_tool_output"
_VIRTUAL_PREFIX = "run-output/"
_STRUCTURE_PARSE_LIMIT = 2 * 1024 * 1024
_SAFE_FILENAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
_YAML_KEY = re.compile(r"^[A-Za-z_][\w.-]*\s*:", re.MULTILINE)
_XML_ROOT = re.compile(r"^\s*(?:<\?xml[^>]*>\s*)?<([A-Za-z_][\w:.-]*)")

type ToolOutputFormat = Literal["json", "csv", "tsv", "xml", "yaml", "text"]


@dataclass(frozen=True, slots=True)
class ToolOutputBudgetPolicy:
    max_inline_chars: int = 12_000
    sample_chars: int = 1_200
    read_chunk_chars: int = 8_000

    def __post_init__(self) -> None:
        if self.max_inline_chars < 1_024:
            raise ValueError("max inline characters must be at least 1024")
        if not 64 <= self.sample_chars <= self.max_inline_chars // 3:
            raise ValueError("sample characters must fit within inline budget")
        if not 256 <= self.read_chunk_chars <= self.max_inline_chars - 512:
            raise ValueError("read chunk characters must fit within inline budget")


@dataclass(frozen=True, slots=True)
class ToolOutputMeta:
    original_chars: int
    original_bytes: int
    format: ToolOutputFormat
    stored: bool
    path: str | None
    storage_error: str | None


@dataclass(frozen=True, slots=True)
class _OutputScope:
    store: "RunOutputStore"
    run_id: str


_CURRENT_OUTPUT_SCOPE: ContextVar[_OutputScope | None] = ContextVar(
    "mini_deer_tool_output_scope",
    default=None,
)


class RunOutputError(RuntimeError):
    """内部结果路径不可用；公开响应只使用稳定错误码。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _normalized_run_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        normalized = str(UUID(value))
    except (ValueError, AttributeError):
        return None
    return normalized if value.casefold() == normalized else None


def _safe_tool_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")
    return (normalized or "tool")[:48]


def _value_kind(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def _short(value: object, limit: int = 120) -> str:
    text = str(value)
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _detect_format(content: str) -> tuple[ToolOutputFormat, dict[str, object]]:
    stripped = content.lstrip()
    if stripped.startswith(("{", "[")):
        summary: dict[str, object] = {"container": "unknown"}
        if len(content) <= _STRUCTURE_PARSE_LIMIT:
            try:
                value = json.loads(content)
            except (json.JSONDecodeError, ValueError):
                pass
            else:
                if isinstance(value, dict):
                    keys = list(value)[:30]
                    rendered_keys = [_short(key) for key in keys]
                    summary = {
                        "container": "object",
                        "key_count": len(value),
                        "keys": rendered_keys,
                        "value_types": {
                            rendered: _value_kind(value[key])
                            for key, rendered in zip(keys, rendered_keys, strict=True)
                        },
                    }
                elif isinstance(value, list):
                    summary = {
                        "container": "array",
                        "item_count": len(value),
                        "sample_item_types": [
                            _value_kind(item) for item in value[:20]
                        ],
                    }
                else:
                    summary = {"container": _value_kind(value)}
        return "json", summary

    xml_match = _XML_ROOT.match(content)
    if xml_match is not None:
        sample = content[:65_536]
        return "xml", {
            "root_element": _short(xml_match.group(1)),
            "sample_element_count": len(
                re.findall(r"<[A-Za-z_][\w:.-]*(?:\s|>|/)", sample)
            ),
        }

    first_lines = content[:65_536].splitlines()[:50]
    first_nonempty = next((line for line in first_lines if line.strip()), "")
    delimiter = "\t" if "\t" in first_nonempty else ","
    if delimiter in first_nonempty:
        try:
            rows = list(
                csv.reader(StringIO("\n".join(first_lines)), delimiter=delimiter)
            )
        except csv.Error:
            rows = []
        if rows and len(rows[0]) >= 2:
            widths = {len(row) for row in rows[:20] if row}
            if widths and len(widths) <= 3:
                return ("tsv" if delimiter == "\t" else "csv"), {
                    "columns": [_short(column) for column in rows[0][:30]],
                    "column_count": len(rows[0]),
                    "estimated_rows": content.count("\n")
                    + (0 if content.endswith("\n") else 1),
                }

    yaml_keys = _YAML_KEY.findall(content[:65_536])
    if yaml_keys:
        return "yaml", {
            "top_level_keys": [
                _short(key.rstrip(":").strip()) for key in yaml_keys[:30]
            ],
            "sample_key_count": len(yaml_keys),
        }

    upper = content.upper()
    return "text", {
        "line_count": content.count("\n") + (0 if content.endswith("\n") else 1),
        "nonempty_line_count": sum(1 for line in content.splitlines() if line.strip()),
        "log_levels": {
            level: upper.count(level)
            for level in ("ERROR", "WARN", "INFO", "DEBUG")
            if level in upper
        },
    }


def _logical_lines(content: str, chunk_chars: int) -> list[str]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    source_lines = normalized.split("\n")
    if source_lines and source_lines[-1] == "":
        source_lines.pop()
    chunks: list[str] = []
    for line in source_lines:
        if not line:
            chunks.append("")
            continue
        chunks.extend(
            line[offset : offset + chunk_chars]
            for offset in range(0, len(line), chunk_chars)
        )
    return chunks


class RunOutputStore:
    """在不可由项目工具枚举的应用数据目录中保存完整 UTF-8 输出。"""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self._lock = RLock()

    def _run_directory(self, run_id: str, *, create: bool) -> Path:
        normalized = _normalized_run_id(run_id)
        if normalized is None:
            raise RunOutputError("run_output_scope_invalid", "当前 Run 身份无效。")
        try:
            if create:
                self.root.mkdir(parents=True, exist_ok=True)
            elif not self.root.exists():
                raise RunOutputError(
                    "run_output_not_found",
                    "当前 Run 中没有该内部工具结果。",
                )
            root_meta = self.root.lstat()
            if (
                not stat.S_ISDIR(root_meta.st_mode)
                or stat.S_ISLNK(root_meta.st_mode)
                or getattr(root_meta, "st_file_attributes", 0) & 0x400
            ):
                raise OSError("unsafe output root")
            directory = self.root / normalized
            if create:
                directory.mkdir(exist_ok=True)
            elif not directory.exists():
                raise RunOutputError(
                    "run_output_not_found",
                    "当前 Run 中没有该内部工具结果。",
                )
            directory_meta = directory.lstat()
            if (
                not stat.S_ISDIR(directory_meta.st_mode)
                or stat.S_ISLNK(directory_meta.st_mode)
                or getattr(directory_meta, "st_file_attributes", 0) & 0x400
                or directory.resolve(strict=True).parent
                != self.root.resolve(strict=True)
            ):
                raise OSError("unsafe run output directory")
            return directory
        except RunOutputError:
            raise
        except (OSError, RuntimeError):
            raise RunOutputError(
                "run_output_storage_unavailable",
                "完整工具输出暂时无法写入应用数据区。",
            ) from None

    def virtual_path(
        self,
        *,
        tool_name: str,
        tool_call_id: str,
        output_format: ToolOutputFormat,
    ) -> str:
        digest = hashlib.sha256(
            f"{tool_name}\0{tool_call_id}".encode("utf-8")
        ).hexdigest()[:20]
        return f"{_VIRTUAL_PREFIX}{_safe_tool_name(tool_name)}-{digest}.{output_format}"

    def write(
        self,
        run_id: str,
        *,
        tool_name: str,
        tool_call_id: str,
        output_format: ToolOutputFormat,
        content: str,
    ) -> str:
        virtual_path = self.virtual_path(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            output_format=output_format,
        )
        filename = virtual_path.removeprefix(_VIRTUAL_PREFIX)
        with self._lock:
            directory = self._run_directory(run_id, create=True)
            target = directory / filename
            temporary = directory / f".{filename}.{uuid4().hex}.tmp"
            try:
                with temporary.open("x", encoding="utf-8", newline="") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            except OSError:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                raise RunOutputError(
                    "run_output_storage_unavailable",
                    "完整工具输出暂时无法写入应用数据区。",
                ) from None
        return virtual_path

    def read(
        self,
        run_id: str,
        path: str,
        *,
        start_line: int,
        limit: int,
        chunk_chars: int,
    ) -> dict[str, object]:
        filename = path.removeprefix(_VIRTUAL_PREFIX)
        if (
            not path.startswith(_VIRTUAL_PREFIX)
            or "/" in filename
            or "\\" in filename
            or not _SAFE_FILENAME.fullmatch(filename)
            or not 1 <= start_line <= 1_000_000
            or not 1 <= limit <= 200
        ):
            raise RunOutputError("run_output_path_invalid", "内部结果路径或范围无效。")
        with self._lock:
            directory = self._run_directory(run_id, create=False)
            target = directory / filename
            try:
                before = target.lstat()
                if (
                    not stat.S_ISREG(before.st_mode)
                    or stat.S_ISLNK(before.st_mode)
                    or getattr(before, "st_file_attributes", 0) & 0x400
                    or target.resolve(strict=True).parent
                    != directory.resolve(strict=True)
                ):
                    raise OSError("unsafe output file")
                data = target.read_bytes()
                after = target.lstat()
                if (
                    (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                ):
                    raise OSError("output changed while reading")
                content = data.decode("utf-8")
            except FileNotFoundError:
                raise RunOutputError(
                    "run_output_not_found",
                    "当前 Run 中没有该内部工具结果。",
                ) from None
            except (OSError, UnicodeDecodeError):
                raise RunOutputError(
                    "run_output_unavailable",
                    "内部工具结果当前无法读取。",
                ) from None
        lines = _logical_lines(content, chunk_chars)
        if start_line > max(1, len(lines)):
            raise RunOutputError("run_output_range_invalid", "起始位置超过结果末尾。")
        selected: list[str] = []
        used = 0
        for line in lines[start_line - 1 : start_line - 1 + limit]:
            size = len(line) + 1
            if selected and used + size > chunk_chars:
                break
            selected.append(line)
            used += size
        next_line = start_line + len(selected)
        return {
            "ok": True,
            "status": "text",
            "path": path,
            "size_bytes": len(data),
            "lines": selected,
            "line_numbers": list(range(start_line, next_line)),
            "start_line": start_line,
            "next_line": next_line if next_line <= len(lines) else None,
            "total_lines": len(lines),
            "revision": hashlib.sha256(data).hexdigest(),
            "virtual_chunks": True,
        }


class ReadRunOutputInput(BaseModel):
    """没有项目 Scope 时，read_file 只接受当前 Run 的虚拟输出路径。"""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(
        min_length=1,
        max_length=256,
        pattern=r"^run-output/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
        description="工具摘要返回的 run-output/... 虚拟路径",
    )
    start_line: int = Field(default=1, ge=1, le=1_000_000)
    limit: int = Field(default=100, ge=1, le=200)


def create_run_output_read_tool() -> BaseTool:
    """创建由输出预算拦截器实现的虚拟 read_file 占位工具。"""

    def unavailable(path: str, start_line: int = 1, limit: int = 100) -> str:
        del path, start_line, limit
        return json.dumps(
            {
                "ok": False,
                "error": {
                    "code": "run_output_scope_unavailable",
                    "message": "当前没有可续读的内部工具结果。",
                },
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        func=unavailable,
        name="read_file",
        args_schema=ReadRunOutputInput,
        description=(
            "只读当前 Run 工具摘要给出的 run-output/... 虚拟路径。"
            "使用 start_line 和 limit 分段续读；不能读取项目或宿主文件。"
        ),
    )


class ToolOutputBudget:
    """组合统一结果包装、确定性摘要、外置存储和虚拟续读。"""

    def __init__(
        self,
        store: RunOutputStore | None,
        policy: ToolOutputBudgetPolicy | None = None,
    ) -> None:
        self.store = store
        self.policy = policy or ToolOutputBudgetPolicy()

    def _scope(self, request: ToolCallRequest) -> _OutputScope | None:
        runtime = request.runtime
        config = getattr(runtime, "config", None)
        configurable = (
            config.get("configurable", {}) if isinstance(config, dict) else {}
        )
        run_id = _normalized_run_id(
            configurable.get("run_id") if isinstance(configurable, dict) else None
        )
        if self.store is not None and run_id is not None:
            return _OutputScope(self.store, run_id)
        return _CURRENT_OUTPUT_SCOPE.get()

    @staticmethod
    def _activate(scope: _OutputScope | None) -> Token[_OutputScope | None] | None:
        return _CURRENT_OUTPUT_SCOPE.set(scope) if scope is not None else None

    @staticmethod
    def _deactivate(token: Token[_OutputScope | None] | None) -> None:
        if token is not None:
            _CURRENT_OUTPUT_SCOPE.reset(token)

    def _read_virtual(
        self,
        request: ToolCallRequest,
        scope: _OutputScope | None,
    ) -> ToolMessage | None:
        if request.tool_call.get("name") != "read_file":
            return None
        arguments = request.tool_call.get("args")
        path = arguments.get("path") if isinstance(arguments, dict) else None
        if not isinstance(path, str) or not path.startswith(_VIRTUAL_PREFIX):
            return None
        call_id = str(request.tool_call.get("id") or "missing_tool_call_id")
        try:
            if scope is None:
                raise RunOutputError(
                    "run_output_scope_unavailable",
                    "当前没有可续读的内部工具结果。",
                )
            start_line = int(cast(dict, arguments).get("start_line", 1))
            limit = int(cast(dict, arguments).get("limit", 100))
            payload = scope.store.read(
                scope.run_id,
                path,
                start_line=start_line,
                limit=limit,
                chunk_chars=self.policy.read_chunk_chars,
            )
            message = ToolMessage(
                content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                tool_call_id=call_id,
                name="read_file",
            )
            return normalize_tool_message(message)
        except (RunOutputError, TypeError, ValueError) as exc:
            error = (
                exc
                if isinstance(exc, RunOutputError)
                else RunOutputError("run_output_range_invalid", "读取范围无效。")
            )
            message = ToolMessage(
                content=json.dumps(
                    {
                        "ok": False,
                        "error": {"code": error.code, "message": error.message},
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                tool_call_id=call_id,
                name="read_file",
                status="error",
            )
            return attach_tool_result_meta(
                message,
                ToolResultMeta(
                    status=(
                        "no_results"
                        if error.code == "run_output_not_found"
                        else "retryable_error"
                    ),
                    recoverable_by_model=True,
                    recommended_next_action=(
                        "rewrite_parameters"
                        if error.code == "run_output_not_found"
                        else "try_alternative"
                    ),
                    error_summary=error.message,
                    error_type=error.code,
                ),
            )

    def _summary_content(
        self,
        message: ToolMessage,
        scope: _OutputScope | None,
    ) -> tuple[str, ToolOutputMeta]:
        content = message.text
        output_format, structure = _detect_format(content)
        path = None
        storage_error = None
        if scope is not None:
            try:
                path = scope.store.write(
                    scope.run_id,
                    tool_name=message.name or "unknown_tool",
                    tool_call_id=message.tool_call_id,
                    output_format=output_format,
                    content=content,
                )
            except RunOutputError as exc:
                storage_error = exc.code
        else:
            storage_error = "run_output_scope_unavailable"
        meta = ToolOutputMeta(
            original_chars=len(content),
            original_bytes=len(content.encode("utf-8")),
            format=output_format,
            stored=path is not None,
            path=path,
            storage_error=storage_error,
        )
        sample = self.policy.sample_chars
        payload: dict[str, object] = {
            "version": 1,
            "kind": "tool_output_reference",
            "status": "partial_success",
            **asdict(meta),
            "structure": structure,
            "sample": {
                "head": content[:sample],
                "tail": content[-sample:] if len(content) > sample else "",
            },
            "next_action": (
                {
                    "tool": "read_file",
                    "path": path,
                    "start_line": 1,
                    "limit": 100,
                }
                if path is not None
                else {
                    "action": "use_bounded_sample",
                    "warning": "完整内容未能外置；以下仅为明确标记的有界样本。",
                }
            ),
        }
        rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(rendered) > self.policy.max_inline_chars:
            cast(dict[str, str], payload["sample"])["head"] = content[:64]
            cast(dict[str, str], payload["sample"])["tail"] = content[-64:]
            rendered = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        if len(rendered) > self.policy.max_inline_chars:
            payload["structure"] = {
                "summary": "结构字段过多，已省略；按虚拟路径分段读取。"
            }
            payload["sample"] = {
                "head": content[:32],
                "tail": content[-32:],
            }
            rendered = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        if len(rendered) > self.policy.max_inline_chars:
            payload.pop("sample", None)
            rendered = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        if len(rendered) > self.policy.max_inline_chars:
            payload = {
                "version": 1,
                "kind": "tool_output_reference",
                "status": "partial_success",
                **asdict(meta),
                "structure": {"summary": "详细结构与样本已按上下文预算省略。"},
                "next_action": (
                    {"tool": "read_file", "path": path, "start_line": 1, "limit": 100}
                    if path is not None
                    else {
                        "action": "report_limited_evidence",
                        "warning": "完整内容未能外置，且样本超出上下文预算。",
                    }
                ),
            }
            rendered = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        return rendered, meta

    def _apply_budget(
        self,
        result: ToolMessage | Command,
        scope: _OutputScope | None,
    ) -> ToolMessage | Command:
        if not isinstance(result, ToolMessage):
            return result
        if len(result.text) <= self.policy.max_inline_chars:
            return result
        content, output_meta = self._summary_content(result, scope)
        kwargs = dict(result.additional_kwargs or {})
        kwargs[TOOL_OUTPUT_META_KEY] = asdict(output_meta)
        budgeted = result.model_copy(
            update={"content": content, "additional_kwargs": kwargs}
        )
        existing = tool_result_meta(budgeted)
        if existing is None or existing.status == "success":
            budgeted = attach_tool_result_meta(
                budgeted,
                ToolResultMeta(
                    status="partial_success",
                    recoverable_by_model=True,
                    recommended_next_action=(
                        "continue_reading" if output_meta.stored else "try_alternative"
                    ),
                ),
            )
        return budgeted

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        scope = self._scope(request)
        virtual = self._read_virtual(request, scope)
        if virtual is not None:
            return virtual
        token = self._activate(scope)
        try:
            result = wrap_tool_call(request, handler)
        finally:
            self._deactivate(token)
        return self._apply_budget(result, scope)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        scope = self._scope(request)
        virtual = self._read_virtual(request, scope)
        if virtual is not None:
            return virtual
        token = self._activate(scope)
        try:
            result = await awrap_tool_call(request, handler)
        finally:
            self._deactivate(token)
        return self._apply_budget(result, scope)
