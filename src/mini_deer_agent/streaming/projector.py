"""把 LangGraph 原始消息投影为稳定的产品级 run 事件。"""

import json
import logging
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from langchain_core.messages import AIMessageChunk, ToolMessage

from mini_deer_agent.streaming.events import AgentMessageEvent, RunEvent, RunEventName


logger = logging.getLogger(__name__)


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
            provider_id = str(message.tool_call_id)
            message_id = _public_message_id(
                self.run_namespace,
                message_kind="tool-result",
                provider_message_id=provider_message_id,
                fallback_identity=provider_id,
            )
            projected.append(
                self._event(
                    "tool_result",
                    message_id=message_id,
                    payload={
                        # 工具结果映射回参数分片第一次公开的逻辑调用 ID。
                        "tool_call_id": self.provider_to_logical_id.get(
                            provider_id,
                            provider_id,
                        ),
                        "name": message.name,
                        "content": message.text,
                    },
                )
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

    def completed(self) -> RunEvent:
        """创建正常结束事件。"""
        return self._event(
            "run_completed",
            message_id=None,
            payload={"finish_reason": "stop"},
        )


def project_run_events(
    events: Iterable[AgentMessageEvent],
    *,
    run_id: str,
    thread_id: str,
) -> Iterator[RunEvent]:
    """同步投影消息，保留 CLI 与现有学习示例。"""
    state = _RunProjectionState(run_id, thread_id)
    yield state.started()
    try:
        for source in events:
            yield from state.project_message(source)
    except Exception as exc:
        yield state.failed(exc)
        return
    yield state.completed()


async def aproject_run_events(
    events: AsyncIterable[AgentMessageEvent],
    *,
    run_id: str,
    thread_id: str,
) -> AsyncIterator[RunEvent]:
    """异步投影消息；CancelledError 不会被普通异常处理误写成 run_error。"""
    state = _RunProjectionState(run_id, thread_id)
    yield state.started()
    try:
        async for source in events:
            for event in state.project_message(source):
                yield event
    except Exception as exc:
        yield state.failed(exc)
        return
    yield state.completed()
