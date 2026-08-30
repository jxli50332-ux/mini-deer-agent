"""管理后台 Agent Run、事件订阅与显式幂等取消。"""

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from mini_deer_agent.application.conversations import ConversationRepository
from mini_deer_agent.application.run_stream import RunStreamService
from mini_deer_agent.domain import TextAttachment
from mini_deer_agent.streaming.events import RunEvent


logger = logging.getLogger(__name__)
_QUEUE_CAPACITY = 256
_TERMINAL_EVENTS = {"run_completed", "run_error", "run_interrupted"}


class CancelOutcome(StrEnum):
    """描述取消命令的业务结果，不与 Run 持久化状态混用。"""

    cancelled = "cancelled"
    not_found = "not_found"
    not_cancellable = "not_cancellable"
    not_active = "not_active"


@dataclass(frozen=True, slots=True)
class StartedRun:
    """保存响应头需要的 Run ID 和当前 Run 的异步事件订阅。"""

    run_id: str
    events: AsyncIterator[RunEvent]


@dataclass(frozen=True, slots=True)
class _EndOfRun:
    """表示进程内事件队列已经结束，不会进入公开 SSE 协议。"""


_END_OF_RUN = _EndOfRun()


@dataclass(slots=True)
class _ActiveRun:
    """保存只在当前进程有效的 Task、取消信号和订阅队列。"""

    run_id: str
    thread_id: str
    events: asyncio.Queue[RunEvent | _EndOfRun] = field(
        default_factory=lambda: asyncio.Queue(maxsize=_QUEUE_CAPACITY)
    )
    abort_event: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    task: asyncio.Task[None] | None = None
    last_sequence: int = 0
    abort_reason: str = "user_cancelled"
    terminal: bool = False


