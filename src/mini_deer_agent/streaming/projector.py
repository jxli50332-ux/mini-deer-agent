"""把 LangGraph 原始消息投影为稳定的产品级 run 事件。"""

import json
import logging
from collections.abc import AsyncIterable, AsyncIterator, Callable, Iterable, Iterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from langchain_core.messages import AIMessageChunk, ToolMessage

from mini_deer_agent.agents.middleware.loop_detection import (
    LOOP_STOP_REASON_KEY,
)
from mini_deer_agent.agents.middleware.run_budget import RUN_USAGE_KEY
from mini_deer_agent.agents.middleware.tool_results import TOOL_RESULT_META_KEY
from mini_deer_agent.streaming.events import AgentMessageEvent, RunEvent, RunEventName


logger = logging.getLogger(__name__)
_DELTA_BATCH_CHARS = 128


def _run_namespace(run_id: str) -> UUID:
    """把正式或测试 Run ID 都转换为确定性的 UUID namespace。"""
    try:
        return UUID(run_id)
    except ValueError:
        return uuid5(NAMESPACE_URL, f"mini-deer-run:{run_id}")


def _public_message_id(
    run_namespace: UUID,
    *,
    message_kind: str,
    provider_message_id: str | None,
    fallback_identity: str,
) -> str:
    """把不可信 provider 身份映射为 Run 内稳定且跨 Run 隔离的产品 UUID。"""
    source_identity = provider_message_id or fallback_identity
    return str(uuid5(run_namespace, f"{message_kind}:{source_identity}"))


