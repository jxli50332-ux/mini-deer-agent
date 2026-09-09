"""检测 Run 内连续重复的工具调用，并在有界次数内强制收尾。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


LOOP_STOP_REASON_KEY = "mini_deer_stop_reason"
LOOP_CAPPED_REASON = "loop_capped"
_EXEMPT_TOOLS = frozenset(
    {"write_todos", "ask_clarification", "activate_skill", "task"}
)
_SOFT_WARNING = (
    "[执行约束] 你正在使用完全相同的参数重复调用同一组工具。"
    "请改变查询、路径、页码或工具；如果已有证据足够，请停止调用工具并形成结论。"
)
_HARD_FINALIZE = (
    "[执行约束] 相同工具调用已达到硬上限。不得继续调用任何工具。"
    "请只使用已有工具结果给出最终结论；无法完成的部分必须明确说明证据缺口。"
)
_FALLBACK_FINAL = "重复工具调用已达到安全上限；请依据以上已有结果完成当前任务。"


@dataclass(frozen=True, slots=True)
class ToolLoopPolicy:
    """可调但有严格顺序约束的软、硬阈值。"""

    soft_limit: int = 3
    hard_limit: int = 5

    def __post_init__(self) -> None:
        if self.soft_limit < 2:
            raise ValueError("tool loop soft limit must be at least 2")
        if self.hard_limit <= self.soft_limit:
            raise ValueError("tool loop hard limit must exceed soft limit")


type LoopDecision = Literal["continue", "warn", "cap"]


def _normalize_args(raw: object) -> object:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return " ".join(raw.split())
    return raw


def tool_call_signature(message: BaseMessage) -> str | None:
    """以名称和完整规范化参数生成批次签名；分页变化自然形成新签名。"""
    calls = getattr(message, "tool_calls", None) or []
    normalized = [
        {"name": str(call.get("name") or ""), "args": _normalize_args(call.get("args"))}
        for call in calls
        if call.get("name") not in _EXEMPT_TOOLS
    ]
    if not normalized:
        return None
    normalized.sort(
        key=lambda value: json.dumps(
            value, ensure_ascii=False, sort_keys=True, default=str
        )
    )
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


class ToolLoopDetector:
    """每次构图创建一个实例，因此状态天然按当前 Run 隔离。"""

    def __init__(self, policy: ToolLoopPolicy | None = None) -> None:
        self.policy = policy or ToolLoopPolicy()
        self._last_signature: str | None = None
        self._repeat_count = 0
        self._warning_pending = False
        self._warned_signature: str | None = None
        self._run_key: str | None = None

    @property
    def repeat_count(self) -> int:
        return self._repeat_count

    def begin_run(self, run_key: str | None) -> None:
        """在同一图被复用时按最新用户回合清空旧 Run 的检测状态。"""
        if run_key == self._run_key:
            return
        self._run_key = run_key
        self._last_signature = None
        self._repeat_count = 0
        self._warning_pending = False
        self._warned_signature = None

    def observe(self, response: BaseMessage) -> LoopDecision:
        signature = tool_call_signature(response)
        if signature is None:
            self._last_signature = None
            self._repeat_count = 0
            self._warning_pending = False
            self._warned_signature = None
            return "continue"
        if signature == self._last_signature:
            self._repeat_count += 1
        else:
            self._last_signature = signature
            self._repeat_count = 1
            self._warning_pending = False
            self._warned_signature = None
        if self._repeat_count >= self.policy.hard_limit:
            self._warning_pending = False
            return "cap"
        if (
            self._repeat_count >= self.policy.soft_limit
            and self._warned_signature != signature
        ):
            self._warning_pending = True
            self._warned_signature = signature
            return "warn"
        return "continue"

    def append_pending_warning(
        self, messages: list[BaseMessage]
    ) -> list[BaseMessage]:
        """只在前一批 ToolMessage 已配对后注入一次临时提示。"""
        if not self._warning_pending:
            return messages
        self._warning_pending = False
        return [
            *messages,
            HumanMessage(
                content=_SOFT_WARNING,
                additional_kwargs={"hide_from_ui": True, "kind": "loop_warning"},
            ),
        ]


def loop_finalize_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """构造一次不落 checkpoint 的强制收尾请求。"""
    return [
        *messages,
        HumanMessage(
            content=_HARD_FINALIZE,
            additional_kwargs={"hide_from_ui": True, "kind": "loop_cap"},
        ),
    ]


def mark_loop_capped(response: BaseMessage | None) -> AIMessage:
    """移除强制收尾响应中的新工具调用，并标记正式终止原因。"""
    content = response.content if isinstance(response, AIMessage) else ""
    text = response.text.strip() if isinstance(response, AIMessage) else ""
    kwargs = dict(response.additional_kwargs or {}) if response is not None else {}
    kwargs[LOOP_STOP_REASON_KEY] = LOOP_CAPPED_REASON
    return AIMessage(
        content=content if text else _FALLBACK_FINAL,
        additional_kwargs=kwargs,
        response_metadata=(
            dict(response.response_metadata or {}) if response is not None else {}
        ),
        id=response.id if response is not None else None,
        tool_calls=[],
        usage_metadata=(
            response.usage_metadata if isinstance(response, AIMessage) else None
        ),
    )
