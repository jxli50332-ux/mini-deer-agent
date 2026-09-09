"""统一工具结果语义，并把普通异常转换为可恢复的 ToolMessage。"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Literal, cast

from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command


logger = logging.getLogger(__name__)
TOOL_RESULT_META_KEY = "mini_deer_tool_result"

type ToolResultStatus = Literal[
    "success",
    "no_results",
    "partial_success",
    "retryable_error",
    "terminal_error",
]
type RecommendedNextAction = Literal[
    "continue",
    "rewrite_parameters",
    "continue_reading",
    "try_alternative",
    "retry_later",
    "stop_using_tool",
]


@dataclass(frozen=True, slots=True)
class ToolResultMeta:
    """所有工具结果共享的结构化语义。"""

    status: ToolResultStatus
    recoverable_by_model: bool
    recommended_next_action: RecommendedNextAction
    error_summary: str | None = None
    error_type: str | None = None


_TERMINAL_MARKERS = (
    "unauthorized",
    "authentication",
    "invalid api key",
    "forbidden",
    "permission denied",
    "access denied",
    "not configured",
    "missing api key",
    "disabled",
)
_TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "rate limit",
    "temporarily unavailable",
    "connection",
    "network",
    "internal error",
)
_NO_RESULT_MARKERS = (
    "no results",
    "no result",
    "not found",
    "does not exist",
    "no matches",
)


def tool_result_meta(message: ToolMessage) -> ToolResultMeta | None:
    """从 ToolMessage 读取并校验本项目生成的结果元数据。"""
    value = (message.additional_kwargs or {}).get(TOOL_RESULT_META_KEY)
    if not isinstance(value, dict):
        return None
    try:
        return ToolResultMeta(
            status=cast(ToolResultStatus, value["status"]),
            recoverable_by_model=bool(value["recoverable_by_model"]),
            recommended_next_action=cast(
                RecommendedNextAction,
                value["recommended_next_action"],
            ),
            error_summary=cast(str | None, value.get("error_summary")),
            error_type=cast(str | None, value.get("error_type")),
        )
    except (KeyError, TypeError):
        return None


def attach_tool_result_meta(
    message: ToolMessage,
    meta: ToolResultMeta,
) -> ToolMessage:
    """返回带不可变元数据副本的 ToolMessage，保留生产者的其他字段。"""
    kwargs = dict(message.additional_kwargs or {})
    kwargs[TOOL_RESULT_META_KEY] = asdict(meta)
    return message.model_copy(update={"additional_kwargs": kwargs})


def _json_object(content: str) -> dict[str, object] | None:
    try:
        value = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _error_text(content: str, payload: dict[str, object] | None) -> str:
    if payload is None:
        return content
    error = payload.get("error")
    if isinstance(error, dict):
        return " ".join(str(value) for value in error.values())
    if error:
        return str(error)
    return content if payload.get("ok") is False else ""


def _classify_error(text: str) -> ToolResultMeta:
    lower = text.casefold()
    if any(marker in lower for marker in _TERMINAL_MARKERS):
        return ToolResultMeta(
            status="terminal_error",
            recoverable_by_model=False,
            recommended_next_action="stop_using_tool",
            error_summary="工具因认证、配置或权限问题不可用。",
            error_type="configuration_or_permission",
        )
    if any(marker in lower for marker in _TRANSIENT_MARKERS):
        return ToolResultMeta(
            status="retryable_error",
            recoverable_by_model=True,
            recommended_next_action="try_alternative",
            error_summary="工具遇到暂时性服务或网络错误。",
            error_type="transient",
        )
    if any(marker in lower for marker in _NO_RESULT_MARKERS):
        return ToolResultMeta(
            status="no_results",
            recoverable_by_model=True,
            recommended_next_action="rewrite_parameters",
        )
    return ToolResultMeta(
        status="retryable_error",
        recoverable_by_model=True,
        recommended_next_action="rewrite_parameters",
        error_summary="工具请求失败；请修正参数或改用其他工具。",
        error_type="tool_error",
    )


def normalize_tool_message(message: ToolMessage) -> ToolMessage:
    """为普通返回值推导统一语义；已有可信 stamp 保持不变。"""
    if tool_result_meta(message) is not None:
        return message
    content = message.text
    payload = _json_object(content)
    payload_error = _error_text(content, payload) if payload is not None else ""
    if message.status == "error":
        return attach_tool_result_meta(
            message,
            _classify_error(payload_error or content),
        )
    if payload_error:
        return attach_tool_result_meta(message, _classify_error(payload_error))

    if payload is not None:
        collections = [payload.get("results"), payload.get("items")]
        if any(isinstance(value, list) and not value for value in collections):
            return attach_tool_result_meta(
                message,
                ToolResultMeta(
                    status="no_results",
                    recoverable_by_model=True,
                    recommended_next_action="rewrite_parameters",
                ),
            )
        if payload.get("truncated") is True or payload.get("partial") is True:
            return attach_tool_result_meta(
                message,
                ToolResultMeta(
                    status="partial_success",
                    recoverable_by_model=True,
                    recommended_next_action="continue_reading",
                ),
            )
    return attach_tool_result_meta(
        message,
        ToolResultMeta(
            status="success",
            recoverable_by_model=True,
            recommended_next_action="continue",
        ),
    )


def _exception_message(request: ToolCallRequest, exc: Exception) -> ToolMessage:
    tool_name = str(request.tool_call.get("name") or "unknown_tool")
    tool_call_id = str(request.tool_call.get("id") or "missing_tool_call_id")
    type_name = type(exc).__name__
    meta = _classify_error(f"{type_name}: {exc}")
    if meta.error_summary is None:
        meta = ToolResultMeta(
            status=meta.status,
            recoverable_by_model=meta.recoverable_by_model,
            recommended_next_action=meta.recommended_next_action,
            error_summary=f"工具 {tool_name} 执行失败（{type_name}）。",
            error_type=meta.error_type,
        )
    content = json.dumps(
        {
            "version": 1,
            "kind": "tool_error",
            **asdict(meta),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return attach_tool_result_meta(
        ToolMessage(
            content=content,
            tool_call_id=tool_call_id,
            name=tool_name,
            status="error",
        ),
        meta,
    )


def normalize_tool_result(result: ToolMessage | Command) -> ToolMessage | Command:
    return normalize_tool_message(result) if isinstance(result, ToolMessage) else result


def wrap_tool_call(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    """同步工具边界：保留图控制异常，归一普通结果和普通异常。"""
    try:
        return normalize_tool_result(handler(request))
    except GraphBubbleUp:
        raise
    except Exception as exc:
        logger.warning(
            "工具执行失败并转换为 ToolMessage：tool=%s error_type=%s",
            request.tool_call.get("name"),
            type(exc).__name__,
        )
        return _exception_message(request, exc)


async def awrap_tool_call(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
) -> ToolMessage | Command:
    """异步工具边界：CancelledError 不属于 Exception，会自然传播。"""
    try:
        return normalize_tool_result(await handler(request))
    except GraphBubbleUp:
        raise
    except Exception as exc:
        logger.warning(
            "异步工具执行失败并转换为 ToolMessage：tool=%s error_type=%s",
            request.tool_call.get("name"),
            type(exc).__name__,
        )
        return _exception_message(request, exc)
