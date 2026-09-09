"""根据统一结果元数据检测单个工具的连续失败与无效进展。"""

from __future__ import annotations

import json
import re
from threading import RLock
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from mini_deer_agent.agents.middleware.tool_results import (
    ToolResultMeta,
    attach_tool_result_meta,
    awrap_tool_call,
    tool_result_meta,
    wrap_tool_call,
)


_CONTENT_LIMIT = 8192
_EXEMPT_TOOLS = frozenset(
    {"write_todos", "ask_clarification", "activate_skill", "task"}
)


@dataclass(frozen=True, slots=True)
class ToolProgressPolicy:
    transient_failure_limit: int = 3
    repeated_content_limit: int = 2
    similarity_threshold: float = 0.85
    minimum_words: int = 10

    def __post_init__(self) -> None:
        if self.transient_failure_limit < 2:
            raise ValueError("transient failure limit must be at least 2")
        if self.repeated_content_limit < 2:
            raise ValueError("repeated content limit must be at least 2")
        if not 0 < self.similarity_threshold <= 1:
            raise ValueError("similarity threshold must be within (0, 1]")


@dataclass(slots=True)
class _ToolState:
    transient_failures: int = 0
    repeated_content: int = 0
    recent_words: tuple[frozenset[str], ...] = ()
    blocked_reason: str | None = None


def _word_set(content: str) -> frozenset[str]:
    return frozenset(re.findall(r"\b\w{3,}\b", content[:_CONTENT_LIMIT].casefold()))


def _near_duplicate(
    current: frozenset[str],
    previous: tuple[frozenset[str], ...],
    *,
    threshold: float,
    minimum_words: int,
) -> bool:
    if len(current) < minimum_words:
        return False
    for candidate in previous[-3:]:
        if len(candidate) < minimum_words:
            continue
        union = current | candidate
        if union and len(current & candidate) / len(union) >= threshold:
            return True
    return False


class ToolProgressTracker:
    """每个 Run 独立跟踪各工具状态，并组合统一异常包装器。"""

    def __init__(
        self,
        policy: ToolProgressPolicy | None = None,
        *,
        sync_wrapper: Callable[
            [
                ToolCallRequest,
                Callable[[ToolCallRequest], ToolMessage | Command],
            ],
            ToolMessage | Command,
        ] = wrap_tool_call,
        async_wrapper: Callable[
            [
                ToolCallRequest,
                Callable[
                    [ToolCallRequest],
                    Awaitable[ToolMessage | Command],
                ],
            ],
            Awaitable[ToolMessage | Command],
        ] = awrap_tool_call,
    ) -> None:
        self.policy = policy or ToolProgressPolicy()
        self._sync_wrapper = sync_wrapper
        self._async_wrapper = async_wrapper
        self._run_key: str | None = None
        self._states: dict[str, _ToolState] = {}
        self._pending_hints: dict[str, str] = {}
        self._lock = RLock()

    def begin_run(self, run_key: str | None) -> None:
        with self._lock:
            if run_key == self._run_key:
                return
            self._run_key = run_key
            self._states.clear()
            self._pending_hints.clear()

    def blocked_reason(self, tool_name: str) -> str | None:
        with self._lock:
            return self._states.get(tool_name, _ToolState()).blocked_reason

    def append_pending_hints(
        self, messages: list[BaseMessage]
    ) -> list[BaseMessage]:
        with self._lock:
            if not self._pending_hints:
                return messages
            hints = [
                self._pending_hints[name]
                for name in sorted(self._pending_hints)
            ]
            self._pending_hints.clear()
        return [
            *messages,
            HumanMessage(
                content="\n".join(hints),
                additional_kwargs={
                    "hide_from_ui": True,
                    "kind": "tool_progress_hint",
                },
            ),
        ]

    def _hint(self, tool_name: str, text: str) -> None:
        self._pending_hints[tool_name] = f"[工具进度] `{tool_name}` {text}"

    def _blocked_message(
        self, request: ToolCallRequest, reason: str
    ) -> ToolMessage:
        tool_name = str(request.tool_call.get("name") or "unknown_tool")
        meta = ToolResultMeta(
            status="terminal_error",
            recoverable_by_model=False,
            recommended_next_action="stop_using_tool",
            error_summary=reason,
            error_type="blocked_by_progress_guard",
        )
        return attach_tool_result_meta(
            ToolMessage(
                content=json.dumps(
                    {
                        "version": 1,
                        "kind": "tool_blocked",
                        "status": meta.status,
                        "recommended_next_action": meta.recommended_next_action,
                        "error_summary": reason,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                tool_call_id=str(
                    request.tool_call.get("id") or "missing_tool_call_id"
                ),
                name=tool_name,
                status="error",
            ),
            meta,
        )

    def _observe(
        self,
        tool_name: str,
        result: ToolMessage | Command,
    ) -> ToolMessage | Command:
        if not isinstance(result, ToolMessage) or tool_name in _EXEMPT_TOOLS:
            return result
        meta = tool_result_meta(result)
        if meta is None:
            return result
        with self._lock:
            state = self._states.setdefault(tool_name, _ToolState())
            if meta.status == "terminal_error":
                state.blocked_reason = (
                    meta.error_summary or "工具在当前 Run 中不可恢复。"
                )
                self._hint(
                    tool_name,
                    "遇到不可恢复错误，当前 Run 不再使用它；请改用其他工具。",
                )
                return result
            if meta.status == "retryable_error":
                if meta.error_type == "transient":
                    state.transient_failures += 1
                    if (
                        state.transient_failures
                        >= self.policy.transient_failure_limit
                    ):
                        state.blocked_reason = "连续瞬时失败已达到当前 Run 上限。"
                        self._hint(
                            tool_name,
                            "连续瞬时失败，已被阻断；请改用其他工具或基于已有证据收尾。",
                        )
                    else:
                        self._hint(
                            tool_name,
                            "暂时失败；请先改变参数或尝试其他工具，避免原样重试。",
                        )
                else:
                    self._hint(tool_name, "请求失败；请修正参数或改用其他工具。")
                return result
            state.transient_failures = 0
            if meta.status == "no_results":
                self._hint(tool_name, "没有返回结果；请改写查询或更换数据源。")
                return result
            if meta.status == "partial_success":
                self._hint(tool_name, "只返回部分结果；请按游标或范围继续读取。")
                return result

            words = _word_set(result.text)
            if _near_duplicate(
                words,
                state.recent_words,
                threshold=self.policy.similarity_threshold,
                minimum_words=self.policy.minimum_words,
            ):
                state.repeated_content += 1
                if (
                    state.repeated_content
                    >= self.policy.repeated_content_limit - 1
                ):
                    self._hint(
                        tool_name,
                        "连续返回近似相同正文；请更换参数、来源或停止扩张。",
                    )
            else:
                state.repeated_content = 0
            state.recent_words = (*state.recent_words, words)[-3:]
        return result

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        tool_name = str(request.tool_call.get("name") or "unknown_tool")
        blocked = self.blocked_reason(tool_name)
        if blocked is not None:
            return self._blocked_message(request, blocked)
        return self._observe(tool_name, self._sync_wrapper(request, handler))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        tool_name = str(request.tool_call.get("name") or "unknown_tool")
        blocked = self.blocked_reason(tool_name)
        if blocked is not None:
            return self._blocked_message(request, blocked)
        return self._observe(
            tool_name,
            await self._async_wrapper(request, handler),
        )
