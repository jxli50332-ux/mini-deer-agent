"""管理后台 Agent Run、事件订阅与显式幂等取消。"""

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from mini_deer_agent.application.conversations import ConversationRepository
from mini_deer_agent.application.run_stream import RunContextSnapshot, RunStreamService
from mini_deer_agent.application.goals import GoalEvaluationService
from mini_deer_agent.domain import Attachment
from mini_deer_agent.domain import require_benchmark_case
from mini_deer_agent.streaming.events import RunEvent


logger = logging.getLogger(__name__)
_QUEUE_CAPACITY = 256
_DEFAULT_CANCEL_GRACE_SECONDS = 5.0
_DEFAULT_RUN_TIMEOUT_SECONDS = 900.0
_TERMINAL_EVENTS = {"run_completed", "run_error", "run_interrupted"}
_GOAL_CONTROL_ABORT_REASONS = {
    "goal_cleared",
    "goal_replaced",
    "goal_stopped",
}


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
    timeout_task: asyncio.Task[None] | None = None
    timeout_triggered: bool = False
    last_sequence: int = 0
    abort_reason: str = "user_cancelled"
    terminal: bool = False
    context_snapshot: RunContextSnapshot | None = None
    goal_context_revision: str | None = None


class RunExecutionManager:
    """在应用生命周期内注册后台 Run，并统一处理开始、订阅和取消。"""

    def __init__(
        self,
        stream_service: RunStreamService,
        conversation_repository: ConversationRepository,
        *,
        cancel_grace_seconds: float = _DEFAULT_CANCEL_GRACE_SECONDS,
        run_timeout_seconds: float = _DEFAULT_RUN_TIMEOUT_SECONDS,
        goal_evaluation_service: GoalEvaluationService | None = None,
    ) -> None:
        """保存执行源和产品仓储；Task 句柄永远不会写入数据库。"""
        if cancel_grace_seconds <= 0:
            raise ValueError("cancel_grace_seconds must be positive")
        if run_timeout_seconds <= 0:
            raise ValueError("run_timeout_seconds must be positive")
        self._stream_service = stream_service
        self._conversation_repository = conversation_repository
        self._cancel_grace_seconds = cancel_grace_seconds
        self._run_timeout_seconds = run_timeout_seconds
        self._active_runs: dict[str, _ActiveRun] = {}
        self._shutting_down = False
        self._goal_evaluation_service = goal_evaluation_service
        self._goal_context_snapshots: dict[str, RunContextSnapshot] = {}

    async def start_run(
        self,
        message: str,
        thread_id: str,
        user_message_id: str,
        attachments: tuple[Attachment, ...] = (),
        human_input_response: dict[str, object] | None = None,
        benchmark_case_id: str | None = None,
        internal_continuation: bool = False,
        skill_install_authorization_token: str | None = None,
    ) -> StartedRun:
        """先持久化 Run，再无等待窗口地附加后台执行 Task。"""
        if self._shutting_down:
            raise RuntimeError("Run execution manager is shutting down")

        snapshot_factory = getattr(self._stream_service, "create_context_snapshot", None)
        goal_context_revision: str | None = None
        revision_reader = getattr(
            self._goal_evaluation_service,
            "current_revision",
            None,
        )
        if callable(revision_reader):
            goal_context_revision = await revision_reader(thread_id)
        context_snapshot = (
            self._goal_context_snapshots.get(thread_id)
            if goal_context_revision is not None
            else None
        )
        if context_snapshot is None and goal_context_revision is not None:
            loader = getattr(
                self._conversation_repository,
                "get_goal_context_snapshot",
                None,
            )
            restorer = getattr(
                self._stream_service,
                "restore_context_snapshot",
                None,
            )
            stored = (
                await asyncio.to_thread(loader, thread_id)
                if callable(loader)
                else None
            )
            if stored is not None and stored[0] == goal_context_revision:
                if not callable(restorer):
                    raise RuntimeError("Stored Goal context cannot be restored")
                try:
                    context_snapshot = restorer(stored[1])
                except Exception as exc:
                    raise RuntimeError("Stored Goal context cannot be restored") from exc
                self._goal_context_snapshots[thread_id] = context_snapshot
            elif stored is not None:
                deleter = getattr(
                    self._conversation_repository,
                    "delete_goal_context_snapshot",
                    None,
                )
                if callable(deleter):
                    await asyncio.to_thread(deleter, thread_id)
        if context_snapshot is None:
            context_snapshot = snapshot_factory() if callable(snapshot_factory) else None
        run_id = str(uuid4())
        create_run_kwargs: dict[str, object] = dict(
            thread_id=thread_id,
            run_id=run_id,
            user_message_id=user_message_id,
            user_message=message,
            attachments=attachments,
            human_input_response=human_input_response,
            hidden_from_ui=internal_continuation,
        )
        if benchmark_case_id is not None:
            require_benchmark_case(benchmark_case_id)
            create_run_kwargs["benchmark_case_id"] = benchmark_case_id
        await asyncio.to_thread(
            self._conversation_repository.create_run,
            **create_run_kwargs,
        )

        if skill_install_authorization_token is not None:
            binder = getattr(
                self._stream_service,
                "bind_skill_install_authorization",
                None,
            )
            try:
                if not callable(binder):
                    raise RuntimeError(
                        "Skill install authorization is unavailable"
                    )
                await asyncio.to_thread(
                    binder,
                    skill_install_authorization_token,
                    thread_id=thread_id,
                    run_id=run_id,
                )
            except BaseException:
                await asyncio.shield(
                    asyncio.to_thread(
                        self._conversation_repository.interrupt_run,
                        thread_id=thread_id,
                        run_id=run_id,
                        error_code="skill_install_authorization_failed",
                    )
                )
                raise

        started_event = RunEvent(
            event="run_started",
            run_id=run_id,
            thread_id=thread_id,
            sequence=1,
            message_id=None,
            payload={
                "created_at": datetime.now(UTC).isoformat(),
                **(context_snapshot.metadata if context_snapshot is not None else {}),
            },
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

        active = _ActiveRun(
            run_id=run_id,
            thread_id=thread_id,
            context_snapshot=context_snapshot,
            goal_context_revision=goal_context_revision,
        )
        active.last_sequence = 1
        active.events.put_nowait(started_event)
        # 从注册到 create_task 之间没有 await，取消请求不会观察到半附加状态。
        self._active_runs[run_id] = active
        try:
            active.task = asyncio.create_task(
                self._execute(
                    active,
                    message,
                    attachments,
                    human_input_response,
                    internal_continuation,
                ),
                name=f"mini-deer-run-{run_id}",
            )
            active.timeout_task = asyncio.create_task(
                self._timeout_active_run(active),
                name=f"mini-deer-run-timeout-{run_id}",
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
        attachments: tuple[Attachment, ...],
        human_input_response: dict[str, object] | None,
        initial_internal_continuation: bool = False,
    ) -> None:
        """驱动异步 LangGraph，把事件先持久化再发布给 SSE 订阅者。"""
        logger.info(
            "Run 开始执行：run_id=%s thread_id=%s",
            active.run_id,
            active.thread_id,
        )
        terminal_event: str | None = None
        goal_evaluated = False
        goal_revision: str | None = None
        try:
            goal_revision = (
                await self._goal_evaluation_service.resume_for_user_run(
                    active.thread_id,
                    is_human_input_response=human_input_response is not None,
                )
                if self._goal_evaluation_service is not None
                else None
            )
            if goal_revision is not None and active.context_snapshot is not None:
                if (
                    active.goal_context_revision is not None
                    and active.goal_context_revision != goal_revision
                ):
                    raise RuntimeError("Goal changed while restoring its context snapshot")
                self._goal_context_snapshots.setdefault(
                    active.thread_id,
                    active.context_snapshot,
                )
                serializer = getattr(
                    self._stream_service,
                    "serialize_context_snapshot",
                    None,
                )
                saver = getattr(
                    self._conversation_repository,
                    "save_goal_context_snapshot",
                    None,
                )
                if callable(serializer) and callable(saver):
                    await asyncio.to_thread(
                        saver,
                        thread_id=active.thread_id,
                        goal_revision=goal_revision,
                        snapshot_json=serializer(active.context_snapshot),
                    )
            goal_budget_tracker = (
                self._stream_service.create_run_budget_tracker(active.run_id)
                if goal_revision is not None
                else None
            )
            if goal_revision is not None and (
                initial_internal_continuation or human_input_response is not None
            ):
                # 显式恢复和澄清恢复会在创建产品 Run 前改变 Goal；从第一帧
                # 主动通知前端，避免栏位在轮询到来前仍显示旧的暂停/停止态。
                resumed_event = RunEvent(
                    event="goal_status",
                    run_id=active.run_id,
                    thread_id=active.thread_id,
                    sequence=active.last_sequence + 1,
                    message_id=None,
                    payload={"phase": "updated"},
                )
                if not await self._persist_and_publish(active, resumed_event):
                    return
            round_message = message
            round_attachments = attachments
            round_human_response = human_input_response
            internal_continuation = initial_internal_continuation
            while True:
                snapshot_options = (
                    {
                        "model_snapshot": active.context_snapshot.model,
                        "skill_catalog": active.context_snapshot.skill_catalog,
                        "skill_creation_enabled": (
                            active.context_snapshot.skill_creation_enabled
                        ),
                    }
                    if active.context_snapshot is not None
                    else {}
                )
                if goal_budget_tracker is not None:
                    stream = self._stream_service.astream_run_events(
                        round_message,
                        active.thread_id,
                        active.run_id,
                        round_attachments,
                        round_human_response,
                        run_budget_tracker=goal_budget_tracker,
                        internal_continuation=internal_continuation,
                        **snapshot_options,
                    )
                elif round_human_response is None:
                    stream = self._stream_service.astream_run_events(
                        round_message,
                        active.thread_id,
                        active.run_id,
                        round_attachments,
                        **snapshot_options,
                    )
                else:
                    stream = self._stream_service.astream_run_events(
                        round_message,
                        active.thread_id,
                        active.run_id,
                        round_attachments,
                        round_human_response,
                        **snapshot_options,
                    )
                held_terminal: RunEvent | None = None
                async for source_event in stream:
                    if source_event.event == "run_started":
                        # 每轮投影都会生成本地 started；产品 Run 只保留首次已持久化事件。
                        continue
                    if active.abort_event.is_set():
                        raise asyncio.CancelledError
                    event = replace(
                        source_event,
                        sequence=active.last_sequence + 1,
                    )
                    if event.event in _TERMINAL_EVENTS and goal_revision is not None:
                        held_terminal = event
                        continue
                    if not await self._persist_and_publish(active, event):
                        return
                    if event.event in _TERMINAL_EVENTS:
                        terminal_event = event.event

                if held_terminal is None:
                    break
                try:
                    evaluating_event = RunEvent(
                        event="goal_status",
                        run_id=active.run_id,
                        thread_id=active.thread_id,
                        sequence=active.last_sequence + 1,
                        message_id=None,
                        payload={"phase": "evaluating"},
                    )
                    if not await self._persist_and_publish(active, evaluating_event):
                        return
                    evaluation = await self._goal_evaluation_service.evaluate_run(
                        thread_id=active.thread_id,
                        run_id=active.run_id,
                        terminal_event=held_terminal.event,
                        expected_revision=goal_revision,
                    )
                    goal_evaluated = True
                    if evaluation is not None and evaluation["satisfied"]:
                        await self._release_goal_context(active.thread_id)
                    if evaluation is not None and held_terminal.event == "run_completed":
                        finish_reason = held_terminal.payload.get("finish_reason")
                        decision = (
                            await self._goal_evaluation_service.prepare_continuation(
                                thread_id=active.thread_id,
                                evaluation=evaluation,
                                expected_revision=goal_revision,
                                budget_stop_reason=(
                                    finish_reason
                                    if isinstance(finish_reason, str)
                                    else None
                                ),
                            )
                        )
                        if decision.continue_run and decision.message is not None:
                            updated_event = RunEvent(
                                event="goal_status",
                                run_id=active.run_id,
                                thread_id=active.thread_id,
                                sequence=active.last_sequence + 1,
                                message_id=None,
                                payload={"phase": "updated"},
                            )
                            if not await self._persist_and_publish(active, updated_event):
                                return
                            round_message = decision.message
                            round_attachments = ()
                            round_human_response = None
                            internal_continuation = True
                            goal_evaluated = False
                            continue
                    updated_event = RunEvent(
                        event="goal_status",
                        run_id=active.run_id,
                        thread_id=active.thread_id,
                        sequence=active.last_sequence + 1,
                        message_id=None,
                        payload={"phase": "updated"},
                    )
                    if not await self._persist_and_publish(active, updated_event):
                        return
                except Exception as exc:
                    # Goal 是附加控制层；评估器或 checkpoint 故障不能吞掉已经成功的
                    # 产品 Run 终态，否则 Thread 会永久停留在 busy。
                    goal_evaluated = True
                    logger.error(
                        "Goal evaluation failed before Run completion: error_type=%s",
                        type(exc).__name__,
                        extra={"run_id": active.run_id},
                    )
                    failed_event = RunEvent(
                        event="goal_status",
                        run_id=active.run_id,
                        thread_id=active.thread_id,
                        sequence=active.last_sequence + 1,
                        message_id=None,
                        payload={"phase": "evaluation_failed"},
                    )
                    if not await self._persist_and_publish(active, failed_event):
                        return
                held_terminal = replace(
                    held_terminal,
                    sequence=active.last_sequence + 1,
                )
                if not await self._persist_and_publish(active, held_terminal):
                    return
                terminal_event = held_terminal.event
                break
            if terminal_event is None:
                raise RuntimeError("Run stream ended without a terminal event")
            logger.info("Run 执行完成：run_id=%s", active.run_id)
        except asyncio.CancelledError:
            logger.info(
                "Run 被中断：run_id=%s reason=%s",
                active.run_id,
                active.abort_reason,
            )
            if (
                not active.terminal
                and not goal_evaluated
                and goal_revision is not None
                and active.abort_reason not in _GOAL_CONTROL_ABORT_REASONS
            ):
                goal_evaluated = await self._evaluate_goal_before_terminal(
                    active,
                    goal_revision=goal_revision,
                    terminal_event="run_interrupted",
                )
            if not active.terminal:
                await self._finish_interrupted(active)
            terminal_event = "run_interrupted"
        except Exception as exc:
            # 只记录异常类型，避免模型、工具或数据库异常正文泄露敏感信息。
            logger.error(
                "后台 Run 管理失败：error_type=%s",
                type(exc).__name__,
                extra={"run_id": active.run_id},
            )
            if (
                not active.terminal
                and not goal_evaluated
                and goal_revision is not None
            ):
                goal_evaluated = await self._evaluate_goal_before_terminal(
                    active,
                    goal_revision=goal_revision,
                    terminal_event="run_error",
                )
            if not active.terminal:
                error_event = RunEvent(
                    event="run_error",
                    run_id=active.run_id,
                    thread_id=active.thread_id,
                    sequence=active.last_sequence + 1,
                    message_id=None,
                    payload={
                        "code": "run_execution_manager_failed",
                        "message": "Agent execution failed",
                        "retryable": True,
                    },
                )
                try:
                    await self._persist_and_publish(active, error_event)
                except Exception:
                    await asyncio.shield(
                        asyncio.to_thread(
                            self._conversation_repository.interrupt_run,
                            thread_id=active.thread_id,
                            run_id=active.run_id,
                            error_code="run_execution_manager_failed",
                        )
                    )
            terminal_event = "run_error"
        finally:
            if (
                self._goal_evaluation_service is not None
                and terminal_event is not None
                and not goal_evaluated
                and active.abort_reason not in _GOAL_CONTROL_ABORT_REASONS
            ):
                try:
                    evaluation = await self._goal_evaluation_service.evaluate_run(
                        thread_id=active.thread_id,
                        run_id=active.run_id,
                        terminal_event=terminal_event,
                        expected_revision=goal_revision,
                    )
                    if evaluation is not None and evaluation["satisfied"]:
                        await self._release_goal_context(active.thread_id)
                except Exception as exc:
                    logger.error(
                        "Goal evaluation failed after Run terminal: error_type=%s",
                        type(exc).__name__,
                        extra={"run_id": active.run_id},
                    )
            active.terminal = True
            await active.events.put(_END_OF_RUN)
            if (
                active.timeout_task is not None
                and not active.timeout_triggered
                and active.timeout_task is not asyncio.current_task()
            ):
                active.timeout_task.cancel()
            if self._active_runs.get(active.run_id) is active:
                self._active_runs.pop(active.run_id, None)

    async def _evaluate_goal_before_terminal(
        self,
        active: _ActiveRun,
        *,
        goal_revision: str,
        terminal_event: str,
    ) -> bool:
        """在管理器自行产生终态时先写 Goal，避免终态刷新读取到旧状态。"""
        if self._goal_evaluation_service is None:
            return False
        try:
            evaluating_event = RunEvent(
                event="goal_status",
                run_id=active.run_id,
                thread_id=active.thread_id,
                sequence=active.last_sequence + 1,
                message_id=None,
                payload={"phase": "evaluating"},
            )
            if not await self._persist_and_publish(active, evaluating_event):
                return True
            evaluation = await self._goal_evaluation_service.evaluate_run(
                thread_id=active.thread_id,
                run_id=active.run_id,
                terminal_event=terminal_event,
                expected_revision=goal_revision,
            )
            if evaluation is not None and evaluation["satisfied"]:
                await self._release_goal_context(active.thread_id)
            updated_event = RunEvent(
                event="goal_status",
                run_id=active.run_id,
                thread_id=active.thread_id,
                sequence=active.last_sequence + 1,
                message_id=None,
                payload={"phase": "updated"},
            )
            await self._persist_and_publish(active, updated_event)
        except Exception as exc:
            logger.error(
                "Goal evaluation failed before manager terminal: error_type=%s",
                type(exc).__name__,
                extra={"run_id": active.run_id},
            )
            try:
                failed_event = RunEvent(
                    event="goal_status",
                    run_id=active.run_id,
                    thread_id=active.thread_id,
                    sequence=active.last_sequence + 1,
                    message_id=None,
                    payload={"phase": "evaluation_failed"},
                )
                await self._persist_and_publish(active, failed_event)
            except Exception:
                pass
        return True

    async def _timeout_active_run(self, active: _ActiveRun) -> None:
        """给整个产品 Run（含隐藏续跑）设置最终截止时间。"""
        try:
            await asyncio.sleep(self._run_timeout_seconds)
            active.timeout_triggered = True
            await self.cancel_run(
                active.thread_id,
                active.run_id,
                reason="run_timeout",
            )
        except asyncio.CancelledError:
            return

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
        applied = await asyncio.shield(
            asyncio.to_thread(
                self._conversation_repository.apply_run_event,
                event,
            )
        )
        # 第一个终态写入者独占公开终态；并发取消不能重复发送相同 sequence。
        if not applied:
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
            # 某些模型或工具可能吞掉 CancelledError。这里只给底层 Task 有界宽限期，
            # 超时后以持久终态释放 Thread，迟到事件会被仓储的终态条件拒绝。
            done, _ = await asyncio.wait(
                {task},
                timeout=self._cancel_grace_seconds,
            )
            if task not in done:
                logger.warning(
                    "Run 取消等待超时，强制收敛持久状态：run_id=%s reason=%s",
                    active.run_id,
                    reason,
                )
                self._discard_buffered_events(active)
                await self._finish_interrupted(active)
                active.terminal = True
                await active.events.put(_END_OF_RUN)
                if self._active_runs.get(active.run_id) is active:
                    self._active_runs.pop(active.run_id, None)

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

    async def cancel_active_run(
        self,
        thread_id: str,
        *,
        reason: str,
    ) -> CancelOutcome:
        """按 Thread 取消本进程唯一活动 Run，供 Goal/Thread 控制面复用。"""
        active = next(
            (
                candidate
                for candidate in self._active_runs.values()
                if candidate.thread_id == thread_id and not candidate.terminal
            ),
            None,
        )
        if active is None:
            if reason in _GOAL_CONTROL_ABORT_REASONS:
                await self._release_goal_context(thread_id)
            return CancelOutcome.not_active
        if reason in _GOAL_CONTROL_ABORT_REASONS:
            await self._release_goal_context(thread_id)
        return await self.cancel_run(thread_id, active.run_id, reason=reason)

    async def _release_goal_context(self, thread_id: str) -> None:
        """同时释放进程内和 SQLite 中的 Goal 冻结上下文。"""
        self._goal_context_snapshots.pop(thread_id, None)
        deleter = getattr(
            self._conversation_repository,
            "delete_goal_context_snapshot",
            None,
        )
        if callable(deleter):
            await asyncio.to_thread(deleter, thread_id)

    async def release_goal_context(self, thread_id: str) -> None:
        """供空闲 Thread 的 Goal 控制面显式释放持久快照。"""
        await self._release_goal_context(thread_id)

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