class RunExecutionManager:
    """在应用生命周期内注册后台 Run，并统一处理开始、订阅和取消。"""

    def __init__(
        self,
        stream_service: RunStreamService,
        conversation_repository: ConversationRepository,
    ) -> None:
        """保存执行源和产品仓储；Task 句柄永远不会写入数据库。"""
        self._stream_service = stream_service
        self._conversation_repository = conversation_repository
        self._active_runs: dict[str, _ActiveRun] = {}
        self._shutting_down = False

    async def start_run(
        self,
        message: str,
        thread_id: str,
        user_message_id: str,
        attachments: tuple[TextAttachment, ...] = (),
    ) -> StartedRun:
        """先持久化 Run，再无等待窗口地附加后台执行 Task。"""
        if self._shutting_down:
            raise RuntimeError("Run execution manager is shutting down")

        run_id = str(uuid4())
        await asyncio.to_thread(
            self._conversation_repository.create_run,
            thread_id=thread_id,
            run_id=run_id,
            user_message_id=user_message_id,
            user_message=message,
            attachments=attachments,
        )

        started_event = RunEvent(
            event="run_started",
            run_id=run_id,
            thread_id=thread_id,
            sequence=1,
            message_id=None,
            payload={"created_at": datetime.now(UTC).isoformat()},
        )
        try:
            await asyncio.to_thread(
                self._conversation_repository.apply_run_event,
                started_event,
            )
        except BaseException:
            await asyncio.shield(
                asyncio.to_thread(
                    self._conversation_repository.interrupt_run,
                    thread_id=thread_id,
                    run_id=run_id,
                    error_code="run_start_persistence_failed",
                )
            )
            raise

        active = _ActiveRun(run_id=run_id, thread_id=thread_id)
        active.last_sequence = 1
        active.events.put_nowait(started_event)
        # 从注册到 create_task 之间没有 await，取消请求不会观察到半附加状态。
        self._active_runs[run_id] = active
        try:
            active.task = asyncio.create_task(
                self._execute(active, message, attachments),
                name=f"mini-deer-run-{run_id}",
            )
        except BaseException:
            self._active_runs.pop(run_id, None)
            await asyncio.shield(
                asyncio.to_thread(
                    self._conversation_repository.interrupt_run,
                    thread_id=thread_id,
                    run_id=run_id,
                    error_code="run_task_attach_failed",
                )
            )
            raise

        return StartedRun(
            run_id=run_id,
            events=self._subscribe(active),
        )

    async def _execute(
        self,
        active: _ActiveRun,
        message: str,
        attachments: tuple[TextAttachment, ...],
    ) -> None:
        """驱动异步 LangGraph，把事件先持久化再发布给 SSE 订阅者。"""
        try:
            async for event in self._stream_service.astream_run_events(
                message,
                active.thread_id,
                active.run_id,
                attachments,
            ):
                if event.event == "run_started" and event.sequence == 1:
                    # start_run 已在返回响应前持久化并排队，投影器的同一事件不重复发送。
                    continue
                if active.abort_event.is_set():
                    raise asyncio.CancelledError
                if not await self._persist_and_publish(active, event):
                    return
        except asyncio.CancelledError:
            if not active.terminal:
                await self._finish_interrupted(active)
        except Exception as exc:
            # 只记录异常类型，避免模型、工具或数据库异常正文泄露敏感信息。
            logger.error(
                "后台 Run 管理失败：error_type=%s",
                type(exc).__name__,
                extra={"run_id": active.run_id},
            )
            await asyncio.shield(
                asyncio.to_thread(
                    self._conversation_repository.interrupt_run,
                    thread_id=active.thread_id,
                    run_id=active.run_id,
                    error_code="run_execution_manager_failed",
                )
            )
        finally:
            active.terminal = True
            await active.events.put(_END_OF_RUN)
            if self._active_runs.get(active.run_id) is active:
                self._active_runs.pop(active.run_id, None)

    async def _persist_and_publish(
        self,
        active: _ActiveRun,
        event: RunEvent,
    ) -> bool:
        """保证单条事件的数据库写入与排队不会被取消切成半个状态。"""
        persistence_task = asyncio.create_task(
            asyncio.to_thread(
                self._conversation_repository.apply_run_event,
                event,
            )
        )
        try:
            applied = await asyncio.shield(persistence_task)
        except asyncio.CancelledError:
            # to_thread 已开始后不能被强杀；等待它结束并完成事件排队，再传播取消。
            applied = await persistence_task
            if applied:
                active.last_sequence = event.sequence
                active.terminal = event.event in _TERMINAL_EVENTS
                await active.events.put(event)
            raise

        if not applied:
            # 已写入的终态赢得竞争，迟到事件既不入库也不进入 SSE。
            return False
        active.last_sequence = event.sequence
        active.terminal = event.event in _TERMINAL_EVENTS
        await active.events.put(event)
        return True

    async def _finish_interrupted(self, active: _ActiveRun) -> None:
        """把用户停止、连接断开或服务关闭物化为正式终止事件。"""
        event = RunEvent(
            event="run_interrupted",
            run_id=active.run_id,
            thread_id=active.thread_id,
            sequence=active.last_sequence + 1,
            message_id=None,
            payload={"reason": active.abort_reason},
        )
        await asyncio.shield(
            asyncio.to_thread(
                self._conversation_repository.apply_run_event,
                event,
            )
        )
        persisted = await asyncio.shield(
            asyncio.to_thread(
                self._conversation_repository.get_run,
                active.run_id,
            )
        )
        # 若自然完成抢先落库，就不能再向客户端伪造 interrupted 终态。
        if persisted is None or persisted.status != "interrupted":
            return
        active.last_sequence = event.sequence
        active.terminal = True
        await active.events.put(event)

    async def _close_cancelled_before_worker_start(
        self,
        active: _ActiveRun,
    ) -> None:
        """处理 Task 在第一次获得执行机会前就被取消的启动竞争。"""
        if active.terminal:
            return
        await self._finish_interrupted(active)
        active.terminal = True
        await active.events.put(_END_OF_RUN)
        if self._active_runs.get(active.run_id) is active:
            self._active_runs.pop(active.run_id, None)

    @staticmethod
    def _discard_buffered_events(active: _ActiveRun) -> None:
        """取消时丢弃尚未展示的增量，为终止事件腾出确定空间。"""
        while True:
            try:
                active.events.get_nowait()
            except asyncio.QueueEmpty:
                return

    async def cancel_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        reason: str = "user_cancelled",
    ) -> CancelOutcome:
        """幂等取消活动 Run，并等待终止状态完成持久化。"""
        persisted = await asyncio.to_thread(
            self._conversation_repository.get_run,
            run_id,
        )
        if persisted is None or persisted.thread_id != thread_id:
            return CancelOutcome.not_found
        if persisted.status == "interrupted":
            active = self._active_runs.get(run_id)
            if active is not None and active.task is not None:
                # 并发重复取消不能在首个请求尚未完成清理时提前宣告完全停止。
                await asyncio.shield(
                    asyncio.gather(active.task, return_exceptions=True)
                )
            return CancelOutcome.cancelled
        if persisted.status not in {"pending", "running"}:
            return CancelOutcome.not_cancellable

        active = self._active_runs.get(run_id)
        if active is None:
            # 为未来多 worker 留出明确结果，不能把别的进程的 Run 当成本地成功取消。
            return CancelOutcome.not_active

        async with active.cancel_lock:
            persisted = await asyncio.to_thread(
                self._conversation_repository.get_run,
                run_id,
            )
            if persisted is None or persisted.thread_id != thread_id:
                return CancelOutcome.not_found
            if persisted.status == "interrupted":
                return CancelOutcome.cancelled
            if persisted.status not in {"pending", "running"}:
                return CancelOutcome.not_cancellable

            active.abort_reason = reason
            active.abort_event.set()
            if reason in {"client_disconnected", "service_shutdown"}:
                # 无订阅者时必须腾空队列，否则终止事件可能被背压永久阻塞。
                self._discard_buffered_events(active)
            task = active.task
            if task is None:
                return CancelOutcome.not_active
            if not task.done():
                task.cancel()
            # gather(return_exceptions=True) 把“底层 Task 自身已取消”和“当前 HTTP
            # 请求被取消”分开；后者仍会由 shield 向上传播。
            await asyncio.shield(asyncio.gather(task, return_exceptions=True))

            final_record = await asyncio.to_thread(
                self._conversation_repository.get_run,
                run_id,
            )
            if final_record is not None and final_record.status in {
                "pending",
                "running",
            }:
                await self._close_cancelled_before_worker_start(active)
                final_record = await asyncio.to_thread(
                    self._conversation_repository.get_run,
                    run_id,
                )
            if final_record is not None and final_record.status == "interrupted":
                return CancelOutcome.cancelled
            return CancelOutcome.not_cancellable

    async def _subscribe(self, active: _ActiveRun) -> AsyncIterator[RunEvent]:
        """订阅一个 Run；浏览器断开时复用同一取消状态机。"""
        try:
            while True:
                item = await active.events.get()
                if isinstance(item, _EndOfRun):
                    return
                yield item
        finally:
            if not active.terminal:
                await self.cancel_run(
                    active.thread_id,
                    active.run_id,
                    reason="client_disconnected",
                )

    async def shutdown(self) -> None:
        """应用退出时取消并等待所有本机 Run，避免关闭数据库后仍有写入。"""
        self._shutting_down = True
        active_runs = list(self._active_runs.values())
        if not active_runs:
            return
        await asyncio.gather(
            *(
                self.cancel_run(
                    active.thread_id,
                    active.run_id,
                    reason="service_shutdown",
                )
                for active in active_runs
            ),
            return_exceptions=True,
        )