def _arguments_delta(value: object) -> str:
    """把模型返回的工具参数增量规范化为可传输字符串。"""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    # 少数兼容模型可能直接返回对象；统一编码后，前端仍按增量文本处理。
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class _RunProjectionState:
    """保存一次 Run 的消息身份、工具关联和严格递增序号。"""

    def __init__(self, run_id: str, thread_id: str) -> None:
        """初始化只属于当前 Run 的投影状态。"""
        self.run_id = run_id
        self.thread_id = thread_id
        self.sequence = 0
        self.run_namespace = _run_namespace(run_id)
        self.tool_states: dict[
            tuple[str | None, int], dict[str, str | None]
        ] = {}
        self.provider_to_logical_id: dict[str, str] = {}
        self.anonymous_ai_generation = 0
        self.finish_reason = "stop"
        self.run_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "model_calls": 0,
        }

    def _event(
        self,
        event: RunEventName,
        *,
        message_id: str | None,
        payload: dict[str, Any],
    ) -> RunEvent:
        """分配下一序号并创建一条内部 RunEvent。"""
        self.sequence += 1
        return RunEvent(
            event=event,
            run_id=self.run_id,
            thread_id=self.thread_id,
            sequence=self.sequence,
            message_id=message_id,
            payload=payload,
        )

    def started(self) -> RunEvent:
        """创建本轮第一条 run_started 事件。"""
        return self._event(
            "run_started",
            message_id=None,
            payload={"created_at": datetime.now(UTC).isoformat()},
        )

    def project_message(self, source: AgentMessageEvent) -> list[RunEvent]:
        """把一条 LangChain 消息投影成零到多条产品事件。"""
        message, _metadata = source
        provider_message_id = str(message.id) if message.id else None
        projected: list[RunEvent] = []

        if isinstance(message, AIMessageChunk):
            usage = (message.additional_kwargs or {}).get(RUN_USAGE_KEY)
            if isinstance(usage, dict):
                for field in self.run_usage:
                    value = usage.get(field)
                    if (
                        isinstance(value, int)
                        and not isinstance(value, bool)
                        and value >= 0
                    ):
                        self.run_usage[field] = value
            stop_reason = (message.additional_kwargs or {}).get(
                LOOP_STOP_REASON_KEY
            )
            if isinstance(stop_reason, str) and stop_reason:
                self.finish_reason = stop_reason
            message_id = _public_message_id(
                self.run_namespace,
                message_kind="assistant",
                provider_message_id=provider_message_id,
                fallback_identity=f"anonymous:{self.anonymous_ai_generation}",
            )
            if message.text:
                projected.append(
                    self._event(
                        "ai_delta",
                        message_id=message_id,
                        payload={"text": message.text},
                    )
                )
            reasoning = message.additional_kwargs.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning:
                # 思考过程与最终回答同属一条 assistant 消息，共享 message_id，
                # 前端据此把两者合并到同一个消息气泡里折叠展示。
                projected.append(
                    self._event(
                        "reasoning_delta",
                        message_id=message_id,
                        payload={"text": reasoning},
                    )
                )

            for chunk in message.tool_call_chunks:
                index = int(chunk.get("index") or 0)
                state_key = (provider_message_id, index)
                state = self.tool_states.get(state_key)
                if state is None:
                    # provider 尚未给 ID 时先建立 Run 内稳定身份，避免前端工具卡片漂移。
                    logical_id = str(
                        chunk.get("id")
                        or f"{message_id or self.run_id}:tool:{index}"
                    )
                    state = {"logical_id": logical_id, "name": None}
                    self.tool_states[state_key] = state

                provider_id = chunk.get("id")
                if provider_id:
                    self.provider_to_logical_id[str(provider_id)] = str(
                        state["logical_id"]
                    )
                if chunk.get("name"):
                    if state["name"] is None:
                        # 只在工具名首次出现时记录，避免参数分片刷屏。
                        logger.info(
                            "模型发起工具调用：run_id=%s tool=%s",
                            self.run_id,
                            chunk["name"],
                        )
                    state["name"] = str(chunk["name"])

                projected.append(
                    self._event(
                        "tool_call_delta",
                        message_id=message_id,
                        payload={
                            "tool_call_id": state["logical_id"],
                            "name": state["name"],
                            "arguments_delta": _arguments_delta(chunk.get("args")),
                            "index": index,
                        },
                    )
                )
            if provider_message_id is None and message.chunk_position == "last":
                self.anonymous_ai_generation += 1
            return projected

        if isinstance(message, ToolMessage):
            if message.name == "ask_clarification" and message.status == "success":
                # 澄清是正常完成的 Agent 回合，不应与用户取消或执行失败混淆。
                self.finish_reason = "clarification_requested"
            provider_id = str(message.tool_call_id)
            message_id = _public_message_id(
                self.run_namespace,
                message_kind="tool-result",
                provider_message_id=provider_message_id,
                fallback_identity=provider_id,
            )
            result_payload: dict[str, object] = {
                "tool_call_id": self.provider_to_logical_id.get(
                    provider_id,
                    provider_id,
                ),
                "name": message.name,
                "content": message.text,
            }
            result_meta = (message.additional_kwargs or {}).get(
                TOOL_RESULT_META_KEY
            )
            if isinstance(result_meta, dict):
                result_payload["result_meta"] = result_meta
            projected.append(
                self._event(
                    "tool_result",
                    message_id=message_id,
                    # 工具结果映射回参数分片第一次公开的逻辑调用 ID。
                    payload=result_payload,
                )
            )
            logger.info(
                "工具返回结果：run_id=%s tool=%s tool_call_id=%s result_chars=%d",
                self.run_id,
                message.name,
                message.tool_call_id,
                len(message.text),
            )
        return projected

    def failed(self, exc: Exception) -> RunEvent:
        """记录脱敏失败并创建公开 run_error 事件。"""
        logger.error(
            "Agent run 执行失败：error_type=%s",
            type(exc).__name__,
            extra={"run_id": self.run_id},
        )
        return self._event(
            "run_error",
            message_id=None,
            payload={
                "code": "agent_execution_failed",
                "message": "Agent execution failed",
                "retryable": True,
            },
        )

    def completed(
        self,
        terminal_payload: dict[str, object] | None = None,
    ) -> RunEvent:
        """创建正常结束事件。"""
        payload: dict[str, object] = {
            "finish_reason": self.finish_reason,
            **self.run_usage,
        }
        if terminal_payload is not None:
            payload.update(terminal_payload)
        return self._event(
            "run_completed",
            message_id=None,
            payload=payload,
        )


