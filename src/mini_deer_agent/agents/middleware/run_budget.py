"""累计主/子 Agent 模型用量，并在软硬预算处确定性收敛 Run。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import RLock
from typing import Literal, cast

import json

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from mini_deer_agent.agents.middleware.loop_detection import LOOP_STOP_REASON_KEY


RUN_USAGE_KEY = "mini_deer_run_usage"
type BudgetStopReason = Literal["token_capped", "turn_capped"]


@dataclass(frozen=True, slots=True)
class RunBudgetPolicy:
    soft_token_limit: int = 80_000
    hard_token_limit: int = 120_000
    soft_turn_limit: int = 16
    hard_turn_limit: int = 24

    def __post_init__(self) -> None:
        if self.soft_token_limit < 1:
            raise ValueError("soft token limit must be positive")
        if self.hard_token_limit <= self.soft_token_limit:
            raise ValueError("hard token limit must exceed soft token limit")
        if self.soft_turn_limit < 1:
            raise ValueError("soft turn limit must be positive")
        if self.hard_turn_limit <= self.soft_turn_limit:
            raise ValueError("hard turn limit must exceed soft turn limit")


@dataclass(frozen=True, slots=True)
class RunUsageSnapshot:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    model_calls: int


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _useful_prior_text(messages: list[BaseMessage] | None) -> str:
    """优先保留模型正文，其次提取已完成子 Agent 的部分结果。"""
    if messages is None:
        return ""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.text.strip():
            return message.text.strip()
        if not isinstance(message, ToolMessage) or message.name != "task":
            continue
        try:
            payload = json.loads(message.text)
        except (json.JSONDecodeError, TypeError):
            continue
        result = payload.get("result") if isinstance(payload, dict) else None
        if isinstance(result, str) and result.strip():
            return result.strip()
    return ""


def _usage_from_response(response: BaseMessage) -> tuple[int, int, int]:
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict):
        input_tokens = _nonnegative_int(usage.get("input_tokens")) or 0
        output_tokens = _nonnegative_int(usage.get("output_tokens")) or 0
        total_tokens = _nonnegative_int(usage.get("total_tokens"))
        return (
            input_tokens,
            output_tokens,
            total_tokens if total_tokens is not None else input_tokens + output_tokens,
        )
    metadata = response.response_metadata or {}
    raw = metadata.get("token_usage") or metadata.get("usage")
    if not isinstance(raw, dict):
        return 0, 0, 0
    input_tokens = (
        _nonnegative_int(raw.get("input_tokens"))
        or _nonnegative_int(raw.get("prompt_tokens"))
        or 0
    )
    output_tokens = (
        _nonnegative_int(raw.get("output_tokens"))
        or _nonnegative_int(raw.get("completion_tokens"))
        or 0
    )
    total_tokens = _nonnegative_int(raw.get("total_tokens"))
    return (
        input_tokens,
        output_tokens,
        total_tokens if total_tokens is not None else input_tokens + output_tokens,
    )


def _cap_notice(reason: BudgetStopReason) -> str:
    return (
        "本次运行已达到 Token 硬预算；以下结论仅使用预算内已经取得的内容。"
        if reason == "token_capped"
        else "本次运行已达到模型轮次硬预算；以下结论仅使用预算内已经取得的内容。"
    )


class RunBudgetTracker:
    """一个主图及其全部子图共享的线程安全 Run 预算。"""

    def __init__(self, policy: RunBudgetPolicy | None = None) -> None:
        self.policy = policy or RunBudgetPolicy()
        self._run_key: str | None = None
        self._input_tokens = 0
        self._output_tokens = 0
        self._total_tokens = 0
        self._model_calls = 0
        self._soft_warning_pending = False
        self._soft_warning_emitted = False
        self._hard_reason: BudgetStopReason | None = None
        self._stop_reason: str | None = None
        self._pinned_run_key: str | None = None
        self._lock = RLock()

    def pin_run(self, run_key: str) -> None:
        """把多个隐藏续轮固定为同一产品 Run，避免 HumanMessage ID 重置预算。"""
        with self._lock:
            if self._pinned_run_key == run_key:
                return
            self._pinned_run_key = None
        self.begin_run(run_key)
        with self._lock:
            self._pinned_run_key = run_key

    def begin_run(self, run_key: str | None) -> None:
        """复用同一编译图时，以当前用户回合清空上一 Run 的累计值。"""
        with self._lock:
            if self._pinned_run_key is not None:
                return
            if run_key == self._run_key:
                return
            self._run_key = run_key
            self._input_tokens = 0
            self._output_tokens = 0
            self._total_tokens = 0
            self._model_calls = 0
            self._soft_warning_pending = False
            self._soft_warning_emitted = False
            self._hard_reason = None
            self._stop_reason = None

    def snapshot(self) -> RunUsageSnapshot:
        with self._lock:
            return RunUsageSnapshot(
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
                total_tokens=self._total_tokens,
                model_calls=self._model_calls,
            )

    def child_scope(self) -> ScopedRunBudgetTracker:
        """创建独立计量、共享硬上限的子 Agent 预算视图。"""
        return ScopedRunBudgetTracker(self)

    def reserve_model_call(self) -> BudgetStopReason | None:
        """在发请求前原子占用一次轮次；并行子 Agent 不能突破硬轮次。"""
        with self._lock:
            if self._hard_reason is not None:
                return self._hard_reason
            if self._model_calls >= self.policy.hard_turn_limit:
                self._hard_reason = "turn_capped"
                return self._hard_reason
            self._model_calls += 1
            return None

    def record_response(self, response: BaseMessage) -> BudgetStopReason | None:
        """累计一个已完成响应的实际用量，并决定是否达到软硬阈值。"""
        input_tokens, output_tokens, total_tokens = _usage_from_response(response)
        with self._lock:
            self._input_tokens += input_tokens
            self._output_tokens += output_tokens
            self._total_tokens += total_tokens
            if self._total_tokens >= self.policy.hard_token_limit:
                self._hard_reason = "token_capped"
            if (
                self._hard_reason is None
                and not self._soft_warning_emitted
                and (
                    self._total_tokens >= self.policy.soft_token_limit
                    or self._model_calls >= self.policy.soft_turn_limit
                )
            ):
                self._soft_warning_pending = True
                self._soft_warning_emitted = True
            return self._hard_reason

    def append_pending_warning(
        self,
        messages: list[BaseMessage],
    ) -> list[BaseMessage]:
        """把一次软预算提醒放在已配对工具结果之后，不写入 checkpoint。"""
        with self._lock:
            if not self._soft_warning_pending:
                return messages
            self._soft_warning_pending = False
            snapshot = self.snapshot()
        return [
            *messages,
            HumanMessage(
                content=(
                    "[运行预算] 本次任务已接近 Token 或模型轮次上限。"
                    "请停止无必要扩张，优先使用已有证据形成结论；仍缺少的部分明确说明。"
                    f" 当前累计：{snapshot.total_tokens} tokens，"
                    f"{snapshot.model_calls} 次模型调用。"
                ),
                additional_kwargs={
                    "hide_from_ui": True,
                    "kind": "run_budget_warning",
                },
            ),
        ]

    def stamp(self, response: BaseMessage) -> BaseMessage:
        """把累计用量附在主 Agent 响应上，供流式投影器生成正式终态。"""
        kwargs = dict(response.additional_kwargs or {})
        raw_reason = kwargs.get(LOOP_STOP_REASON_KEY)
        if isinstance(raw_reason, str) and raw_reason:
            with self._lock:
                self._stop_reason = raw_reason
        kwargs[RUN_USAGE_KEY] = asdict(self.snapshot())
        return response.model_copy(update={"additional_kwargs": kwargs})

    def terminal_payload(self) -> dict[str, object]:
        """返回产品终态所需的共享累计快照，不依赖 token chunk 回传。"""
        with self._lock:
            payload: dict[str, object] = asdict(
                RunUsageSnapshot(
                    input_tokens=self._input_tokens,
                    output_tokens=self._output_tokens,
                    total_tokens=self._total_tokens,
                    model_calls=self._model_calls,
                )
            )
            reason = self._stop_reason or self._hard_reason
            if reason is not None:
                payload["finish_reason"] = reason
            return payload

    def capped_response(
        self,
        reason: BudgetStopReason,
        response: BaseMessage | None = None,
        *,
        prior_messages: list[BaseMessage] | None = None,
    ) -> AIMessage:
        """移除新的工具调用，保留可用正文并携带正式预算终止原因。"""
        content: object = ""
        text = ""
        if isinstance(response, AIMessage):
            content = response.content
            text = response.text.strip()
        if not text:
            text = _useful_prior_text(prior_messages)
        notice = _cap_notice(reason)
        if not text:
            content = notice
        elif not isinstance(response, AIMessage) or not response.text.strip():
            content = f"{text}\n\n{notice}"
        kwargs = (
            dict(response.additional_kwargs or {})
            if isinstance(response, AIMessage)
            else {}
        )
        kwargs[LOOP_STOP_REASON_KEY] = reason
        kwargs[RUN_USAGE_KEY] = asdict(self.snapshot())
        return AIMessage(
            content=cast(str | list[str | dict], content),
            additional_kwargs=kwargs,
            response_metadata=(
                dict(response.response_metadata or {})
                if isinstance(response, AIMessage)
                else {}
            ),
            id=response.id if isinstance(response, AIMessage) else None,
            tool_calls=[],
            usage_metadata=(
                response.usage_metadata if isinstance(response, AIMessage) else None
            ),
        )


class ScopedRunBudgetTracker(RunBudgetTracker):
    """把子任务用量单独计量，同时把每次调用原子计入父 Run。"""

    def __init__(self, parent: RunBudgetTracker) -> None:
        self.parent = parent
        self.policy = parent.policy
        self._input_tokens = 0
        self._output_tokens = 0
        self._total_tokens = 0
        self._model_calls = 0
        self._lock = RLock()

    def begin_run(self, run_key: str | None) -> None:
        """子视图生命周期固定，不得重置父 Run 或自身已累计用量。"""
        del run_key

    def snapshot(self) -> RunUsageSnapshot:
        with self._lock:
            return RunUsageSnapshot(
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
                total_tokens=self._total_tokens,
                model_calls=self._model_calls,
            )

    def child_scope(self) -> ScopedRunBudgetTracker:
        """嵌套委派被角色权限禁止；仍保持安全的同级计量语义。"""
        return ScopedRunBudgetTracker(self.parent)

    def reserve_model_call(self) -> BudgetStopReason | None:
        reason = self.parent.reserve_model_call()
        if reason is None:
            with self._lock:
                self._model_calls += 1
        return reason

    def record_response(self, response: BaseMessage) -> BudgetStopReason | None:
        input_tokens, output_tokens, total_tokens = _usage_from_response(response)
        with self._lock:
            self._input_tokens += input_tokens
            self._output_tokens += output_tokens
            self._total_tokens += total_tokens
        return self.parent.record_response(response)

    def append_pending_warning(
        self,
        messages: list[BaseMessage],
    ) -> list[BaseMessage]:
        return self.parent.append_pending_warning(messages)

    def stamp(self, response: BaseMessage) -> BaseMessage:
        return self.parent.stamp(response)

    def terminal_payload(self) -> dict[str, object]:
        return asdict(self.snapshot())

    def capped_response(
        self,
        reason: BudgetStopReason,
        response: BaseMessage | None = None,
        *,
        prior_messages: list[BaseMessage] | None = None,
    ) -> AIMessage:
        return self.parent.capped_response(
            reason,
            response,
            prior_messages=prior_messages,
        )