class _DeltaBatcher:
    """合并连续 token/参数碎片，避免每个 token 都触发 SQLite 事务与渲染。"""

    def __init__(self) -> None:
        self._pending: RunEvent | None = None
        self._sequence = 0

    @staticmethod
    def _merge(first: RunEvent, second: RunEvent) -> RunEvent | None:
        if first.event != second.event or first.message_id != second.message_id:
            return None
        if first.event in {"ai_delta", "reasoning_delta"}:
            return replace(
                first,
                payload={
                    "text": str(first.payload.get("text") or "")
                    + str(second.payload.get("text") or "")
                },
            )
        if first.event == "tool_call_delta" and (
            first.payload.get("tool_call_id") == second.payload.get("tool_call_id")
            and first.payload.get("index") == second.payload.get("index")
        ):
            return replace(
                first,
                payload={
                    **first.payload,
                    "name": first.payload.get("name") or second.payload.get("name"),
                    "arguments_delta": str(
                        first.payload.get("arguments_delta") or ""
                    )
                    + str(second.payload.get("arguments_delta") or ""),
                },
            )
        return None

    def _emit(self, event: RunEvent) -> RunEvent:
        self._sequence += 1
        return replace(event, sequence=self._sequence)

    def push(self, event: RunEvent) -> tuple[RunEvent, ...]:
        pending = self._pending
        if pending is None:
            if event.event in {"ai_delta", "reasoning_delta", "tool_call_delta"}:
                self._pending = event
                return ()
            return (self._emit(event),)
        merged = self._merge(pending, event)
        if merged is not None:
            content = (
                merged.payload.get("arguments_delta")
                if merged.event == "tool_call_delta"
                else merged.payload.get("text")
            )
            if len(str(content or "")) < _DELTA_BATCH_CHARS:
                self._pending = merged
                return ()
            self._pending = None
            return (self._emit(merged),)
        self._pending = None
        emitted = [self._emit(pending)]
        if event.event in {"ai_delta", "reasoning_delta", "tool_call_delta"}:
            self._pending = event
        else:
            emitted.append(self._emit(event))
        return tuple(emitted)

    def flush(self) -> tuple[RunEvent, ...]:
        if self._pending is None:
            return ()
        pending = self._pending
        self._pending = None
        return (self._emit(pending),)


def project_run_events(
    events: Iterable[AgentMessageEvent],
    *,
    run_id: str,
    thread_id: str,
) -> Iterator[RunEvent]:
    """同步投影消息，保留 CLI 与现有学习示例。"""
    state = _RunProjectionState(run_id, thread_id)
    batcher = _DeltaBatcher()
    yield from batcher.push(state.started())
    try:
        for source in events:
            for event in state.project_message(source):
                yield from batcher.push(event)
    except Exception as exc:
        yield from batcher.push(state.failed(exc))
        yield from batcher.flush()
        return
    yield from batcher.push(state.completed())
    yield from batcher.flush()


async def aproject_run_events(
    events: AsyncIterable[AgentMessageEvent],
    *,
    run_id: str,
    thread_id: str,
    terminal_payload: Callable[[], dict[str, object]] | None = None,
) -> AsyncIterator[RunEvent]:
    """异步投影消息；CancelledError 不会被普通异常处理误写成 run_error。"""
    state = _RunProjectionState(run_id, thread_id)
    batcher = _DeltaBatcher()
    for event in batcher.push(state.started()):
        yield event
    try:
        async for source in events:
            for event in state.project_message(source):
                for batched in batcher.push(event):
                    yield batched
    except Exception as exc:
        for event in batcher.push(state.failed(exc)):
            yield event
        for event in batcher.flush():
            yield event
        return
    for event in batcher.push(
        state.completed(terminal_payload() if terminal_payload is not None else None)
    ):
        yield event
    for event in batcher.flush():
        yield event
